from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Iterable

try:
    from .structural_identity import occurrence_rank as _next_occurrence_rank, structural_identity
except ImportError:
    from structural_identity import occurrence_rank as _next_occurrence_rank, structural_identity


def _clean(s: Any) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"[*_`#]+", "", s)
    return re.sub(r"\s+", " ", s).strip(" |:\t\r\n")


def _fold(s: Any) -> str:
    s = unicodedata.normalize("NFD", _clean(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _number(v: Any):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s or s in {"-", "–", "—", "..."}:
        return 0 if s == "-" else None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("() ").replace(" ", "").replace("−", "-")
    s = re.sub(r"(?i)(?:tri[eệ]u|ngh[iì]n|vnd|vnđ|đ[oồ]ng)$", "", s).strip()
    try:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
            x = int(s.replace(".", ""))
        elif re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", s):
            x = int(s.replace(",", ""))
        elif re.fullmatch(r"-?\d+", s):
            x = int(s)
        elif re.fullmatch(r"-?\d+[.,]\d+", s):
            x = float(s.replace(",", "."))
        else:
            return None
        return -abs(x) if neg else x
    except Exception:
        return None


def _row_raw_text(row: Any, fallback: str) -> str:
    """Return preserved source serialization when an extractor supplied it."""

    direct = getattr(row, "raw_text", None)
    if direct:
        return str(direct).strip()
    raw = getattr(row, "raw", None)
    if isinstance(raw, dict):
        for key in ("raw_text", "source_text"):
            if raw.get(key):
                return str(raw[key]).strip()
        lines = raw.get("raw_lines")
        if isinstance(lines, list):
            joined = "\n".join(str(line).strip() for line in lines if str(line).strip())
            if joined:
                return joined
    return fallback


def _source_id(
    statement: str,
    label: str,
    section: str = "",
    code: str = "",
    *,
    parent_label: str = "",
    hierarchy_path: str = "",
    occurrence: int | None = None,
) -> str:
    # ``code`` remains an API-compatible argument, but deliberately does not
    # participate in identity. Codes may be detached or may refer to a
    # different document layer (the Notes section).
    identity = structural_identity(
        statement=statement,
        label=label,
        section=section,
        parent_label=parent_label,
        hierarchy_path=hierarchy_path,
        occurrence_rank=occurrence,
    )
    key = "|".join(identity)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
    return f"SOURCE.{statement}.{h}"


def _existing_labels(canonical: dict) -> set[str]:
    out = set()
    for n in canonical.get("nodes") or []:
        name = _fold(n.get("canonical_name"))
        if name:
            out.add(name)
        for o in ((n.get("extraction_meta") or {}).get("occurrences") or []):
            f = _fold(o.get("source_label"))
            if f:
                out.add(f)
    return out


def augment_from_rows(canonical: dict | None, rows: Iterable[Any], statement: str) -> dict | None:
    """Append source-preserving observations without changing semantic nodes.

    This is deliberately schema-additive: semantic nodes remain authoritative while rows that
    cannot be represented by the current universal schema are still available losslessly.
    """
    if not canonical:
        return canonical
    nodes = canonical.setdefault("nodes", [])
    semantic_labels = {_fold(n.get("canonical_name")) for n in nodes if n.get("kind") != "source_observation"}
    seen = set()
    ranks: dict[tuple[str, ...], int] = {}
    added = 0
    for r in rows:
        label = _clean(getattr(r, "label", None) or getattr(r, "source_label", None))
        if not label:
            continue
        current = _number(getattr(r, "current", None))
        previous = _number(getattr(r, "previous", None))
        if current is None and previous is None:
            continue
        section = _clean(getattr(r, "section", None) or "")
        statement_code = _clean(
            getattr(r, "statement_code", None) or getattr(r, "code", None) or ""
        )
        note_ref = _clean(
            getattr(r, "note_ref", None) or getattr(r, "note", None) or ""
        )
        raw_text = _row_raw_text(r, label)
        parent_label = _clean(getattr(r, "parent_label", None) or "")
        hierarchy_path = _clean(getattr(r, "hierarchy_path", None) or "")
        base_identity = structural_identity(
            statement=statement,
            label=label,
            section=section,
            parent_label=parent_label,
            hierarchy_path=hierarchy_path,
        )
        # A repeated parser observation with a different code/note is still
        # the same structural row.  Assign an occurrence rank only after this
        # code-independent duplicate check.
        duplicate_key = (base_identity, current, previous)
        if duplicate_key in seen:
            continue
        rank = _next_occurrence_rank(
            ranks,
            statement=statement,
            label=label,
            section=section,
            parent_label=parent_label,
            hierarchy_path=hierarchy_path,
        )
        key = (structural_identity(
            statement=statement,
            label=label,
            section=section,
            parent_label=parent_label,
            hierarchy_path=hierarchy_path,
            occurrence_rank=rank,
        ), current, previous)
        if key in seen:
            continue
        seen.add(duplicate_key)
        # Materialize even mapped rows when source label differs from canonical wording.
        # Exact duplicates of a semantic canonical name add no evaluator/downstream value.
        if _fold(label) in semantic_labels:
            continue
        node = {
            "node_id": _source_id(
                statement,
                label,
                section,
                statement_code,
                parent_label=parent_label,
                hierarchy_path=hierarchy_path,
                occurrence=rank,
            ),
            "canonical_name": label,
            "kind": "source_observation",
            "semantic_role": "supplemental_source_row",
            "sector": canonical.get("sector"),
            "method": canonical.get("method"),
            "section": section or None,
            # Kept for compatibility with older consumers; it is metadata,
            # never the source-observation identity.
            "form_code": statement_code or None,
            "statement_code": statement_code or None,
            "note_ref": note_ref or None,
            "value": {
                "current": current,
                "previous": previous,
                "note": note_ref or None,
                "unit": getattr(r, "unit", None),
                "raw_text": raw_text,
            },
            "extraction_meta": {
                "source_preservation": True,
                "mapping_status": getattr(r, "mapping_status", None),
                "mapping_method": getattr(r, "mapping_method", None),
                "occurrences": [{
                    "source_line": getattr(r, "source_line", None),
                    "source_label": label,
                    "raw_text": raw_text,
                    "pattern": getattr(r, "pattern", None),
                    "current": current,
                    "previous": previous,
                    "code": statement_code or None,
                    "statement_code": statement_code or None,
                    "note": note_ref or None,
                    "note_ref": note_ref or None,
                    "section": section or None,
                    "parent_label": parent_label or None,
                    "hierarchy_path": hierarchy_path or None,
                    "occurrence_rank": rank,
                }],
            },
        }
        nodes.append(node)
        added += 1
    d = canonical.setdefault("diagnostics", {})
    d["source_observation_layer"] = {
        "enabled": True,
        "statement": statement,
        "added_nodes": added,
        "policy": "schema_additive_preserve_structural_rows",
    }
    return canonical
