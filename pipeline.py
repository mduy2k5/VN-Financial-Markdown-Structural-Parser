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
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.b01_financial_position import FinancialPositionIndex, integrate_financial_position
from src.b02_income import extract_income_fallback, strip_md, IncomeMapper, adapt_row, auto_sector
from src.b03_cashflow import extract_cashflow_fallback, detect_method as detect_cf_method, CashFlowMapper, adapt_cashflow_row
from src.common import (
    augment_from_rows,
    extract_generic_statement_rows,
    augment_canonical_with_recovered_rows,
    extract_code_period_table,
    hydrate_canonical_by_form_code,
    reconcile_source_observations,
    detect_document_unit,
    fold_text,
)
from pipeline_metrics import (
    _scope_text,
    detect_sector_from_scope,
    build_metrics,
    build_cashflow_metrics,
)

try:
    from src.notes.pipeline import NotesPipeline
except ImportError:
    from notes.pipeline import NotesPipeline
try:
    from src.notes.row_exporter import export_note_rows
except ImportError:
    from notes.row_exporter import export_note_rows



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



def run_income(md_path: Path, current_year=2025, previous_year=2024, forced_sector="auto", fallback_unit: Optional[str] = None):
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    ext = extract_income_fallback(text, current_year, previous_year, fallback_unit=fallback_unit)
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
    # `SP_INCOME_CODE_LED_MIXED` is a recovery-oriented pattern.  On a layout
    # that was already captured by a stronger structural pattern it can cross a
    # neighbouring bullet boundary and contribute a contradictory duplicate.
    # Keep it when it is the only evidence for a semantic node; otherwise the
    # complete non-recovery observation is the authoritative parser result.
    complete_primary_nodes = {
        row.node_id
        for row in mapped
        if row.mapping_status == "mapped"
        and row.node_id
        and row.pattern != "SP_INCOME_CODE_LED_MIXED"
        and row.current is not None
        and row.previous is not None
    }
    mapped = [
        row for row in mapped
        if not (
            row.pattern == "SP_INCOME_CODE_LED_MIXED"
            and row.mapping_status == "mapped"
            and row.node_id in complete_primary_nodes
        )
    ]
    stmt_unit = ext.get("unit") or fallback_unit
    if stmt_unit == "unknown":
        stmt_unit = None
    canonical = mapper.canonical(mapped, source_name=md_path.name, current_year=current_year, previous_year=previous_year, statement_unit=stmt_unit)
    canonical = augment_from_rows(canonical, mapped, "INCOME")
    # v13: source-scope recovery is additive only. It preserves rows that the semantic extractor
    # did not materialize, without changing mapping decisions for already-populated semantic nodes.
    if ext.get("scope_start_line") and ext.get("scope_end_line"):
        recovered_rows = extract_generic_statement_rows(
            text, ext["scope_start_line"], ext["scope_end_line"], current_year, previous_year, "INCOME")
        canonical = augment_canonical_with_recovered_rows(canonical, recovered_rows, "INCOME")
        canonical = reconcile_source_observations(canonical, "INCOME")
    metrics = build_metrics(canonical, mapped, ext, sector, sector_method)
    sr = (canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}
    (metrics.get("parser") or {}).update({
        "source_recovery": "v16", "source_recovered_rows": sr.get("rows_recovered", 0),
        "source_recovery_added_nodes": sr.get("added_nodes", 0),
        "source_recovery_filled_nodes": sr.get("filled_existing_nodes", 0),
        "source_recovery_conflicts": sr.get("conflicts", 0),
    })
    return {"canonical": canonical, "metrics": metrics, "rows": mapped, "scope": ext, "sector": sector}




