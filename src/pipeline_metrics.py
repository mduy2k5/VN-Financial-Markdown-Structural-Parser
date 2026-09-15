from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "resources" / "income_statement_schema.json"
ALIASES = ROOT / "resources" / "income_statement_aliases.json"

try:
    from .income_mapper import auto_sector
except ImportError:
    from income_mapper import auto_sector


def _scope_text(text: str, scope: dict) -> str:
    lines = text.splitlines()
    s = max(0, int(scope.get("scope_start_line") or 1) - 1)
    e = min(len(lines), int(scope.get("scope_end_line") or len(lines)))
    return "\n".join(lines[s:e])


def detect_sector_from_scope(scope_text: str, rows, schema_path=SCHEMA, aliases_path=ALIASES):
    low = scope_text.casefold()

    # Explicit statutory form beats semantic guessing.
    if re.search(r"(?i)B\s*0?2\s*[-–]?\s*CTCK", scope_text) or "công ty chứng khoán" in low or "cong ty chung khoan" in low:
        return "securities", "form_or_text"
    insurance_hints = [
        "doanh thu phí bảo hiểm", "phí bảo hiểm gốc", "nhượng tái bảo hiểm",
        "dự phòng nghiệp vụ bảo hiểm", "bồi thường bảo hiểm", "hoạt động bảo hiểm",
    ]
    if sum(1 for x in insurance_hints if x in low) >= 2:
        return "insurance", "text_anchors"
    if re.search(r"(?i)B\s*0?3a?\s*/\s*TCTD(?:-HN)?", scope_text):
        return "bank", "form_code"
    if re.search(r"(?i)B\s*0?2\s*[-–]?\s*DN(?:/HN)?", scope_text):
        return "enterprise", "form_code"

    bank_anchors = [
        "thu nhập lãi và các khoản thu nhập tương tự",
        "chi phí lãi và các chi phí tương tự",
        "thu nhập lãi thuần",
        "dự phòng rủi ro tín dụng",
        "mua bán chứng khoán đầu tư",
    ]
    enterprise_anchors = [
        "doanh thu bán hàng và cung cấp dịch vụ",
        "giá vốn hàng bán",
        "chi phí bán hàng",
        "chi phí quản lý doanh nghiệp",
        "lợi nhuận gộp",
    ]
    bs = sum(1 for x in bank_anchors if x in low)
    es = sum(1 for x in enterprise_anchors if x in low)
    if bs >= 2 and bs > es:
        return "bank", "semantic_anchors"
    if es >= 2 and es > bs:
        return "enterprise", "semantic_anchors"

    # Last fallback: score normalized rows against each catalog.
    sec = auto_sector(rows, schema_path, aliases_path)
    return sec, "row_catalog"


def build_metrics(canonical: dict, rows, scope: dict, sector: str, sector_method: str):
    nodes = canonical.get("nodes", [])
    valued = [n for n in nodes if (n.get("value") or {}).get("current") is not None or (n.get("value") or {}).get("previous") is not None]
    cur = [n for n in nodes if (n.get("value") or {}).get("current") is not None]
    prev = [n for n in nodes if (n.get("value") or {}).get("previous") is not None]
    mapped = [r for r in rows if getattr(r, "mapping_status", None) == "mapped"]
    unmapped = [r for r in rows if getattr(r, "mapping_status", None) != "mapped"]
    rate = len(mapped) / len(rows) if rows else 0.0
    valued_n = len(valued)
    prev_cov = len(prev) / valued_n if valued_n else 0.0
    cur_cov = len(cur) / valued_n if valued_n else 0.0

    canonical_status = canonical.get("status") or "ok"
    if not rows:
        status = "no_structural_rows"
    elif valued_n == 0:
        status = "no_income_values"
    elif rate < 0.8:
        status = "partial_mapping"
    elif min(cur_cov, prev_cov) < 0.75:
        status = "partial_periods"
    elif rate < 0.95:
        status = "partial_mapping"
    elif canonical_status != "ok":
        status = canonical_status
    else:
        status = "ok"

    diagnostics = canonical.get("diagnostics") or {}
    formula_summary = diagnostics.get("formula_summary") or {}
    sign_normalizations = diagnostics.get("sign_normalizations") or []

    return {
        "status": status,
        "value_nodes": valued_n,
        "current_value_nodes": len(cur),
        "previous_value_nodes": len(prev),
        "mapping": {
            "input_rows": len(rows),
            "mapped_rows": len(mapped),
            "unmapped_rows": len(unmapped),
            "mapping_rate": round(rate, 6) if rows else 0.0,
            "canonical_value_nodes": valued_n,
            "current_value_nodes": len(cur),
            "previous_value_nodes": len(prev),
            "current_coverage": round(cur_cov, 6) if valued_n else 0.0,
            "previous_coverage": round(prev_cov, 6) if valued_n else 0.0,
            "accepted_occurrences": valued_n,
        },
        "parser": {
            "statement_profile": "income_statement",
            "sector": sector,
            "sector_method": sector_method,
            "scope_start": scope.get("scope_start_line"),
            "scope_end": scope.get("scope_end_line"),
            "scope_score": scope.get("scope_score"),
            "collector_policy": "income_multi_layout_v8",
            "patterns": sorted({getattr(r, "pattern", None) for r in rows if getattr(r, "pattern", None)}),
        },
        "quality": {
            "canonical_status": canonical_status,
            "formula_evaluated": formula_summary.get("evaluated", 0),
            "formula_passed": formula_summary.get("passed", 0),
            "formula_failed": formula_summary.get("failed", 0),
            "formula_pass_rate": formula_summary.get("pass_rate"),
            "sign_normalizations": len(sign_normalizations),
        },
        "unmapped_examples": [
            {"label": r.label, "current": r.current, "previous": r.previous, "code": r.code, "note": r.note, "pattern": r.pattern}
            for r in unmapped[:40]
        ],
    }


