from __future__ import annotations

import re
import unicodedata
from typing import Any


def fold(s: Any) -> str:
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


BANK_ALWAYS_NEGATIVE_NODES = {
    "INCOME.BANK.INTEREST_EXPENSE",
    "INCOME.BANK.SERVICE_EXPENSE",
    "INCOME.BANK.OTHER_OPERATING_EXPENSE",
    "INCOME.BANK.OPERATING_EXPENSE",
    "INCOME.BANK.CREDIT_RISK_PROVISION_EXPENSE",
    "INCOME.BANK.CURRENT_TAX_EXPENSE",
    "INCOME.BANK.TAX_EXPENSE",
}


def _label_implies_income(label: str | None) -> bool:
    f = fold(label or "")
    return any(x in f for x in ("thu nhap", "loi ich", "hoan nhap"))


def _label_implies_expense(label: str | None) -> bool:
    f = fold(label or "")
    return any(x in f for x in ("chi phi", "lo", "du phong"))


def normalize_bank_semantic_signs(by: dict) -> list[dict]:
    """Chuẩn hóa giá trị B02 ngân hàng về quy ước cộng có dấu."""
    actions = []
    for nid, node in by.items():
        value = node.get("value") or {}
        occs = ((node.get("extraction_meta") or {}).get("occurrences") or [])
        source_label = next((o.get("source_label") for o in occs if o.get("source_label")), value.get("raw_text"))

        if nid in BANK_ALWAYS_NEGATIVE_NODES:
            target_sign = -1
        elif nid == "INCOME.BANK.DEFERRED_TAX_EXPENSE":
            if _label_implies_income(source_label):
                target_sign = 1
            elif _label_implies_expense(source_label):
                target_sign = -1
            else:
                target_sign = 0
        else:
            continue

        for period in ("current", "previous"):
            old = value.get(period)
            if old is None or target_sign == 0 or not isinstance(old, (int, float)):
                continue
            new = abs(old) * target_sign
            if new != old:
                value[period] = new
                actions.append({
                    "node_id": nid,
                    "period": period,
                    "source_label": source_label,
                    "from": old,
                    "to": new,
                    "reason": "bank_semantic_sign_normalization",
                })
    return actions


ENTERPRISE_PRESENTATION_MAGNITUDE_NODES = {
    "INCOME.ENTERPRISE.REVENUE_DEDUCTIONS",
    "INCOME.ENTERPRISE.COGS",
    "INCOME.ENTERPRISE.FINANCIAL_EXPENSE",
    "INCOME.ENTERPRISE.INTEREST_EXPENSE",
    "INCOME.ENTERPRISE.SELLING_EXPENSE",
    "INCOME.ENTERPRISE.GENERAL_ADMIN_EXPENSE",
    "INCOME.ENTERPRISE.OTHER_EXPENSE",
    "INCOME.ENTERPRISE.CURRENT_TAX_EXPENSE",
}


def normalize_enterprise_formula_signs(by: dict) -> list[dict]:
    """Tạo view chẩn đoán chuẩn hóa dấu cho công thức doanh nghiệp."""
    actions = []
    for nid in ENTERPRISE_PRESENTATION_MAGNITUDE_NODES:
        node = by.get(nid) or {}
        value = node.get("value") or {}
        for period in ("current", "previous"):
            old = value.get(period)
            if not isinstance(old, (int, float)):
                continue
            normalized = abs(old)
            if normalized != old:
                actions.append({
                    "node_id": nid,
                    "period": period,
                    "source_value": old,
                    "formula_value": normalized,
                    "reason": "enterprise_formula_magnitude_normalization",
                    "canonical_mutated": False,
                })
    return actions


SECURITIES_ALWAYS_NEGATIVE_NODES = {
    "INCOME.SECURITIES.FVTPL_LOSS",
    "INCOME.SECURITIES.FVTPL_SALE_LOSS",
    "INCOME.SECURITIES.FVTPL_REVALUATION_LOSS",
    "INCOME.SECURITIES.FVTPL_TRANSACTION_EXPENSE",
    "INCOME.SECURITIES.WARRANT_REVALUATION_LOSS",
    "INCOME.SECURITIES.AFS_RECLASSIFICATION_LOSS",
    "INCOME.SECURITIES.PROPRIETARY_TRADING_EXPENSE",
    "INCOME.SECURITIES.BROKERAGE_EXPENSE",
    "INCOME.SECURITIES.UNDERWRITING_EXPENSE",
    "INCOME.SECURITIES.CUSTODY_EXPENSE",
    "INCOME.SECURITIES.FINANCIAL_ADVISORY_EXPENSE",
    "INCOME.SECURITIES.OTHER_SERVICE_EXPENSE",
    "INCOME.SECURITIES.TOTAL_OPERATING_EXPENSE",
    "INCOME.SECURITIES.FX_LOSS",
    "INCOME.SECURITIES.INTEREST_EXPENSE",
    "INCOME.SECURITIES.OTHER_FINANCIAL_EXPENSE",
    "INCOME.SECURITIES.TOTAL_FINANCIAL_EXPENSE",
    "INCOME.SECURITIES.MANAGEMENT_EXPENSE",
    "INCOME.SECURITIES.OTHER_EXPENSE",
    "INCOME.SECURITIES.CURRENT_TAX_EXPENSE",
    "INCOME.SECURITIES.TAX_EXPENSE",
}