def run_cashflow(md_path: Path, current_year=2025, previous_year=2024, fallback_unit: Optional[str] = None):
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    ext = extract_cashflow_fallback(text, current_year, previous_year, fallback_unit=fallback_unit)
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
    stmt_unit = ext.get("unit") or fallback_unit
    if stmt_unit == "unknown":
        stmt_unit = None
    canonical = mapper.canonical(mapped, md_path.name, current_year, previous_year, statement_unit=stmt_unit)
    canonical = augment_from_rows(canonical, mapped, "CASHFLOW")
    # v13: raw source recovery covers mixed inline-year/date layouts (e.g. current value followed
    # by `(Năm 2024: ...)`, or `(31.12.2025); (31.12.2024)`) that can hydrate only one period in v12.
    if ext.get("scope_start_line") and ext.get("scope_end_line"):
        recovered_rows = extract_generic_statement_rows(
            text, ext["scope_start_line"], ext["scope_end_line"], current_year, previous_year, "CASHFLOW")
        canonical = augment_canonical_with_recovered_rows(canonical, recovered_rows, "CASHFLOW")
        # v16: label-less statutory code tables can safely hydrate an existing unique profile node.
        # This repairs period pairing without inventing labels or overwriting mapped values.
        code_evidence = extract_code_period_table(
            text, ext["scope_start_line"], ext["scope_end_line"], current_year, previous_year)
        canonical = hydrate_canonical_by_form_code(canonical, code_evidence, sector, method)
        canonical = reconcile_source_observations(canonical, "CASHFLOW")
    metrics = build_cashflow_metrics(canonical, mapped, ext, sector, sector_method, method, method_method)
    sr = (canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}
    (metrics.get("parser") or {}).update({
        "source_recovery": "v16", "source_recovered_rows": sr.get("rows_recovered", 0),
        "source_recovery_added_nodes": sr.get("added_nodes", 0),
        "source_recovery_filled_nodes": sr.get("filled_existing_nodes", 0),
        "source_recovery_conflicts": sr.get("conflicts", 0),
    })
    return {"canonical": canonical, "metrics": metrics, "rows": mapped, "scope": ext, "sector": sector, "method": method}


def process_one(md_path: Path, output_dir: Path, comparison_dir: Optional[Path], current_year: int, previous_year: int, sector: str, fp_index: FinancialPositionIndex, enable_notes: bool = True):
    base = stem_base(md_path)
    source_text = md_path.read_text(encoding="utf-8", errors="ignore")
    doc_unit_ctx = detect_document_unit(source_text)
    doc_unit = doc_unit_ctx.unit if doc_unit_ctx.unit != "unknown" else None

    inc = run_income(md_path, current_year, previous_year, sector, fallback_unit=doc_unit)
    cf = run_cashflow(md_path, current_year, previous_year, fallback_unit=doc_unit)
    output_dir.mkdir(parents=True, exist_ok=True)

    existing_path = find_existing_comparison(base, comparison_dir, output_dir, md_path.parent)
    existing = read_json(existing_path, {}) if existing_path else {}
    if not isinstance(existing, dict):
        existing = {}

    # Integrate the completed Financial Position pipeline/output before writing the unified comparison.
    fp = integrate_financial_position(
        base, output_dir, fp_index, existing, source_text=source_text,
        current_year=current_year, previous_year=previous_year, fallback_unit=doc_unit)

    # Cross-statement unit re-synchronization
    resolved_unit = (
        doc_unit
        or (inc.get("canonical") or {}).get("unit")
        or (cf.get("canonical") or {}).get("unit")
        or (fp.get("canonical") or {}).get("unit")
    )
    if resolved_unit and resolved_unit != "unknown":
        for obj in (inc.get("canonical"), cf.get("canonical"), fp.get("canonical")):
            if obj:
                if not obj.get("unit") or obj.get("unit") == "unknown":
                    obj["unit"] = resolved_unit
                for n in obj.get("nodes", []):
                    v = n.get("value")
                    if isinstance(v, dict) and (not v.get("unit") or v.get("unit") == "unknown"):
                        cname = fold_text(n.get("canonical_name", ""))
                        if "lai co ban" in cname or "lai suy giam" in cname:
                            v["unit"] = "vnd_per_share"
                        else:
                            v["unit"] = resolved_unit

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

    fp_path = output_dir / f"{base}.financial_position.canonical.json"
    if fp.get("canonical") is not None:
        write_json(fp_path, fp["canonical"])

    # v22.5 Notes Foundation: additive, non-destructive.
    # Primary statements stay authoritative; Notes is emitted as a separate Generic Note IR.
    notes_ir = None
    notes_path = output_dir / f"{base}.notes.ir.json"
    if enable_notes:
        notes_sector = inc.get("sector") or cf.get("sector") or "enterprise"
        primary_for_notes = {
            "financial_position": {"canonical": fp.get("canonical") or {}},
            "income_statement": {"canonical": inc.get("canonical") or {}},
            "cash_flow_statement": {"canonical": cf.get("canonical") or {}},
        }
        notes_ir = NotesPipeline(
            current_year=current_year,
            previous_year=previous_year,
        ).parse_text(
            source_text,
            source_name=md_path.name,
            sector=notes_sector,
            primary=primary_for_notes,
        )
        if (notes_ir.get("diagnostics") or {}).get("notes_found"):
            write_json(notes_path, notes_ir)
            notes_rows_dir = output_dir / "notes_rows"
            notes_rows_export = export_note_rows(
                notes_ir,
                notes_rows_dir,
                stem=base,
                write_json=True,
            )
        else:
            notes_rows_export = {"row_count": 0, "csv_file": None, "json_file": None}
            if notes_path.exists():
                notes_path.unlink()
    else:
        notes_rows_export = {"row_count": 0, "csv_file": None, "json_file": None}
    if not enable_notes and notes_path.exists():
        notes_path.unlink()

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
    if notes_ir is not None:
        nd = notes_ir.get("diagnostics") or {}
        merged["notes"] = {
            "schema_id": notes_ir.get("schema_id"),
            "schema_version": notes_ir.get("schema_version"),
            "status": "parsed" if nd.get("notes_found") else "not_detected",
            "ir_file": notes_path.name if nd.get("notes_found") else None,
            "scope_start": notes_ir.get("scope_start_line"),
            "scope_end": notes_ir.get("scope_end_line"),
            "sections": nd.get("section_count", 0),
            "tables": nd.get("table_count", 0),
            "rows": nd.get("row_count", 0),
            "exported_rows": notes_rows_export.get("row_count", 0),
            "rows_csv": (
                f"notes_rows/{notes_rows_export.get('csv_file')}"
                if notes_rows_export.get("csv_file") else None
            ),
            "rows_json": (
                f"notes_rows/{notes_rows_export.get('json_file')}"
                if notes_rows_export.get("json_file") else None
            ),
            "links": nd.get("link_count", 0),
            "high_confidence_links": nd.get("high_confidence_links", 0),
            "policy": "PRIMARY_GT_NOTES_non_destructive_v1",
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
        "notes_status": (
            "parsed" if notes_ir is not None and (notes_ir.get("diagnostics") or {}).get("notes_found")
            else ("not_detected" if enable_notes else "disabled")
        ),
        "notes_sections": ((notes_ir or {}).get("diagnostics") or {}).get("section_count", 0),
        "notes_tables": ((notes_ir or {}).get("diagnostics") or {}).get("table_count", 0),
        "notes_rows": ((notes_ir or {}).get("diagnostics") or {}).get("row_count", 0),
        "notes_exported_rows": notes_rows_export.get("row_count", 0) if enable_notes else 0,
        "notes_rows_csv": (
            f"notes_rows/{notes_rows_export.get('csv_file')}"
            if enable_notes and notes_rows_export.get("csv_file") else None
        ),
        "notes_links": ((notes_ir or {}).get("diagnostics") or {}).get("link_count", 0),
        "notes_ir_file": notes_path.name if notes_ir is not None and (notes_ir.get("diagnostics") or {}).get("notes_found") else None,
    }