def build_cashflow_metrics(canonical: dict, rows, ext: dict, sector: str, sector_method: str, method: str, method_method: str):
    nodes = canonical.get("nodes", []) if canonical else []
    valued = [n for n in nodes if (n.get("value") or {}).get("current") is not None or (n.get("value") or {}).get("previous") is not None]
    cur = [n for n in valued if (n.get("value") or {}).get("current") is not None]
    prev = [n for n in valued if (n.get("value") or {}).get("previous") is not None]
    mapped = [r for r in rows if getattr(r, "mapping_status", None) == "mapped"]
    unmapped = [r for r in rows if getattr(r, "mapping_status", None) != "mapped"]
    rate = len(mapped) / len(rows) if rows else 0.0
    diagnostics = (canonical or {}).get("diagnostics") or {}
    fs = diagnostics.get("formula_summary") or {}
    canonical_status = (canonical or {}).get("status") or "ok"
    if not rows:
        status = "no_structural_rows"
    elif not canonical:
        status = "schema_sector_gap:" + sector if sector in {"securities", "insurance"} else "unknown_sector"
    elif len(valued) == 0:
        status = "no_cashflow_values"
    elif rate < 0.95:
        status = "partial_mapping"
    elif canonical_status != "ok":
        status = canonical_status
    else:
        status = "ok"

    # Source-coverage gate: 100% of a tiny fragment is not a complete cash-flow statement.
    # Use semantic core anchors rather than requiring form codes/notes, because LLM Markdown can omit both.
    valued_ids = {n.get("node_id") for n in valued}
    if sector == "enterprise":
        core = {
            "CASHFLOW.ENTERPRISE.OPERATING.NET_CASH",
            "CASHFLOW.ENTERPRISE.INVESTING.NET_CASH",
            "CASHFLOW.ENTERPRISE.FINANCING.NET_CASH",
            "CASHFLOW.ENTERPRISE.NET_CHANGE_IN_CASH",
            "CASHFLOW.ENTERPRISE.CASH_BEGINNING",
            "CASHFLOW.ENTERPRISE.CASH_ENDING",
        }
        min_nodes = 10
    elif sector == "bank":
        core = {
            "CASHFLOW.BANK.OPERATING.NET_CASH",
            "CASHFLOW.BANK.INVESTING.NET_CASH",
            "CASHFLOW.BANK.FINANCING.NET_CASH",
            "CASHFLOW.BANK.NET_CHANGE_IN_CASH",
            "CASHFLOW.BANK.CASH_BEGINNING",
            "CASHFLOW.BANK.CASH_ENDING",
        }
        min_nodes = 10
    elif sector == "securities":
        core = {
            "CASHFLOW.SECURITIES.INDIRECT.NET_OPERATING_CASH",
            "CASHFLOW.SECURITIES.INDIRECT.NET_INVESTING_CASH",
            "CASHFLOW.SECURITIES.INDIRECT.NET_FINANCING_CASH",
            "CASHFLOW.SECURITIES.INDIRECT.NET_CHANGE_IN_CASH",
            "CASHFLOW.SECURITIES.INDIRECT.CASH_BEGINNING",
        }
        min_nodes = 12
    else:
        core, min_nodes = set(), 0
    core_hits = len(core & valued_ids)
    core_total = len(core)
    if canonical and status == "ok" and (len(valued) < min_nodes or (core_total and core_hits < 2)):
        status = "partial_source_coverage"
    return {
        "status": status,
        "value_nodes": len(valued),
        "current_value_nodes": len(cur),
        "previous_value_nodes": len(prev),
        "mapping": {
            "input_rows": len(rows), "mapped_rows": len(mapped), "unmapped_rows": len(unmapped),
            "mapping_rate": round(rate, 6) if rows else 0.0,
            "canonical_value_nodes": len(valued),
            "current_value_nodes": len(cur), "previous_value_nodes": len(prev),
            "current_coverage": round(len(cur)/len(valued), 6) if valued else 0.0,
            "previous_coverage": round(len(prev)/len(valued), 6) if valued else 0.0,
        },
        "parser": {
            "statement_profile": "cash_flow_statement", "sector": sector, "sector_method": sector_method,
            "method": method, "method_method": method_method,
            "scope_start": ext.get("scope_start_line"), "scope_end": ext.get("scope_end_line"),
            "scope_score": ext.get("scope_score"), "collector_policy": "cashflow_multi_layout_v7_structural_identity_repair",
            "patterns": sorted({getattr(r, "pattern", None) for r in rows if getattr(r, "pattern", None)}),
        },
        "quality": {
            "canonical_status": canonical_status if canonical else status,
            "formula_evaluated": fs.get("evaluated", 0), "formula_passed": fs.get("passed", 0),
            "formula_failed": fs.get("failed", 0), "formula_pass_rate": fs.get("pass_rate"),
            "core_anchor_hits": core_hits, "core_anchor_total": core_total,
            "core_anchor_ratio": round(core_hits/core_total, 6) if core_total else None,
        },
        "unmapped_examples": [
            {"label": r.label, "section": r.section, "current": r.current, "previous": r.previous,
             "code": r.code, "note": r.note, "pattern": r.pattern}
            for r in unmapped[:40]
        ],
    }