def normalize_securities_semantic_signs(by: dict) -> list[dict]:
    """Chuẩn hóa B02-CTCK thành giá trị cộng có dấu."""
    actions = []
    for nid, node in by.items():
        value = node.get("value") or {}
        occs = ((node.get("extraction_meta") or {}).get("occurrences") or [])
        source_label = next((o.get("source_label") for o in occs if o.get("source_label")), value.get("raw_text"))
        if nid in SECURITIES_ALWAYS_NEGATIVE_NODES:
            target_sign = -1
        elif nid in {"INCOME.SECURITIES.PROVISION_EXPENSE", "INCOME.SECURITIES.DEFERRED_TAX_EXPENSE"}:
            if _label_implies_income(source_label):
                target_sign = 1
            elif _label_implies_expense(source_label):
                target_sign = -1
            else:
                target_sign = 0
        elif nid == "INCOME.SECURITIES.UNREALIZED_PROFIT":
            f = fold(source_label or "")
            target_sign = -1 if "lo chua thuc hien" in f else 0
        else:
            continue
        for period in ("current", "previous"):
            old = value.get(period)
            if old is None or target_sign == 0 or not isinstance(old, (int, float)):
                continue
            new = abs(old) * target_sign
            if new != old:
                value[period] = new
                actions.append({
                    "node_id": nid, "period": period, "source_label": source_label,
                    "from": old, "to": new, "reason": "securities_semantic_sign_normalization",
                })
    return actions


def validate_securities_formulas(by: dict) -> list[dict]:
    checks = []
    def val(nid, period):
        return by.get(nid, {}).get("value", {}).get(period)
    def emit(name, period, reported, expected):
        if reported is None or expected is None:
            checks.append({"name": name, "period": period, "status": "skipped_missing_operand"})
            return
        diff = reported - expected
        tol = max(1e-6, abs(expected) * 1e-9)
        checks.append({
            "name": name, "period": period,
            "status": "pass" if abs(diff) <= tol else "fail",
            "reported": reported, "expected": expected, "difference": diff,
        })
    for period in ("current", "previous"):
        op_rev = val("INCOME.SECURITIES.TOTAL_OPERATING_REVENUE", period)
        op_exp = val("INCOME.SECURITIES.TOTAL_OPERATING_EXPENSE", period)
        fin_inc = val("INCOME.SECURITIES.TOTAL_FINANCIAL_INCOME", period)
        fin_exp = val("INCOME.SECURITIES.TOTAL_FINANCIAL_EXPENSE", period)
        mgmt = val("INCOME.SECURITIES.MANAGEMENT_EXPENSE", period)
        op_result = val("INCOME.SECURITIES.OPERATING_RESULT", period)
        if all(x is not None for x in (op_rev, op_exp, fin_inc, fin_exp, mgmt, op_result)):
            emit("operating_result", period, op_result, op_rev + op_exp + fin_inc + fin_exp + mgmt)
        else:
            checks.append({"name":"operating_result","period":period,"status":"skipped_missing_operand"})

        other_i = val("INCOME.SECURITIES.OTHER_INCOME", period)
        other_e = val("INCOME.SECURITIES.OTHER_EXPENSE", period)
        other_r = val("INCOME.SECURITIES.OTHER_RESULT", period)
        if all(x is not None for x in (other_i, other_e, other_r)):
            emit("other_result", period, other_r, other_i + other_e)
        else:
            checks.append({"name":"other_result","period":period,"status":"skipped_missing_operand"})

        pbt = val("INCOME.SECURITIES.PROFIT_BEFORE_TAX", period)
        if op_result is not None and other_r is not None and pbt is not None:
            emit("profit_before_tax", period, pbt, op_result + other_r)
        else:
            checks.append({"name":"profit_before_tax","period":period,"status":"skipped_missing_operand"})

        cur_tax = val("INCOME.SECURITIES.CURRENT_TAX_EXPENSE", period)
        def_tax = val("INCOME.SECURITIES.DEFERRED_TAX_EXPENSE", period)
        tax_total = val("INCOME.SECURITIES.TAX_EXPENSE", period)
        if cur_tax is not None and def_tax is not None and tax_total is not None:
            emit("tax_expense", period, tax_total, cur_tax + def_tax)
        else:
            checks.append({"name":"tax_expense","period":period,"status":"skipped_missing_operand"})

        pat = val("INCOME.SECURITIES.PROFIT_AFTER_TAX", period)
        if pbt is not None and tax_total is not None and pat is not None:
            emit("profit_after_tax", period, pat, pbt + tax_total)
        else:
            checks.append({"name":"profit_after_tax","period":period,"status":"skipped_missing_operand"})

        oci = val("INCOME.SECURITIES.OTHER_COMPREHENSIVE_INCOME", period)
        total_ci = val("INCOME.SECURITIES.TOTAL_COMPREHENSIVE_INCOME", period)
        if pat is not None and oci is not None and total_ci is not None:
            emit("total_comprehensive_income", period, total_ci, pat + oci)
        else:
            checks.append({"name":"total_comprehensive_income","period":period,"status":"skipped_missing_operand"})
    return checks


