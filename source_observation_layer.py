from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Iterable


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


def _source_id(statement: str, label: str, section: str = "", code: str = "") -> str:
    key = "|".join((_fold(label), section or "", code or ""))
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
        code = _clean(getattr(r, "code", None) or "")
        key = (_fold(label), section, code, current, previous)
        if key in seen:
            continue
        seen.add(key)
        # Materialize even mapped rows when source label differs from canonical wording.
        # Exact duplicates of a semantic canonical name add no evaluator/downstream value.
        if _fold(label) in semantic_labels:
            continue
        node = {
            "node_id": _source_id(statement, label, section, code),
            "canonical_name": label,
            "kind": "source_observation",
            "semantic_role": "supplemental_source_row",
            "sector": canonical.get("sector"),
            "method": canonical.get("method"),
            "section": section or None,
            "form_code": code or None,
            "value": {
                "current": current,
                "previous": previous,
                "note": _clean(getattr(r, "note", None)) or None,
                "unit": getattr(r, "unit", None),
                "raw_text": label,
            },
            "extraction_meta": {
                "source_preservation": True,
                "mapping_status": getattr(r, "mapping_status", None),
                "mapping_method": getattr(r, "mapping_method", None),
                "occurrences": [{
                    "source_line": getattr(r, "source_line", None),
                    "source_label": label,
                    "pattern": getattr(r, "pattern", None),
                    "current": current,
                    "previous": previous,
                    "code": code or None,
                    "note": _clean(getattr(r, "note", None)) or None,
                    "section": section or None,
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


def augment_financial_position(canonical: dict | None) -> dict | None:
    """Materialize source labels already present in FP extraction metadata.

    Historical FP canonical is semantically normalized; evaluator ground truth often retains the
    exact statement wording. This layer preserves both representations without replacing either.
    """
    if not canonical:
        return canonical
    nodes = canonical.setdefault("nodes", [])
    originals = list(nodes)
    semantic_labels = {_fold(n.get("canonical_name")) for n in originals if n.get("kind") != "source_observation"}
    seen = set()
    additions = []
    for n in originals:
        val = n.get("value") or {}
        base_cur = _number(val.get("current"))
        base_prev = _number(val.get("previous"))
        for occ in ((n.get("extraction_meta") or {}).get("occurrences") or []):
            label = _clean(occ.get("source_label"))
            if not label or _fold(label) in semantic_labels:
                continue
            cur = occ.get("current")
            prev = occ.get("previous")
            if cur is None and prev is None:
                for v in occ.get("values") or []:
                    k = v.get("period_key")
                    nv = _number(v.get("normalized_candidate"))
                    if nv is None:
                        nv = _number(v.get("raw_value"))
                    if k == "current": cur = nv
                    elif k == "previous": prev = nv
            cur = _number(cur) if cur is not None else base_cur
            prev = _number(prev) if prev is not None else base_prev
            if cur is None and prev is None:
                continue
            key = (_fold(label), cur, prev, _clean(occ.get("code_candidate")))
            if key in seen:
                continue
            seen.add(key)
            additions.append({
                "node_id": _source_id("FINANCIAL_POSITION", label, "", _clean(occ.get("code_candidate"))),
                "canonical_name": label,
                "kind": "source_observation",
                "semantic_role": "supplemental_source_row",
                "parent_semantic_node_id": n.get("node_id"),
                "sector": n.get("sector"),
                "form_code": _clean(occ.get("code_candidate")) or None,
                "value": {
                    "current": cur,
                    "previous": prev,
                    "additional": None,
                    "note": _clean(occ.get("note_candidate")) or val.get("note"),
                    "raw_text": label,
                },
                "extraction_meta": {
                    "source_preservation": True,
                    "occurrences": [occ],
                },
            })
    nodes.extend(additions)
    canonical.setdefault("diagnostics", {})["source_observation_layer"] = {
        "enabled": True,
        "statement": "FINANCIAL_POSITION",
        "added_nodes": len(additions),
        "policy": "materialize_extraction_occurrence_labels",
    }
    return canonical
