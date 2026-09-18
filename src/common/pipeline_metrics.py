from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "resources" / "schemas" / "income_statement_schema.json"
ALIASES = ROOT / "resources" / "income_statement_aliases.json"

try:
    from src.b02_income import auto_sector
except ImportError:
    from b02_income import auto_sector

try:
    from src.common.error_taxonomy import build_error_taxonomy
except ImportError:
    try:
        from .error_taxonomy import build_error_taxonomy
    except ImportError:
        from error_taxonomy import build_error_taxonomy


def _scope_text(text: str, scope: dict) -> str:
    lines = text.splitlines()
    s = max(0, int(scope.get("scope_start_line") or 1) - 1)
    e = min(len(lines), int(scope.get("scope_end_line") or len(lines)))
    return "\n".join(lines[s:e])


def detect_sector_from_scope(scope_text: str, rows, schema_path=SCHEMA, aliases_path=ALIASES):
    low = scope_text.casefold()

    # Mã biểu mẫu theo quy định được ưu tiên hơn suy đoán semantic.
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

    # Fallback cuối: chấm điểm dòng đã chuẩn hóa với từng catalog.
    sec = auto_sector(rows, schema_path, aliases_path)
    return sec, "row_catalog"


def _is_source_observation_node(node: dict) -> bool:
    """Nhận diện node evidence nguồn bổ sung mà không dựa vào tên báo cáo.

    Observation nguồn được cố ý giữ trong output canonical để truy vết. Tuy
    nhiên, chúng không phải dòng semantic độc lập nên không được làm tăng mẫu
    số của coverage kỳ hay độ đầy đủ nguồn.
    """

    return (
        str(node.get("kind") or "").casefold() == "source_observation"
        or str(node.get("node_id") or "").startswith("SOURCE.")
    )


def _value_nodes(nodes: list[dict]) -> tuple[list[dict], list[dict]]:
    valued = [
        n for n in nodes
        if (n.get("value") or {}).get("current") is not None
        or (n.get("value") or {}).get("previous") is not None
    ]
    coverage = [n for n in valued if not _is_source_observation_node(n)]
    return valued, coverage


def build_metrics(canonical: dict, rows, scope: dict, sector: str, sector_method: str):
    nodes = canonical.get("nodes", [])
    valued, coverage_valued = _value_nodes(nodes)
    cur = [n for n in nodes if (n.get("value") or {}).get("current") is not None]
    prev = [n for n in nodes if (n.get("value") or {}).get("previous") is not None]
    coverage_cur = [n for n in coverage_valued if (n.get("value") or {}).get("current") is not None]
    coverage_prev = [n for n in coverage_valued if (n.get("value") or {}).get("previous") is not None]
    mapped = [r for r in rows if getattr(r, "mapping_status", None) == "mapped"]
    unmapped = [r for r in rows if getattr(r, "mapping_status", None) != "mapped"]
    rate = len(mapped) / len(rows) if rows else 0.0
    valued_n = len(valued)
    coverage_n = len(coverage_valued)
    prev_cov = len(coverage_prev) / coverage_n if coverage_n else 0.0
    cur_cov = len(coverage_cur) / coverage_n if coverage_n else 0.0

    canonical_status = canonical.get("status") or "ok"
    if not rows:
        status = "no_structural_rows"
    elif coverage_n == 0:
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
    error_taxonomy = build_error_taxonomy("income_statement", unmapped)

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
            "coverage_value_nodes": coverage_n,
            "source_observation_nodes": valued_n - coverage_n,
            "current_value_nodes": len(cur),
            "previous_value_nodes": len(prev),
            "coverage_current_value_nodes": len(coverage_cur),
            "coverage_previous_value_nodes": len(coverage_prev),
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
        "error_taxonomy": error_taxonomy,
        "unmapped_examples": error_taxonomy["examples"],
    }


def build_cashflow_metrics(canonical: dict, rows, ext: dict, sector: str, sector_method: str, method: str, method_method: str):
    nodes = canonical.get("nodes", []) if canonical else []
    valued, coverage_valued = _value_nodes(nodes)
    cur = [n for n in valued if (n.get("value") or {}).get("current") is not None]
    prev = [n for n in valued if (n.get("value") or {}).get("previous") is not None]
    coverage_cur = [n for n in coverage_valued if (n.get("value") or {}).get("current") is not None]
    coverage_prev = [n for n in coverage_valued if (n.get("value") or {}).get("previous") is not None]
    mapped = [r for r in rows if getattr(r, "mapping_status", None) == "mapped"]
    unmapped = [r for r in rows if getattr(r, "mapping_status", None) != "mapped"]
    rate = len(mapped) / len(rows) if rows else 0.0
    diagnostics = (canonical or {}).get("diagnostics") or {}
    fs = diagnostics.get("formula_summary") or {}
    canonical_status = (canonical or {}).get("status") or "ok"
    error_taxonomy = build_error_taxonomy("cash_flow_statement", unmapped)
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

    # Gate coverage nguồn: 100% của một mảnh rất ngắn không phải báo cáo lưu
    # chuyển tiền tệ đầy đủ.
    # Dùng anchor semantic cốt lõi thay vì bắt buộc mã biểu mẫu/thuyết minh vì
    # Markdown do LLM tạo có thể thiếu cả hai.
    valued_ids = {n.get("node_id") for n in coverage_valued}
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
    if canonical and status == "ok" and (len(coverage_valued) < min_nodes or (core_total and core_hits < 2)):
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
            "coverage_value_nodes": len(coverage_valued),
            "source_observation_nodes": len(valued) - len(coverage_valued),
            "current_value_nodes": len(cur), "previous_value_nodes": len(prev),
            "coverage_current_value_nodes": len(coverage_cur),
            "coverage_previous_value_nodes": len(coverage_prev),
            "current_coverage": round(len(coverage_cur)/len(coverage_valued), 6) if coverage_valued else 0.0,
            "previous_coverage": round(len(coverage_prev)/len(coverage_valued), 6) if coverage_valued else 0.0,
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
        "error_taxonomy": error_taxonomy,
        "unmapped_examples": error_taxonomy["examples"],
    }
