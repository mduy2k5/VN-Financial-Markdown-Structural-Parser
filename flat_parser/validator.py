from __future__ import annotations
from decimal import Decimal, InvalidOperation


def _num(raw):
    if raw is None or raw == "-":
        return None
    s = str(raw).strip()
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.replace(".", "").replace(",", ".").replace(" ", "")
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if neg else v


def _value(node_map, node_id, period):
    node = node_map.get(node_id)
    if not node:
        return None
    return _num(node.get("value", {}).get(period))


def validate_financial_position(canonical):
    node_map = {n["node_id"]: n for n in canonical.get("nodes", [])}
    checks = []

    for period in ("current", "previous"):
        assets = _value(node_map, "TOTAL_ASSETS", period)
        le = _value(node_map, "TOTAL_LIABILITIES_AND_EQUITY", period)
        liab = _value(node_map, "TOTAL_LIABILITIES", period)
        eq = _value(node_map, "TOTAL_EQUITY", period)

        if assets is not None and le is not None:
            checks.append({
                "check": "assets_equals_liabilities_and_equity",
                "period": period,
                "status": "passed" if assets == le else "failed",
                "left": str(assets),
                "right": str(le),
            })

        if assets is not None and liab is not None and eq is not None:
            rhs = liab + eq
            checks.append({
                "check": "liabilities_plus_equity_equals_assets",
                "period": period,
                "status": "passed" if rhs == assets else "failed",
                "assets": str(assets),
                "liabilities_plus_equity": str(rhs),
            })

    failed = sum(1 for x in checks if x["status"] == "failed")

    def explicit_total(node_id):
        node = node_map.get(node_id) or {}
        occs = (node.get("extraction_meta") or {}).get("occurrences") or []
        return any(
            any(a.get("action") == "accept_first_period_value" for a in o.get("actions", []))
            for o in occs
        )

    explicit_four_totals = all(
        explicit_total(nid)
        for nid in (
            "TOTAL_ASSETS",
            "TOTAL_LIABILITIES",
            "TOTAL_EQUITY",
            "TOTAL_LIABILITIES_AND_EQUITY",
        )
    )

    return {
        "checks": checks,
        "passed": sum(1 for x in checks if x["status"] == "passed"),
        "failed": failed,
        "explicit_four_totals": explicit_four_totals,
        "classification": (
            "source_balance_inconsistent"
            if failed > 0 and explicit_four_totals
            else ("parser_or_source_balance_failure" if failed > 0 else "passed")
        ),
    }