def validate_insurance_formulas(by: dict) -> list[dict]:
    """Validation bảo thủ cho báo cáo kết quả kinh doanh bảo hiểm hợp nhất."""
    checks = []
    def val(nid, period):
        return by.get(nid, {}).get("value", {}).get(period)
    def emit(name, period, target, parts):
        reported = val(target, period)
        vals = [val(x, period) for x in parts]
        if reported is None or any(v is None for v in vals):
            checks.append({"name": name, "period": period, "status": "skipped_missing_operand"})
            return
        expected = sum(vals)
        diff = reported - expected
        tol = max(1e-6, abs(expected) * 1e-9)
        checks.append({
            "name": name, "period": period,
            "status": "pass" if abs(diff) <= tol else "fail",
            "reported": reported, "expected": expected, "difference": diff,
        })
    for period in ("current", "previous"):
        emit("net_other_operations", period, "INCOME.INSURANCE.NET_OTHER_OPERATIONS", [
            "INCOME.INSURANCE.OTHER_OPERATING_REVENUE", "INCOME.INSURANCE.OTHER_OPERATING_EXPENSE"])
        emit("financial_profit", period, "INCOME.INSURANCE.FINANCIAL_PROFIT", [
            "INCOME.INSURANCE.FINANCIAL_REVENUE", "INCOME.INSURANCE.FINANCIAL_EXPENSE"])
        emit("other_profit", period, "INCOME.INSURANCE.OTHER_PROFIT", [
            "INCOME.INSURANCE.OTHER_INCOME", "INCOME.INSURANCE.OTHER_EXPENSE"])
        emit("profit_before_tax", period, "INCOME.INSURANCE.PROFIT_BEFORE_TAX", [
            "INCOME.INSURANCE.GROSS_INSURANCE_PROFIT",
            "INCOME.INSURANCE.NET_OTHER_OPERATIONS",
            "INCOME.INSURANCE.FINANCIAL_PROFIT",
            "INCOME.INSURANCE.SHARE_OF_PROFIT_ASSOCIATES",
            "INCOME.INSURANCE.SELLING_EXPENSE",
            "INCOME.INSURANCE.GENERAL_ADMIN_EXPENSE",
            "INCOME.INSURANCE.OTHER_PROFIT",
        ])
        emit("profit_after_tax", period, "INCOME.INSURANCE.PROFIT_AFTER_TAX", [
            "INCOME.INSURANCE.PROFIT_BEFORE_TAX",
            "INCOME.INSURANCE.CURRENT_TAX_EXPENSE",
            "INCOME.INSURANCE.DEFERRED_TAX_EXPENSE",
        ])
        emit("attributable_profit", period, "INCOME.INSURANCE.PROFIT_AFTER_TAX", [
            "INCOME.INSURANCE.PROFIT_ATTRIBUTABLE_PARENT",
            "INCOME.INSURANCE.PROFIT_ATTRIBUTABLE_NCI",
        ])
    return checks


