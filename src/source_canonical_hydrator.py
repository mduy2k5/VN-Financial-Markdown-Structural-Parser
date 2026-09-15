from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .source_statement_recovery import RecoveredRow

try:
    from .source_statement_recovery import clean, fold, parse_number
except ImportError:
    from source_statement_recovery import clean, fold, parse_number


def _source_id(statement: str, label: str, code: str, line: Optional[int], hierarchy_path: str = "") -> str:
    h = hashlib.sha1(f"{fold(label)}|{clean(code)}|{fold(hierarchy_path)}|{line or 0}".encode("utf-8")).hexdigest()[:14]
    return f"SOURCE.{statement}.{h}"


def extract_code_period_table(text: str, start_line: int, end_line: int, current_year: int = 2025, previous_year: int = 2024):
    """Extract code/current/previous evidence from label-less pipe tables.

    Used when OCR renders labels on one block/page and the statutory code/value columns on another.
    It never creates a semantic identity by itself; it can only hydrate an existing unique form-code node.
    """
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
        out.append({"code": code, "current": nums[-2], "previous": nums[-1], "source_line": s + idx + 1, "pattern": "CODE_PERIOD_PIPE"})
    return out


def hydrate_canonical_by_form_code(canonical: dict | None, evidence: list[dict], sector: str, method: str):
    if not canonical or not evidence:
        return canonical
    semantic = [n for n in canonical.get("nodes", []) if n.get("kind") != "source_observation"]
    by_code = {}
    for n in semantic:
        if clean(n.get("sector")) != clean(sector):
            continue
        nm = clean(n.get("method"))
        if nm not in {clean(method), "any"}:
            continue
        code = clean(n.get("form_code") or "")
        if code:
            by_code.setdefault(code, []).append(n)
    filled = conflicts = 0
    for ev in evidence:
        cand = by_code.get(clean(ev.get("code")), [])
        if len(cand) != 1:
            continue
        n = cand[0]
        v = n.setdefault("value", {})
        changed = False
        for period in ("current", "previous"):
            new = ev.get(period)
            if new is None:
                continue
            if v.get(period) is None:
                v[period] = new
                changed = True
            elif v.get(period) != new:
                conflicts += 1
        if changed:
            filled += 1
            n.setdefault("extraction_meta", {}).setdefault("form_code_period_fills", []).append(ev)
    canonical.setdefault("diagnostics", {})["form_code_period_recovery"] = {
        "policy": "unique_profile_form_code_fill_missing_only_v16",
        "evidence_rows": len(evidence), "filled_nodes": filled, "conflicts": conflicts,
    }
    return canonical


def augment_canonical_with_recovered_rows(canonical: dict | None, rows: list[Any], statement: str) -> dict | None:
    if not canonical:
        return canonical
    nodes = canonical.setdefault("nodes", [])
    # Index exact label+code first; then unique exact label.  We only overwrite missing periods on semantic nodes.
    by_lc: dict[tuple, list[dict]] = {}
    by_l: dict[str, list[dict]] = {}
    by_code: dict[str, list[dict]] = {}
    for n in nodes:
        fl = fold(n.get("canonical_name"))
        if not fl:
            continue
        code = clean(n.get("form_code") or "")
        by_lc.setdefault((fl, code), []).append(n)
        by_l.setdefault(fl, []).append(n)
        if code:
            by_code.setdefault(code, []).append(n)

    added = filled = conflicts = 0
    seen_source = set()
    for r in rows:
        fl = fold(r.label)
        code = clean(r.code or "")
        if not fl:
            continue
        # Explicit form code is stronger identity evidence than label alone.
        # If source has a code but the schema node has no matching form_code, preserve the
        # recovered row as a source_observation instead of collapsing it into a same-label
        # subtotal/group node (e.g. 150 vs 155, 260 vs 268).
        candidates = by_lc.get((fl, code), []) if code else []
        # v22.4: within a statement, an explicit unique form code is stronger identity
        # evidence than a short/ambiguous label (e.g. 131 vs 211 both "Phải thu khách hàng").
        if code and not candidates and len(by_code.get(code, [])) == 1:
            candidates = by_code[code]
        if not code and not candidates and len(by_l.get(fl, [])) == 1:
            candidates = by_l[fl]
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
                    "current": r.current, "previous": r.previous, "code": r.code, "note": r.note,
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

        key = (fl, code, fold(r.parent_label or ""), fold(r.hierarchy_path or ""), r.current, r.previous)
        if key in seen_source:
            continue
        seen_source.add(key)
        stmt_u = canonical.get("unit")
        eff_u = r.unit or stmt_u
        cname = fold(r.label)
        if "lai co ban" in cname or "lai suy giam" in cname:
            node_u = "vnd_per_share"
        else:
            node_u = eff_u
        node = {
            "node_id": _source_id(statement, r.label, code, r.source_line, r.hierarchy_path or r.parent_label or ""),
            "canonical_name": clean(r.label),
            "kind": "source_observation",
            "semantic_role": "recovered_source_row",
            "sector": canonical.get("sector"),
            "method": canonical.get("method"),
            "section": r.section,
            "parent_label": r.parent_label,
            "hierarchy_path": r.hierarchy_path,
            "form_code": code or None,
            "value": {
                "current": r.current, "previous": r.previous, "note": r.note,
                "unit": node_u, "raw_text": clean(r.label),
            },
            "extraction_meta": {
                "source_recovery": True,
                "occurrences": [{
                    "source_line": r.source_line, "source_label": clean(r.label), "pattern": r.pattern,
                    "current": r.current, "previous": r.previous, "code": r.code, "note": r.note,
                    "parent_label": r.parent_label, "hierarchy_path": r.hierarchy_path,
                }],
            },
        }
        nodes.append(node)
        by_lc.setdefault((fl, code), []).append(node)
        by_l.setdefault(fl, []).append(node)
        if code:
            by_code.setdefault(code, []).append(node)
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
                        "node_id": _source_id(statement, contextual_label, code, r.source_line, (r.hierarchy_path or "") + "|contextual"),
                        "canonical_name": contextual_label,
                        "kind": "source_observation",
                        "semantic_role": "contextual_source_identity",
                        "sector": canonical.get("sector"),
                        "method": canonical.get("method"),
                        "section": r.section,
                        "parent_label": r.parent_label,
                        "hierarchy_path": r.hierarchy_path,
                        "form_code": code or None,
                        "value": {"current": r.current, "previous": r.previous, "note": r.note, "unit": node_u, "raw_text": clean(r.label)},
                        "extraction_meta": {
                            "source_recovery": True, "contextual_identity": True,
                            "occurrences": [{"source_line": r.source_line, "source_label": clean(r.label), "contextual_label": contextual_label, "pattern": r.pattern}]
                        },
                    }
                    nodes.append(ctx)
                    by_l.setdefault(cfl, []).append(ctx)
                    by_lc.setdefault((cfl, code), []).append(ctx)
                    added += 1

    canonical.setdefault("diagnostics", {})["source_statement_recovery"] = {
        "statement": statement, "rows_recovered": len(rows), "added_nodes": added,
        "filled_existing_nodes": filled, "conflicts": conflicts,
        "policy": "source_scope_structural_identity_repair_v22_4_1",
    }
    return canonical
