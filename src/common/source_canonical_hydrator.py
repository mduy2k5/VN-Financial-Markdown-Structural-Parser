from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .source_recovery import RecoveredRow

try:
    from .source_recovery import clean, fold, parse_number
    from .structural_identity import occurrence_rank, structural_identity
    from .report_period import resolve_report_years
except ImportError:
    from source_recovery import clean, fold, parse_number
    from structural_identity import occurrence_rank, structural_identity
    from report_period import resolve_report_years


def _source_id(
    statement: str,
    label: str,
    code: str,
    line: Optional[int],
    hierarchy_path: str = "",
    *,
    section: str = "",
    occurrence: int | None = None,
) -> str:
    # ``code`` and source line are provenance, not semantic identity.  The
    # structural context plus occurrence rank keeps repeated labels distinct
    # without making a detached code column authoritative.
    key = "|".join(structural_identity(
        statement=statement,
        label=label,
        section=section,
        hierarchy_path=hierarchy_path,
        occurrence_rank=occurrence,
    ))
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
    return f"SOURCE.{statement}.{h}"


def extract_code_period_table(text: str, start_line: int, end_line: int, current_year: int | None = None, previous_year: int | None = None):
    """Extract period evidence from label-less pipe tables.

    The raw code is retained as provenance only.  This function must not be
    used to identify or hydrate a semantic node by code.
    """
    if current_year is None or previous_year is None:
        period = resolve_report_years(
            text,
            source_name="input",
            current_year=current_year,
            previous_year=previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
    lines = text.splitlines()
    s, e = max(0, start_line - 1), min(len(lines), end_line)
    out = []
    for idx, raw in enumerate(lines[s:e]):
        if raw.count("|") < 3:
            continue
        cells = [clean(x) for x in raw.strip().strip("|").split("|")]
        if not cells or any(fold(c) in {"ma so", "chi tieu"} for c in cells):
            continue
        code = next((c for c in cells[:2] if re.fullmatch(r"\d{2,4}(?:\.\d+)?", c)), None)
        if not code:
            continue
        nums = []
        for c in cells[1:]:
            v = parse_number(c)
            if v is not None:
                nums.append(v)
        if len(nums) < 2:
            continue
        out.append({
            "code": code,
            "statement_code": code,
            "current": nums[-2],
            "previous": nums[-1],
            "source_line": s + idx + 1,
            "pattern": "PERIOD_PIPE_EVIDENCE_ONLY",
        })
    return out


def hydrate_canonical_by_form_code(canonical: dict | None, evidence: list[dict], sector: str, method: str):
    if not canonical:
        return canonical
    # Compatibility entry point.  Code-only evidence is intentionally not
    # allowed to mutate semantic nodes.  Structural/semantic row extraction
    # must provide the label context before a value can be attached.
    canonical.setdefault("diagnostics", {})["form_code_period_recovery"] = {
        "policy": "evidence_only_no_code_identity_v23",
        "sector": sector,
        "method": method,
        "evidence_rows": len(evidence or []),
        "filled_nodes": 0,
        "conflicts": 0,
    }
    canonical.setdefault("diagnostics", {}).setdefault("period_evidence", []).extend(evidence or [])
    return canonical


def augment_canonical_with_recovered_rows(canonical: dict | None, rows: list[Any], statement: str) -> dict | None:
    if not canonical:
        return canonical
    nodes = canonical.setdefault("nodes", [])
    # Index by structural/semantic label only.  Codes and note references are
    # metadata and are deliberately excluded from identity and candidate lookup.
    by_l: dict[str, list[dict]] = {}
    for n in nodes:
        fl = fold(n.get("canonical_name"))
        if not fl:
            continue
        by_l.setdefault(fl, []).append(n)

    added = filled = conflicts = 0
    seen_source = set()
    source_ranks: dict[tuple[str, ...], int] = {}

    def section_matches(node: dict, row: Any) -> bool:
        """Keep bounded cash-flow schedules in their own identity domain."""
        if statement != "CASHFLOW":
            return True
        row_section = clean(getattr(row, "section", None) or "")
        if not row_section:
            return True
        return clean(node.get("section") or "") == row_section

    def source_identity_matches(node: dict, row: Any) -> bool:
        """Do not collapse repeated generic labels from different hierarchies."""

        if node.get("kind") != "source_observation" or statement != "FINANCIAL_POSITION":
            return True
        node_context = fold(node.get("hierarchy_path") or node.get("parent_label") or "")
        row_context = fold(getattr(row, "hierarchy_path", None) or getattr(row, "parent_label", None) or "")
        return not node_context or not row_context or node_context == row_context

    for r in rows:
        fl = fold(r.label)
        if not fl:
            continue
        candidates = [
            node for node in by_l.get(fl, [])
            if node.get("kind") != "source_observation"
            and section_matches(node, r)
            and source_identity_matches(node, r)
        ]
        # Fill missing periods where identity is unambiguous; never replace an existing non-null semantic value.
        if len(candidates) == 1:
            n = candidates[0]
            v = n.setdefault("value", {})
            changed = False
            if v.get("current") is None and r.current is not None:
                v["current"] = r.current
                changed = True
            if v.get("previous") is None and r.previous is not None:
                v["previous"] = r.previous
                changed = True
            stmt_unit = canonical.get("unit")
            eff_u = r.unit or stmt_unit
            if eff_u and (not v.get("unit") or v.get("unit") == "unknown"):
                cname = fold(n.get("canonical_name", ""))
                if "lai co ban" in cname or "lai suy giam" in cname:
                    v["unit"] = "vnd_per_share"
                else:
                    v["unit"] = eff_u
            if changed:
                filled += 1
                em = n.setdefault("extraction_meta", {})
                em.setdefault("source_recovery_occurrences", []).append({
                    "source_line": r.source_line, "source_label": r.label, "pattern": r.pattern,
                    "current": r.current, "previous": r.previous,
                    "code": r.code, "statement_code": getattr(r, "statement_code", None),
                    "note": r.note, "note_ref": getattr(r, "note_ref", None),
                    "parent_label": r.parent_label, "hierarchy_path": r.hierarchy_path,
                    "unit": r.unit, "unit_source": r.unit_source,
                })
                continue
            # Exact identity with differing values is valuable debug evidence, but avoid creating duplicate exact labels
            # that could make downstream row selection unstable.
            if ((r.current is not None and v.get("current") is not None and r.current != v.get("current")) or
                (r.previous is not None and v.get("previous") is not None and r.previous != v.get("previous"))):
                conflicts += 1
                canonical.setdefault("diagnostics", {}).setdefault("source_recovery_conflicts", []).append({
                    "label": r.label, "code": r.code, "source_line": r.source_line,
                    "recovered_current": r.current, "recovered_previous": r.previous,
                    "existing_current": v.get("current"), "existing_previous": v.get("previous"),
                })
            continue

        parent_label = fold(r.parent_label or "")
        hierarchy_path = fold(r.hierarchy_path or "")
        base_identity = structural_identity(
            statement=statement,
            label=r.label,
            section=r.section or "",
            parent_label=r.parent_label or "",
            hierarchy_path=r.hierarchy_path or "",
        )
        duplicate_key = (base_identity, r.current, r.previous)
        if duplicate_key in seen_source:
            continue
        rank = occurrence_rank(
            source_ranks,
            statement=statement,
            label=r.label,
            section=r.section or "",
            parent_label=r.parent_label or "",
            hierarchy_path=r.hierarchy_path or "",
        )
        key = (structural_identity(
            statement=statement,
            label=r.label,
            section=r.section or "",
            parent_label=r.parent_label or "",
            hierarchy_path=r.hierarchy_path or "",
            occurrence_rank=rank,
        ), r.current, r.previous)
        if key in seen_source:
            continue
        seen_source.add(duplicate_key)
        stmt_u = canonical.get("unit")
        eff_u = r.unit or stmt_u
        cname = fold(r.label)
        if "lai co ban" in cname or "lai suy giam" in cname:
            node_u = "vnd_per_share"
        else:
            node_u = eff_u
        node = {
            "node_id": _source_id(
                statement,
                r.label,
                getattr(r, "statement_code", None) or r.code or "",
                r.source_line,
                r.hierarchy_path or r.parent_label or "",
                section=r.section or "",
                occurrence=rank,
            ),
            "canonical_name": clean(r.label),
            "kind": "source_observation",
            "semantic_role": "recovered_source_row",
            "sector": canonical.get("sector"),
            "method": canonical.get("method"),
            "section": r.section,
            "parent_label": r.parent_label,
            "hierarchy_path": r.hierarchy_path,
            "form_code": getattr(r, "statement_code", None) or r.code or None,
            "statement_code": getattr(r, "statement_code", None) or r.code or None,
            "note_ref": getattr(r, "note_ref", None) or r.note or None,
            "value": {
                "current": r.current, "previous": r.previous,
                "note": getattr(r, "note_ref", None) or r.note,
                "unit": node_u, "raw_text": clean(r.label),
            },
            "extraction_meta": {
                "source_recovery": True,
                "occurrences": [{
                    "source_line": r.source_line, "source_label": clean(r.label), "pattern": r.pattern,
                    "current": r.current, "previous": r.previous,
                    "code": r.code, "statement_code": getattr(r, "statement_code", None),
                    "note": r.note, "note_ref": getattr(r, "note_ref", None),
                    "parent_label": r.parent_label, "hierarchy_path": r.hierarchy_path,
                    "occurrence_rank": rank,
                }],
            },
        }
        nodes.append(node)
        by_l.setdefault(fl, []).append(node)
        added += 1

        # v16.1: ambiguous short labels often require hierarchy to recover their real row identity.
        # Preserve the literal source row and add a contextual evidence alias; never replace it.
        if statement == "FINANCIAL_POSITION" and r.parent_label:
            generic = {
                "nguyen gia", "hao mon luy ke", "gia tri hao mon luy ke", "khau hao luy ke",
                "du phong", "gia tri con lai", "tong cong", "cong", "khac"
            }
            if fl in generic:
                if fl in {"tong cong", "cong"}:
                    contextual_label = clean(r.parent_label)
                else:
                    contextual_label = clean(f"{r.label} {r.parent_label}")
                cfl = fold(contextual_label)
                if cfl and cfl != fl and not by_l.get(cfl):
                    ctx = {
                        "node_id": _source_id(
                            statement,
                            contextual_label,
                            getattr(r, "statement_code", None) or r.code or "",
                            r.source_line,
                            (r.hierarchy_path or "") + "|contextual",
                            section=r.section or "",
                            occurrence=rank,
                        ),
                        "canonical_name": contextual_label,
                        "kind": "source_observation",
                        "semantic_role": "contextual_source_identity",
                        "sector": canonical.get("sector"),
                        "method": canonical.get("method"),
                        "section": r.section,
                        "parent_label": r.parent_label,
                        "hierarchy_path": r.hierarchy_path,
                        "form_code": getattr(r, "statement_code", None) or r.code or None,
                        "statement_code": getattr(r, "statement_code", None) or r.code or None,
                        "note_ref": getattr(r, "note_ref", None) or r.note or None,
                        "value": {"current": r.current, "previous": r.previous, "note": getattr(r, "note_ref", None) or r.note, "unit": node_u, "raw_text": clean(r.label)},
                        "extraction_meta": {
                            "source_recovery": True, "contextual_identity": True,
                            "occurrences": [{"source_line": r.source_line, "source_label": clean(r.label), "contextual_label": contextual_label, "pattern": r.pattern}]
                        },
                    }
                    nodes.append(ctx)
                    by_l.setdefault(cfl, []).append(ctx)
                    added += 1

    canonical.setdefault("diagnostics", {})["source_statement_recovery"] = {
        "statement": statement, "rows_recovered": len(rows), "added_nodes": added,
        "filled_existing_nodes": filled, "conflicts": conflicts,
        "policy": "source_scope_structural_identity_repair_v22_4_1",
    }
    return canonical