def validate_enterprise_formulas(by: dict) -> list[dict]:
    """Kiểm tra doanh nghiệp theo quy ước độ lớn trình bày, với rule bảo thủ."""
    checks = []

    def val(nid, period):
        return by.get(nid, {}).get("value", {}).get(period)

    def emit(name, period, reported, expected):
        if reported is None or expected is None:
            checks.append({"name": name, "period": period, "status": "skipped_missing_operand"})
            return
        diff = reported - expected
        tol = max(1e-6, abs(expected) * 1e-9)
        checks.append({
            "name": name,
            "period": period,
            "status": "pass" if abs(diff) <= tol else "fail",
            "reported": reported,
            "expected": expected,
            "difference": diff,
        })

    for period in ("current", "previous"):
        gross = val("INCOME.ENTERPRISE.REVENUE_GROSS", period)
        deductions = val("INCOME.ENTERPRISE.REVENUE_DEDUCTIONS", period)
        net = val("INCOME.ENTERPRISE.REVENUE_NET", period)
        if gross is not None and deductions is not None and net is not None:
            emit("revenue_net", period, net, gross - abs(deductions))
        else:
            checks.append({"name": "revenue_net", "period": period, "status": "skipped_missing_operand"})

        cogs = val("INCOME.ENTERPRISE.COGS", period)
        gp = val("INCOME.ENTERPRISE.GROSS_PROFIT", period)
        if net is not None and cogs is not None and gp is not None:
            emit("gross_profit", period, gp, net - abs(cogs))
        else:
            checks.append({"name": "gross_profit", "period": period, "status": "skipped_missing_operand"})

        oi = val("INCOME.ENTERPRISE.OTHER_INCOME", period)
        oe = val("INCOME.ENTERPRISE.OTHER_EXPENSE", period)
        op = val("INCOME.ENTERPRISE.OTHER_PROFIT", period)
        if oi is not None and oe is not None and op is not None:
            emit("other_profit", period, op, oi - abs(oe))
        else:
            checks.append({"name": "other_profit", "period": period, "status": "skipped_missing_operand"})

        pbt = val("INCOME.ENTERPRISE.PROFIT_BEFORE_TAX", period)
        cur_tax = val("INCOME.ENTERPRISE.CURRENT_TAX_EXPENSE", period)
        def_tax = val("INCOME.ENTERPRISE.DEFERRED_TAX_EXPENSE", period)
        pat = val("INCOME.ENTERPRISE.PROFIT_AFTER_TAX", period)
        if pbt is not None and cur_tax is not None and pat is not None:
            dt = def_tax if def_tax is not None else 0
            expected = pbt - abs(cur_tax) - dt if dt >= 0 else pbt - abs(cur_tax) + abs(dt)
            emit("profit_after_tax", period, pat, expected)
        else:
            checks.append({"name": "profit_after_tax", "period": period, "status": "skipped_missing_operand"})

    return checks


def summarize_formula_checks(checks: list[dict]) -> dict:
    evaluated = [x for x in checks if x.get("status") in {"pass", "fail"}]
    passed = sum(x.get("status") == "pass" for x in evaluated)
    failed = sum(x.get("status") == "fail" for x in evaluated)
    return {
        "evaluated": len(evaluated),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(evaluated), 6) if evaluated else None,
    }


def validate_bank_formulas(by: dict) -> list[dict]:
    checks = []
    formulas = [
        ("net_interest", "INCOME.BANK.NET_INTEREST_INCOME", ["INCOME.BANK.INTEREST_INCOME", "INCOME.BANK.INTEREST_EXPENSE"]),
        ("net_service", "INCOME.BANK.NET_SERVICE_INCOME", ["INCOME.BANK.SERVICE_INCOME", "INCOME.BANK.SERVICE_EXPENSE"]),
        ("net_other", "INCOME.BANK.NET_OTHER_OPERATING", ["INCOME.BANK.OTHER_OPERATING_INCOME", "INCOME.BANK.OTHER_OPERATING_EXPENSE"]),
        ("profit_before_tax", "INCOME.BANK.PROFIT_BEFORE_TAX", ["INCOME.BANK.PRE_PROVISION_OPERATING_PROFIT", "INCOME.BANK.CREDIT_RISK_PROVISION_EXPENSE"]),
    ]
    for period in ("current", "previous"):
        for name, target, parts in formulas:
            tv = by.get(target, {}).get("value", {}).get(period)
            vals = [by.get(n, {}).get("value", {}).get(period) for n in parts]
            if tv is None or any(v is None for v in vals):
                checks.append({"name": name, "period": period, "status": "skipped_missing_operand"})
                continue
            expected = sum(vals)
            checks.append({
                "name": name, "period": period, "status": "pass" if tv == expected else "fail",
                "reported": tv, "expected": expected, "difference": tv - expected,
            })
    return checks
