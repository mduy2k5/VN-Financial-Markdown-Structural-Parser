"""Optional schema aliases for Notes.

Notes are not a fixed two-column statement.  A bank disclosure can add rows,
repeat the same measure under different periods, or emit a matrix with more
columns than the statutory statements.  This module therefore treats aliases
as annotations, never as a filter or a replacement for the source tree.

The catalog is intentionally optional and sector-scoped.  A row that does not
match an alias receives ``storage_mode=raw_tree`` and remains available with
its original label, hierarchy, values, headers and raw cells.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .sectionizer import fold_text, normalize_note_id


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALIAS_PATHS = {
    "bank_v1": ROOT / "resources" / "schemas" / "notes_aliases_bank_v1.json",
    "enterprise_v1": ROOT / "resources" / "schemas" / "notes_aliases_enterprise_v1.json",
    "securities_v1": ROOT / "resources" / "schemas" / "notes_aliases_securities_v1.json",
    "insurance_v1": ROOT / "resources" / "schemas" / "notes_aliases_insurance_v1.json",
}


def load_alias_catalog(profile: str, path: str | Path | None = None) -> dict[str, Any]:
    """Load one optional Notes alias catalog.

    ``profile`` is explicit so a new catalog can be tested in isolation and
    rolled back by selecting ``none``/``legacy`` without changing parser code.
    """

    if profile in {"", "none", "off", None}:
        return {}
    alias_path = Path(path) if path is not None else DEFAULT_ALIAS_PATHS.get(profile)
    if alias_path is None:
        raise ValueError(f"Unknown Notes alias profile: {profile}")
    raw = json.loads(alias_path.read_text(encoding="utf-8"))
    if raw.get("alias_type") != "notes" or raw.get("profile") != profile:
        raise ValueError(f"Invalid Notes alias catalog for profile: {profile}")
    return raw


def _normalized_set(values: Iterable[Any]) -> set[str]:
    return {fold_text(str(value)) for value in values if str(value or "").strip()}


def _title_without_continuation(value: str) -> str:
    """Fold a title while treating a continuation heading as the same topic."""

    folded = fold_text(value)
    return folded.removesuffix(" tiep theo").strip()


def _section_match_score(
    section: Any,
    spec: dict[str, Any],
    *,
    strict_note_id: bool = False,
) -> int:
    """Score a section candidate without letting a reused note number win.

    Enterprise B09 reuses numbers in several groups (for example item ``1``
    appears in accounting policies, balance-sheet notes and income notes).
    An id-only match is therefore only a weak fallback.  Exact title wins over
    the id, and a continuation heading is allowed to reuse its base title.
    """

    note_id = normalize_note_id(getattr(section, "note_id_normalized", None))
    note_ids = {
        normalize_note_id(str(value))
        for value in (spec.get("note_ids") or [])
        if str(value or "").strip()
    }
    id_match = bool(note_id and note_id in note_ids)
    if strict_note_id and note_id and note_ids and not id_match:
        return 0
    title_values = [
        spec.get("canonical_name"),
        *(spec.get("titles") or []),
        *(spec.get("title_aliases") or []),
    ]
    title = fold_text(getattr(section, "title_raw", ""))
    title_match = title in _normalized_set(title_values)
    base_title = _title_without_continuation(getattr(section, "title_raw", ""))
    base_match = base_title in {
        _title_without_continuation(str(value))
        for value in title_values
        if str(value or "").strip()
    }
    if strict_note_id and id_match and not (title_match or base_match):
        return 0

    if id_match and title_match:
        return 5
    if title_match:
        return 4
    if id_match and base_match:
        return 3
    if base_match:
        return 2
    if id_match:
        return 1
    return 0


def _section_matches(section: Any, spec: dict[str, Any]) -> bool:
    """Backward-compatible boolean wrapper for callers outside this module."""

    return _section_match_score(section, spec) > 0


def _row_matches(row: Any, spec: dict[str, Any]) -> bool:
    label = fold_text(getattr(row, "label_raw", ""))
    aliases = [spec.get("canonical_name"), *(spec.get("aliases") or [])]
    if label not in _normalized_set(aliases):
        return False

    required_parent = _normalized_set(spec.get("parent_aliases") or [])
    if not required_parent:
        return True
    path = _normalized_set(getattr(row, "hierarchy_path", []) or [])
    return bool(path & required_parent)


def _block_column_count(block: Any) -> int:
    header_count = len(getattr(block, "headers_raw", []) or [])
    row_count = max(
        [len(getattr(row, "raw_cells", []) or []) for row in (getattr(block, "rows", []) or [])]
        or [0]
    )
    return max(header_count, row_count)


def _row_storage_metadata(
    row: Any,
    *,
    alias: dict[str, Any] | None,
    column_count: int,
    unmapped_reason: str | None = None,
) -> dict[str, Any]:
    """Return additive metadata without changing NoteRow/NoteValue fields."""

    if alias:
        return {
            "status": "mapped",
            "alias_id": alias.get("alias_id"),
            "canonical_name": alias.get("canonical_name"),
            "match_method": "section_scoped_exact_label",
            "confidence": 1.0,
            "storage_mode": "canonical_plus_raw",
            "raw_preserved": True,
            "column_count": column_count,
        }
    return {
        "status": "unmapped",
        "alias_id": None,
        "canonical_name": None,
        "match_method": None,
        "confidence": None,
        "storage_mode": "raw_tree",
        "raw_preserved": True,
        "column_count": column_count,
        **({"reason": unmapped_reason} if unmapped_reason else {}),
    }


def annotate_note_sections(
    sections: list[Any],
    *,
    sector: str,
    profile: str = "auto",
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Annotate parsed Notes with an optional, sector-specific alias catalog.

    The function mutates only ``metadata`` dictionaries.  Labels, hierarchy,
    raw cells and values are never rewritten.  This is the rollback boundary:
    turning the profile off produces the same parsed data without annotations.
    """

    requested = profile or "auto"
    if requested == "auto":
        requested = {
            "bank": "bank_v1",
            "enterprise": "enterprise_v1",
            "securities": "securities_v1",
            "insurance": "insurance_v1",
        }.get(sector, "none")
    if requested in {"none", "off"}:
        return {
            "enabled": False,
            "profile": None,
            "alias_schema_version": None,
            "section_count": len(sections),
            "matched_sections": 0,
            "mapped_rows": 0,
            "unmapped_rows": sum(
                len(getattr(block, "rows", []) or [])
                for section in sections
                for block in (getattr(section, "blocks", []) or [])
            ),
            "raw_tree_rows": sum(
                len(getattr(block, "rows", []) or [])
                for section in sections
                for block in (getattr(section, "blocks", []) or [])
            ),
            "multi_column_blocks": sum(
                1
                for section in sections
                for block in (getattr(section, "blocks", []) or [])
                if _block_column_count(block) > 2
            ),
            "policy": "no_alias_annotation_raw_tree_only",
        }

    catalog = load_alias_catalog(requested, path=path)
    section_specs = catalog.get("sections") or []
    matched_sections = mapped_rows = unmapped_rows = multi_column_blocks = 0

    for section in sections:
        strict_note_id = bool(
            (catalog.get("matching_policy") or {}).get("strict_note_id", False)
        )
        scored_specs = [
            (
                _section_match_score(
                    section,
                    candidate,
                    strict_note_id=strict_note_id,
                ),
                candidate,
            )
            for candidate in section_specs
        ]
        best_score = max((score for score, _ in scored_specs), default=0)
        best_specs = [candidate for score, candidate in scored_specs if score == best_score and score > 0]
        # Reused enterprise note numbers are deliberately not accepted by
        # number alone.  The raw section stays available until a title or
        # another context discriminator proves which family it belongs to.
        if best_score == 1 and len(best_specs) != 1:
            spec = None
            best_score = 0
        else:
            spec = best_specs[0] if best_specs else None
        if spec:
            matched_sections += 1
            section_status = {
                "status": "mapped",
                "alias_id": spec.get("alias_id"),
                "canonical_name": spec.get("canonical_name"),
                "match_method": (
                    "note_id_and_title_exact"
                    if best_score == 5
                    else "title_exact"
                    if best_score == 4
                    else "note_id_and_title_base"
                    if best_score == 3
                    else "title_base"
                    if best_score == 2
                    else "note_id_exact"
                ),
                "confidence": 1.0,
            }
        else:
            section_status = {
                "status": "unmapped",
                "alias_id": None,
                "canonical_name": None,
                "match_method": None,
                "confidence": None,
            }
        section.metadata = dict(getattr(section, "metadata", {}) or {})
        section.metadata["schema_alias"] = section_status

        row_specs = (spec or {}).get("rows") or []
        section_label_counts = Counter(
            fold_text(getattr(candidate_row, "label_raw", ""))
            for candidate_block in (getattr(section, "blocks", []) or [])
            for candidate_row in (getattr(candidate_block, "rows", []) or [])
        )
        for block in getattr(section, "blocks", []) or []:
            column_count = _block_column_count(block)
            is_multi_column = column_count > 2 or any(
                len(getattr(row, "values", []) or []) > 2
                for row in (getattr(block, "rows", []) or [])
            )
            if is_multi_column:
                multi_column_blocks += 1
            block.metadata = dict(getattr(block, "metadata", {}) or {})
            block.metadata["storage_policy"] = {
                "mode": "raw_matrix" if is_multi_column else "raw_tree",
                "raw_preserved": True,
                "header_count": len(getattr(block, "headers_raw", []) or []),
                "column_count": column_count,
                "unbounded_rows": True,
                "unmapped_rows_are_valid": True,
            }
            for row in getattr(block, "rows", []) or []:
                matching_specs = [candidate for candidate in row_specs if _row_matches(row, candidate)]
                label_count = section_label_counts.get(fold_text(getattr(row, "label_raw", "")), 0)
                row_alias = (
                    matching_specs[0]
                    if len(matching_specs) == 1
                    and (label_count <= 1 or matching_specs[0].get("allow_repeated") is True)
                    else None
                )
                reason = None
                if not row_alias and matching_specs and label_count > 1:
                    reason = "repeated_label_requires_hierarchy_or_block_context"
                storage = _row_storage_metadata(
                    row,
                    alias=row_alias,
                    column_count=column_count,
                    unmapped_reason=reason,
                )
                row.metadata = dict(getattr(row, "metadata", {}) or {})
                row.metadata["schema_alias"] = storage
                if row_alias:
                    mapped_rows += 1
                else:
                    unmapped_rows += 1

    return {
        "enabled": True,
        "profile": requested,
        "alias_schema_version": catalog.get("alias_schema_version"),
        "section_count": len(sections),
        "matched_sections": matched_sections,
        "mapped_rows": mapped_rows,
        "unmapped_rows": unmapped_rows,
        "raw_tree_rows": mapped_rows + unmapped_rows,
        "multi_column_blocks": multi_column_blocks,
        "unmatched_policy": copy.deepcopy(catalog.get("unmatched_policy") or {}),
        "multi_column_policy": copy.deepcopy(catalog.get("multi_column_policy") or {}),
        "policy": "alias_annotation_never_replaces_raw_tree_v1",
    }