def main():
    ap = argparse.ArgumentParser(description="Integrated mapper: Financial Position + Income + Cash Flow + additive Notes IR.")
    ap.add_argument("input", help="Markdown file or folder")
    ap.add_argument("--comparison-dir", help="Folder containing existing *.comparison.json")
    ap.add_argument("--financial-position-dir", help="Folder containing completed <base>.canonical.json Financial Position outputs. If omitted, nearby workspace folders are auto-scanned.")
    ap.add_argument("--output", default="comparison_v9")
    ap.add_argument("--current-year", type=int, default=2025)
    ap.add_argument("--previous-year", type=int, default=2024)
    ap.add_argument("--sector", choices=["auto", "bank", "enterprise", "securities", "insurance"], default="auto",
                    help="Income override only; Cash Flow sector is independently detected from its own scope.")
    ap.add_argument(
        "--notes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable/disable v22.5 additive Notes IR extraction. Primary statements remain authoritative.",
    )
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
            r = process_one(p, output_dir, comparison_dir, args.current_year, args.previous_year, args.sector, fp_index, enable_notes=args.notes)
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
        "income_statement_preserved_or_written","comparison_file","canonical_file","cashflow_canonical_file",
        "notes_status","notes_sections","notes_tables","notes_rows","notes_exported_rows","notes_rows_csv","notes_links","notes_ir_file","error"
    ]
    with (output_dir / "comparison_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nSummary: {output_dir / 'comparison_summary.csv'}")


if __name__ == "__main__":
    main()
