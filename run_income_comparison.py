from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from income_observation_patch import extract_income_fallback, strip_md
from income_mapper import IncomeMapper, adapt_row, auto_sector
from cashflow_observation_patch import extract_cashflow_fallback, detect_method as detect_cf_method
from cashflow_mapper import CashFlowMapper, adapt_cashflow_row
from financial_position_bridge import FinancialPositionIndex, integrate_financial_position
from source_observation_layer import augment_from_rows
from source_statement_recovery import extract_generic_statement_rows, augment_canonical_with_recovered_rows

SCHEMA = ROOT / "resources" / "income_statement_schema.json"
ALIASES = ROOT / "resources" / "income_statement_aliases.json"
CF_SCHEMA = ROOT / "resources" / "cash_flow_schema.json"
CF_ALIASES = ROOT / "resources" / "cash_flow_aliases.json"


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def stem_base(path: Path) -> str:
    name = path.stem
    return re.sub(r"\((?:\d+|\d{8}-\d{6})\)$", "", name)


def select_md_files(input_path: Path):
    """Return one Markdown source per normalized base name.

    v8 behavior:
    - fail loudly when input does not exist;
    - accept a single .md file;
    - scan the requested folder first;
    - if no top-level .md exists, recursively scan subfolders;
    - never silently return an empty batch.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path.resolve()}")

    if input_path.is_file():
        if input_path.suffix.lower() != ".md":
            raise ValueError(f"Input file is not Markdown: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise ValueError(f"Input path is neither a file nor a directory: {input_path}")

    files = sorted(p for p in input_path.glob("*.md") if p.is_file())
    discovery_mode = "top_level"
    if not files:
        files = sorted(p for p in input_path.rglob("*.md") if p.is_file())
        discovery_mode = "recursive"

    if not files:
        raise FileNotFoundError(
            f"No Markdown files found under: {input_path.resolve()} "
            f"(checked top-level and recursively)"
        )

    groups = {}
    for p in files:
        base = stem_base(p)
        groups.setdefault(base, []).append(p)

    chosen = []
    for base, variants in groups.items():
        exact = [p for p in variants if p.stem == base]
        chosen.append(exact[0] if exact else sorted(variants, key=lambda x: (len(x.name), x.name))[0])

    chosen = sorted(chosen)
    print(
        f"[DISCOVERY] input={input_path.resolve()} mode={discovery_mode} "
        f"md_found={len(files)} selected={len(chosen)}"
    )
    return chosen


def find_existing_comparison(base: str, comparison_dir: Optional[Path], output_dir: Optional[Path] = None,
                             source_dir: Optional[Path] = None):
    """Find the best existing comparison and prefer one containing financial_position.

    This prevents reruns from selecting a previously generated income-only comparison
    when a legacy B02 comparison is also available.
    """
    target = f"{base}.comparison.json"
    candidates = []
    roots = []
    for root in (comparison_dir, source_dir, output_dir):
        if root and root not in roots:
            roots.append(root)

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        direct = root / target
        if direct.exists():
            candidates.append(direct)
        # One nested level is enough for common layouts such as output/legacy/*.comparison.json.
        candidates.extend(root.glob(f"*/{target}"))

    # Prefer a file that really contains financial_position.
    unique = []
    seen = set()
    for c in candidates:
        try:
            key = c.resolve()
        except Exception:
            key = c
        if key not in seen:
            seen.add(key)
            unique.append(c)

    for c in unique:
        obj = read_json(c, {})
        if isinstance(obj, dict) and isinstance(obj.get("financial_position"), dict):
            return c
    return unique[0] if unique else None


def _scope_text(text: str, scope: dict):
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


def run_income(md_path: Path, current_year=2025, previous_year=2024, forced_sector="auto"):
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    ext = extract_income_fallback(text, current_year, previous_year)
    raw_rows = ext["rows"]
    rows = []
    for i, r in enumerate(raw_rows):
        try:
            rows.append(adapt_row(r, i, current_year=current_year, previous_year=previous_year))
        except Exception:
            continue

    scoped = _scope_text(text, ext)
    if forced_sector in {"bank", "enterprise", "securities", "insurance"}:
        sector, sector_method = forced_sector, "forced"
    else:
        sector, sector_method = detect_sector_from_scope(scoped, rows)

    # Do not manufacture an all-null canonical when structural extraction found no rows.
    # Return a diagnostic-only comparison result instead. This prevents confusing
    # `*.income.canonical.json` files that exist but contain no observations.
    if not rows:
        metrics = {
            "status": "no_structural_rows",
            "value_nodes": 0, "current_value_nodes": 0, "previous_value_nodes": 0,
            "mapping": {
                "input_rows": 0, "mapped_rows": 0, "unmapped_rows": 0, "mapping_rate": 0.0,
                "canonical_value_nodes": 0, "current_value_nodes": 0, "previous_value_nodes": 0,
                "current_coverage": 0.0, "previous_coverage": 0.0,
            },
            "parser": {
                "statement_profile": "income_statement", "sector": sector, "sector_method": sector_method,
                "scope_start": ext["scope_start_line"], "scope_end": ext["scope_end_line"],
                "scope_score": ext["scope_score"], "collector_policy": "income_multi_layout_v8",
                "patterns": [],
            },
            "quality": {
                "canonical_status": "no_structural_rows", "formula_evaluated": 0,
                "formula_passed": 0, "formula_failed": 0, "formula_pass_rate": None,
                "sign_normalizations": 0,
            },
            "unmapped_examples": [],
        }
        return {"canonical": None, "metrics": metrics, "rows": rows, "scope": ext, "sector": sector}

    if sector not in {"bank", "enterprise", "securities", "insurance"}:
        metrics = {
            "status": "unknown_sector",
            "value_nodes": 0, "current_value_nodes": 0, "previous_value_nodes": 0,
            "mapping": {"input_rows": len(rows), "mapped_rows": 0, "unmapped_rows": len(rows), "mapping_rate": 0.0},
            "parser": {
                "statement_profile": "income_statement", "sector": "unknown", "sector_method": sector_method,
                "scope_start": ext["scope_start_line"], "scope_end": ext["scope_end_line"], "scope_score": ext["scope_score"],
                "collector_policy": "income_multi_layout_v8",
            },
            "unmapped_examples": [{"label": r.label, "current": r.current, "previous": r.previous, "code": r.code} for r in rows[:40]],
        }
        return {"canonical": None, "metrics": metrics, "rows": rows, "scope": ext, "sector": "unknown"}

    mapper = IncomeMapper(schema_path=SCHEMA, aliases_path=ALIASES, sector=sector, regex_fallback=True,
                          regex_min_score=0.93, regex_gap=0.08)
    mapped = mapper.map_rows(rows)
    canonical = mapper.canonical(mapped, source_name=md_path.name, current_year=current_year, previous_year=previous_year)
    canonical = augment_from_rows(canonical, mapped, "INCOME")
    # v13: source-scope recovery is additive only. It preserves rows that the semantic extractor
    # did not materialize, without changing mapping decisions for already-populated semantic nodes.
    if ext.get("scope_start_line") and ext.get("scope_end_line"):
        recovered_rows = extract_generic_statement_rows(
            text, ext["scope_start_line"], ext["scope_end_line"], current_year, previous_year, "INCOME")
        canonical = augment_canonical_with_recovered_rows(canonical, recovered_rows, "INCOME")
    metrics = build_metrics(canonical, mapped, ext, sector, sector_method)
    sr = (canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}
    (metrics.get("parser") or {}).update({
        "source_recovery": "v13", "source_recovered_rows": sr.get("rows_recovered", 0),
        "source_recovery_added_nodes": sr.get("added_nodes", 0),
        "source_recovery_filled_nodes": sr.get("filled_existing_nodes", 0),
        "source_recovery_conflicts": sr.get("conflicts", 0),
    })
    return {"canonical": canonical, "metrics": metrics, "rows": mapped, "scope": ext, "sector": sector}



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
            "scope_score": ext.get("scope_score"), "collector_policy": "cashflow_multi_layout_v4_source_recovery",
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


def run_cashflow(md_path: Path, current_year=2025, previous_year=2024):
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    ext = extract_cashflow_fallback(text, current_year, previous_year)
    rows = []
    for raw in ext.get("rows", []):
        try:
            rows.append(adapt_cashflow_row(raw))
        except Exception:
            continue
    sector = ext.get("sector") or "unknown"
    method = ext.get("method") or "unknown"
    sector_method = ext.get("sector_method") or "unknown"
    method_method = ext.get("method_method") or "unknown"
    if method == "unknown" and rows:
        labels_text = "\n".join(r.label for r in rows if getattr(r, "label", None))
        recovered_method, recovered_method_method = detect_cf_method(labels_text)
        if recovered_method in {"direct", "indirect"}:
            method, method_method = recovered_method, "rows_" + recovered_method_method
            for r in rows:
                r.method = method
    if not rows:
        metrics = build_cashflow_metrics(None, rows, ext, sector, sector_method, method, method_method)
        return {"canonical": None, "metrics": metrics, "rows": rows, "scope": ext, "sector": sector, "method": method}
    # v1 intentionally supports only statutory profiles researched from TT200 and B04/TCTD.
    # Securities/insurance are detected, not force-routed into a wrong schema.
    if sector not in {"enterprise", "bank", "securities"} or method not in {"direct", "indirect"}:
        metrics = build_cashflow_metrics(None, rows, ext, sector, sector_method, method, method_method)
        return {"canonical": None, "metrics": metrics, "rows": rows, "scope": ext, "sector": sector, "method": method}
    mapper = CashFlowMapper(CF_SCHEMA, CF_ALIASES, sector=sector, method=method)
    mapped = mapper.map_rows(rows)
    canonical = mapper.canonical(mapped, md_path.name, current_year, previous_year)
    canonical = augment_from_rows(canonical, mapped, "CASHFLOW")
    # v13: raw source recovery covers mixed inline-year/date layouts (e.g. current value followed
    # by `(Năm 2024: ...)`, or `(31.12.2025); (31.12.2024)`) that can hydrate only one period in v12.
    if ext.get("scope_start_line") and ext.get("scope_end_line"):
        recovered_rows = extract_generic_statement_rows(
            text, ext["scope_start_line"], ext["scope_end_line"], current_year, previous_year, "CASHFLOW")
        canonical = augment_canonical_with_recovered_rows(canonical, recovered_rows, "CASHFLOW")
    metrics = build_cashflow_metrics(canonical, mapped, ext, sector, sector_method, method, method_method)
    sr = (canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}
    (metrics.get("parser") or {}).update({
        "source_recovery": "v13", "source_recovered_rows": sr.get("rows_recovered", 0),
        "source_recovery_added_nodes": sr.get("added_nodes", 0),
        "source_recovery_filled_nodes": sr.get("filled_existing_nodes", 0),
        "source_recovery_conflicts": sr.get("conflicts", 0),
    })
    return {"canonical": canonical, "metrics": metrics, "rows": mapped, "scope": ext, "sector": sector, "method": method}


def process_one(md_path: Path, output_dir: Path, comparison_dir: Optional[Path], current_year: int, previous_year: int, sector: str, fp_index: FinancialPositionIndex):
    base = stem_base(md_path)
    inc = run_income(md_path, current_year, previous_year, sector)
    cf = run_cashflow(md_path, current_year, previous_year)
    output_dir.mkdir(parents=True, exist_ok=True)

    income_path = output_dir / f"{base}.income.canonical.json"
    if inc["canonical"] is not None:
        write_json(income_path, inc["canonical"])
    elif income_path.exists():
        income_path.unlink()

    cashflow_path = output_dir / f"{base}.cashflow.canonical.json"
    if cf["canonical"] is not None:
        write_json(cashflow_path, cf["canonical"])
    elif cashflow_path.exists():
        cashflow_path.unlink()

    existing_path = find_existing_comparison(base, comparison_dir, output_dir, md_path.parent)
    existing = read_json(existing_path, {}) if existing_path else {}
    if not isinstance(existing, dict):
        existing = {}

    # Integrate the completed Financial Position pipeline/output before writing the unified comparison.
    source_text = md_path.read_text(encoding="utf-8", errors="ignore")
    fp = integrate_financial_position(
        base, output_dir, fp_index, existing, source_text=source_text,
        current_year=current_year, previous_year=previous_year)

    merged = deepcopy(existing)
    merged.setdefault("source_name", md_path.name)
    merged.setdefault("mapping_strategy", "legacy")
    merged["financial_position"] = {
        "v05": fp["metrics"],
        "canonical_file": fp["canonical_file"],
    }
    merged["income_statement"] = {
        "v05": inc["metrics"],
        "canonical_file": income_path.name if inc["canonical"] is not None else None,
    }
    merged["cash_flow_statement"] = {
        "v01": cf["metrics"],
        "canonical_file": cashflow_path.name if cf["canonical"] is not None else None,
    }
    merged_path = output_dir / f"{base}.comparison.json"
    write_json(merged_path, merged)

    im = inc["metrics"]; imp = im.get("mapping", {})
    cm = cf["metrics"]; cmp = cm.get("mapping", {})
    return {
        "source_name": md_path.name,
        "sector": inc["sector"], "status": im.get("status"),
        "scope_start": (im.get("parser") or {}).get("scope_start"), "scope_end": (im.get("parser") or {}).get("scope_end"),
        "scope_score": (im.get("parser") or {}).get("scope_score"), "sector_method": (im.get("parser") or {}).get("sector_method"),
        "patterns": ";".join((im.get("parser") or {}).get("patterns", [])),
        "input_rows": imp.get("input_rows", 0), "mapped_rows": imp.get("mapped_rows", 0), "unmapped_rows": imp.get("unmapped_rows", 0),
        "mapping_rate": imp.get("mapping_rate", 0.0), "income_value_nodes": im.get("value_nodes", 0),
        "income_current_nodes": im.get("current_value_nodes", 0), "income_previous_nodes": im.get("previous_value_nodes", 0),
        "current_coverage": imp.get("current_coverage", 0.0), "previous_coverage": imp.get("previous_coverage", 0.0),
        "formula_evaluated": (im.get("quality") or {}).get("formula_evaluated", 0),
        "formula_passed": (im.get("quality") or {}).get("formula_passed", 0),
        "formula_failed": (im.get("quality") or {}).get("formula_failed", 0),
        "formula_pass_rate": (im.get("quality") or {}).get("formula_pass_rate"),
        "sign_normalizations": (im.get("quality") or {}).get("sign_normalizations", 0),
        "cashflow_sector": cf["sector"], "cashflow_method": cf["method"], "cashflow_status": cm.get("status"),
        "cashflow_scope_start": (cm.get("parser") or {}).get("scope_start"), "cashflow_scope_end": (cm.get("parser") or {}).get("scope_end"),
        "cashflow_scope_score": (cm.get("parser") or {}).get("scope_score"),
        "cashflow_patterns": ";".join((cm.get("parser") or {}).get("patterns", [])),
        "cashflow_input_rows": cmp.get("input_rows", 0), "cashflow_mapped_rows": cmp.get("mapped_rows", 0),
        "cashflow_unmapped_rows": cmp.get("unmapped_rows", 0), "cashflow_mapping_rate": cmp.get("mapping_rate", 0.0),
        "cashflow_value_nodes": cm.get("value_nodes", 0), "cashflow_current_nodes": cm.get("current_value_nodes", 0),
        "cashflow_previous_nodes": cm.get("previous_value_nodes", 0),
        "cashflow_formula_evaluated": (cm.get("quality") or {}).get("formula_evaluated", 0),
        "cashflow_formula_passed": (cm.get("quality") or {}).get("formula_passed", 0),
        "cashflow_formula_failed": (cm.get("quality") or {}).get("formula_failed", 0),
        "cashflow_formula_pass_rate": (cm.get("quality") or {}).get("formula_pass_rate"),
        "financial_position_status": fp["metrics"].get("status"),
        "financial_position_value_nodes": fp["metrics"].get("value_nodes", 0),
        "financial_position_current_nodes": fp["metrics"].get("current_value_nodes", 0),
        "financial_position_previous_nodes": fp["metrics"].get("previous_value_nodes", 0),
        "financial_position_recovered_rows": (fp["metrics"].get("parser") or {}).get("recovered_rows", 0),
        "income_source_recovered_rows": (im.get("parser") or {}).get("source_recovered_rows", 0),
        "cashflow_source_recovered_rows": (cm.get("parser") or {}).get("source_recovered_rows", 0),
        "cashflow_source_recovery_filled_nodes": (cm.get("parser") or {}).get("source_recovery_filled_nodes", 0),
        "financial_position_canonical_file": fp["canonical_file"],
        "financial_position_preserved": fp["canonical"] is not None or fp.get("preserved_legacy", False),
        "income_statement_preserved_or_written": "income_statement" in merged,
        "comparison_file": merged_path.name,
        "canonical_file": income_path.name if inc["canonical"] is not None else None,
        "cashflow_canonical_file": cashflow_path.name if cf["canonical"] is not None else None,
    }


def main():
    ap = argparse.ArgumentParser(description="Integrated 3-statement mapper: Financial Position + Income + Cash Flow.")
    ap.add_argument("input", help="Markdown file or folder")
    ap.add_argument("--comparison-dir", help="Folder containing existing *.comparison.json")
    ap.add_argument("--financial-position-dir", help="Folder containing completed <base>.canonical.json Financial Position outputs. If omitted, nearby workspace folders are auto-scanned.")
    ap.add_argument("--output", default="comparison_v9")
    ap.add_argument("--current-year", type=int, default=2025)
    ap.add_argument("--previous-year", type=int, default=2024)
    ap.add_argument("--sector", choices=["auto", "bank", "enterprise", "securities", "insurance"], default="auto",
                    help="Income override only; Cash Flow sector is independently detected from its own scope.")
    args = ap.parse_args()

    input_path = Path(args.input)
    comparison_dir = Path(args.comparison_dir) if args.comparison_dir else None
    output_dir = Path(args.output)
    try:
        md_files = select_md_files(input_path)
    except Exception as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        raise SystemExit(2)

    # Build one reusable index instead of recursively searching for every file.
    fp_roots = []
    if args.financial_position_dir:
        fp_roots.append(Path(args.financial_position_dir))
    # Auto-discovery keeps the one-command workflow compatible with the completed older B02 pipeline.
    for root in (input_path if input_path.is_dir() else input_path.parent,
                 input_path.parent if input_path.is_dir() else input_path.parent.parent,
                 comparison_dir,
                 comparison_dir.parent if comparison_dir else None,
                 output_dir.parent):
        if root is not None:
            fp_roots.append(Path(root))
    fp_index = FinancialPositionIndex.build(fp_roots)
    print(f"[FINANCIAL_POSITION] canonical_sources={len(fp_index.by_base)} scanned={fp_index.scanned_files}")

    rows = []
    for p in md_files:
        try:
            r = process_one(p, output_dir, comparison_dir, args.current_year, args.previous_year, args.sector, fp_index)
            rows.append(r)
            print(
                f"[OK] {p.name}: fp={r['financial_position_status']} nodes={r['financial_position_value_nodes']} "
                f"| income={r['status']} {r['mapped_rows']}/{r['input_rows']} "
                f"| cashflow={r['cashflow_status']} {r['cashflow_mapped_rows']}/{r['cashflow_input_rows']} "
                f"sector={r['cashflow_sector']} method={r['cashflow_method']}"
            )
        except Exception as e:
            rows.append({"source_name": p.name, "status": "error", "cashflow_status": "error", "error": repr(e)})
            print(f"[ERROR] {p.name}: {e}", file=sys.stderr)

    if not rows:
        print("[FATAL] Internal invariant failed: discovered Markdown files but produced zero summary rows.", file=sys.stderr)
        raise SystemExit(3)

    write_json(output_dir / "comparison_summary.json", rows)
    cols = [
        "source_name","sector","status","scope_start","scope_end","scope_score","sector_method","patterns",
        "input_rows","mapped_rows","unmapped_rows","mapping_rate","income_value_nodes","income_current_nodes",
        "income_previous_nodes","current_coverage","previous_coverage","formula_evaluated","formula_passed",
        "formula_failed","formula_pass_rate","sign_normalizations",
        "cashflow_sector","cashflow_method","cashflow_status","cashflow_scope_start","cashflow_scope_end","cashflow_scope_score",
        "cashflow_patterns","cashflow_input_rows","cashflow_mapped_rows","cashflow_unmapped_rows","cashflow_mapping_rate",
        "cashflow_value_nodes","cashflow_current_nodes","cashflow_previous_nodes","cashflow_formula_evaluated",
        "cashflow_formula_passed","cashflow_formula_failed","cashflow_formula_pass_rate",
        "financial_position_status","financial_position_value_nodes","financial_position_current_nodes",
        "financial_position_previous_nodes","financial_position_recovered_rows",
        "income_source_recovered_rows","cashflow_source_recovered_rows","cashflow_source_recovery_filled_nodes",
        "financial_position_canonical_file","financial_position_preserved",
        "income_statement_preserved_or_written","comparison_file","canonical_file","cashflow_canonical_file","error"
    ]
    with (output_dir / "comparison_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nSummary: {output_dir / 'comparison_summary.csv'}")


if __name__ == "__main__":
    main()
