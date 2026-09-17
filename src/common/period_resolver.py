from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def _fold(v: Any) -> str:
    s = unicodedata.normalize("NFD", _clean(v))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def period_role_for_date(
    day: int,
    month: int,
    year: int,
    current_year: int | None,
    previous_year: int | None,
) -> str | None:
    """Map an explicit statement date to a comparative role.

    The parser years represent the calendar years of the statement end dates,
    not necessarily 31 December.  Therefore any date in the current end year
    is current evidence, except a day-one opening date; a date in the previous
    end year is prior evidence.  The caller remains responsible for restricting
    this helper to statement-scope text so administrative dates are not used.
    """

    if current_year is not None and year == current_year:
        if day == 1:
            return "previous"
        return "current"
    if previous_year is not None and year == previous_year:
        return "previous"
    return None


def _num(v: Any):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _clean(v).replace("−", "-")
    if not s or s in {"-", "–", "—"}:
        return 0.0 if s else None
    neg = s.startswith("(") and ")" in s
    s = s.strip().strip("()")
    m = re.match(r"-?\d[\d., ]*", s)
    if not m:
        return None
    s = m.group(0).replace(" ", "")
    try:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
            x = float(s.replace(".", ""))
        elif re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", s):
            x = float(s.replace(",", ""))
        elif re.fullmatch(r"-?\d+", s):
            x = float(s)
        elif "," in s and "." in s:
            x = float(re.sub(r"[.,]", "", s))
        else:
            # Financial-statement context: one 3-digit tail is overwhelmingly a thousands group.
            if re.fullmatch(r"-?\d+[.,]\d{3}", s):
                x = float(re.sub(r"[.,]", "", s))
            else:
                x = float(s.replace(",", "."))
        return -abs(x) if neg else x
    except Exception:
        return None


def _role_from_period_label(label: Any, current_year: int | None, previous_year: int | None):
    """Resolve FP current/previous from explicit statement semantics.

    Crucial rule: beginning-of-current-year (01/01/current_year) is the previous comparative
    balance even though the calendar year equals current_year.
    """
    f = _fold(label)
    if not f:
        return None
    if any(k in f for k in ("so cuoi nam", "cuoi nam", "cuoi ky", "so du cuoi nam", "tai ngay cuoi nam")):
        return "current"
    if any(k in f for k in ("so dau nam", "dau nam", "dau ky", "so du dau nam", "tai ngay dau nam", "trinh bay lai")):
        return "previous"
    if "nam nay" in f:
        return "current"
    if "nam truoc" in f:
        return "previous"

    # 1 January of current year == opening balance == previous comparative column.
    # Compact slash/dot dates and Vietnamese long dates survive folding as
    # spaces: 31 03 2026 / 31 thang 3 nam 2026.  Do not special-case December;
    # non-calendar fiscal years use the same year-relative rule.
    toks = re.findall(r"\d+", f)
    if len(toks) >= 3:
        for a, b, c in zip(toks, toks[1:], toks[2:]):
            try:
                d, m, y = int(a), int(b), int(c)
            except Exception:
                continue
            role = period_role_for_date(d, m, y, current_year, previous_year)
            if role:
                return role
    # Bare fiscal-year labels are only safe when they explicitly say Năm/year.
    if re.search(rf"\bnam {current_year}\b|\byear {current_year}\b", f):
        return "current"
    if re.search(rf"\bnam {previous_year}\b|\byear {previous_year}\b", f):
        return "previous"
    return None


def _consensus(candidates):
    """Return raw value only when explicit-period evidence has a unique numeric consensus."""
    vals = [(raw, _num(raw), src) for raw, src in candidates]
    vals = [(r, n, s) for r, n, s in vals if n is not None]
    if not vals:
        return None, []
    counts = Counter(n for _, n, _ in vals)
    top = counts.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None, vals
    winner = top[0][0]
    # Do not use a weak plurality among many contradictory observations.
    if top[0][1] < 2 and len(counts) > 1:
        return None, vals
    raw = next(r for r, n, _ in vals if n == winner)
    return raw, vals


def repair_financial_position_period_identity(canonical: dict | None, current_year: int | None = None, previous_year: int | None = None):
    if not canonical:
        return canonical
    repaired = 0
    conflicts = []
    examples = []
    for node in canonical.get("nodes") or []:
        if node.get("kind") == "source_observation":
            continue
        em = node.get("extraction_meta") or {}
        occurrences = em.get("occurrences") or []
        by_role = {"current": [], "previous": []}
        for occ in occurrences:
            for item in (occ.get("values") or []):
                role = _role_from_period_label(item.get("period_label") or item.get("role"), current_year, previous_year)
                if role:
                    by_role[role].append((item.get("raw_value"), {
                        "source_line": item.get("source_line") or occ.get("source_line"),
                        "period_label": item.get("period_label"),
                        "source_label": occ.get("source_label"),
                    }))
        value = node.setdefault("value", {})
        changes = {}
        for role in ("current", "previous"):
            chosen, evidence = _consensus(by_role[role])
            if chosen is None:
                if evidence and len({n for _, n, _ in evidence}) > 1:
                    conflicts.append({"node_id": node.get("node_id"), "role": role, "evidence": [x[2] | {"raw_value": x[0]} for x in evidence[:8]]})
                continue
            old = value.get(role)
            if _num(old) != _num(chosen):
                changes[role] = {"old": old, "new": chosen}
                value[role] = chosen
        if changes:
            repaired += 1
            if len(examples) < 40:
                examples.append({"node_id": node.get("node_id"), "label": node.get("canonical_name"), "changes": changes})
            em.setdefault("period_identity_repairs", []).append({
                "policy": "explicit_period_label_consensus_v16_1",
                "changes": changes,
            })
            node["extraction_meta"] = em
    canonical.setdefault("diagnostics", {})["financial_position_period_identity_repair"] = {
        "policy": "explicit_period_label_consensus_v16_1",
        "nodes_repaired": repaired,
        "conflicting_nodes": len({(x['node_id'], x['role']) for x in conflicts}),
        "examples": examples,
        "conflicts": conflicts[:80],
    }
    return canonical
