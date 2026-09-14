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

SCHEMA = ROOT / "resources" / "income_statement_schema.json"
ALIASES = ROOT / "resources" / "income_statement_aliases.json"


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
    metrics = build_metrics(canonical, mapped, ext, sector, sector_method)
    return {"canonical": canonical, "metrics": metrics, "rows": mapped, "scope": ext, "sector": sector}


def process_one(md_path: Path, output_dir: Path, comparison_dir: Optional[Path], current_year: int, previous_year: int, sector: str):
    base = stem_base(md_path)
    inc = run_income(md_path, current_year, previous_year, sector)
    output_dir.mkdir(parents=True, exist_ok=True)

    canonical_path = output_dir / f"{base}.income.canonical.json"
    if inc["canonical"] is not None:
        write_json(canonical_path, inc["canonical"])
    elif canonical_path.exists():
        # Deterministic output: never leave an old/empty canonical beside a current
        # diagnostic saying no canonical was produced.
        canonical_path.unlink()

    existing_path = find_existing_comparison(base, comparison_dir, output_dir, md_path.parent)
    existing = read_json(existing_path, {}) if existing_path else {}
    if not isinstance(existing, dict):
        existing = {}
    merged = deepcopy(existing)
    merged.setdefault("source_name", md_path.name)
    merged.setdefault("mapping_strategy", "legacy")
    merged["income_statement"] = {
        "v05": inc["metrics"],
        "canonical_file": canonical_path.name if inc["canonical"] is not None else None,
    }
    merged_path = output_dir / f"{base}.comparison.json"
    write_json(merged_path, merged)

    m = inc["metrics"]
    mp = m.get("mapping", {})
    return {
        "source_name": md_path.name,
        "sector": inc["sector"],
        "status": m.get("status"),
        "scope_start": (m.get("parser") or {}).get("scope_start"),
        "scope_end": (m.get("parser") or {}).get("scope_end"),
        "scope_score": (m.get("parser") or {}).get("scope_score"),
        "sector_method": (m.get("parser") or {}).get("sector_method"),
        "patterns": ";".join((m.get("parser") or {}).get("patterns", [])),
        "input_rows": mp.get("input_rows", 0),
        "mapped_rows": mp.get("mapped_rows", 0),
        "unmapped_rows": mp.get("unmapped_rows", 0),
        "mapping_rate": mp.get("mapping_rate", 0.0),
        "income_value_nodes": m.get("value_nodes", 0),
        "income_current_nodes": m.get("current_value_nodes", 0),
        "income_previous_nodes": m.get("previous_value_nodes", 0),
        "current_coverage": mp.get("current_coverage", 0.0),
        "previous_coverage": mp.get("previous_coverage", 0.0),
        "formula_evaluated": (m.get("quality") or {}).get("formula_evaluated", 0),
        "formula_passed": (m.get("quality") or {}).get("formula_passed", 0),
        "formula_failed": (m.get("quality") or {}).get("formula_failed", 0),
        "formula_pass_rate": (m.get("quality") or {}).get("formula_pass_rate"),
        "sign_normalizations": (m.get("quality") or {}).get("sign_normalizations", 0),
        "financial_position_preserved": bool(existing.get("financial_position")),
        "comparison_file": merged_path.name,
        "canonical_file": canonical_path.name if inc["canonical"] is not None else None,
    }


def main():
    ap = argparse.ArgumentParser(description="Add robust Income Statement results to existing financial-position comparison JSONs.")
    ap.add_argument("input", help="Markdown file or folder")
    ap.add_argument("--comparison-dir", help="Folder containing existing *.comparison.json from financial-position runner")
    ap.add_argument("--output", default="comparison_v8")
    ap.add_argument("--current-year", type=int, default=2025)
    ap.add_argument("--previous-year", type=int, default=2024)
    ap.add_argument("--sector", choices=["auto", "bank", "enterprise", "securities", "insurance"], default="auto")
    args = ap.parse_args()

    input_path = Path(args.input)
    comparison_dir = Path(args.comparison_dir) if args.comparison_dir else None
    output_dir = Path(args.output)
    try:
        md_files = select_md_files(input_path)
    except Exception as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        raise SystemExit(2)

    rows = []
    for p in md_files:
        try:
            r = process_one(p, output_dir, comparison_dir, args.current_year, args.previous_year, args.sector)
            rows.append(r)
            print(f"[OK] {p.name}: status={r['status']} income={r['income_value_nodes']} mapped={r['mapped_rows']}/{r['input_rows']} sector={r['sector']}")
        except Exception as e:
            rows.append({"source_name": p.name, "status": "error", "error": repr(e)})
            print(f"[ERROR] {p.name}: {e}", file=sys.stderr)

    if not rows:
        # Defensive invariant: a successful batch may never produce an empty summary.
        print("[FATAL] Internal invariant failed: discovered Markdown files but produced zero summary rows.", file=sys.stderr)
        raise SystemExit(3)

    write_json(output_dir / "comparison_summary.json", rows)
    cols = [
        "source_name","sector","status","scope_start","scope_end","scope_score","sector_method","patterns",
        "input_rows","mapped_rows","unmapped_rows","mapping_rate","income_value_nodes","income_current_nodes",
        "income_previous_nodes","current_coverage","previous_coverage","formula_evaluated","formula_passed",
        "formula_failed","formula_pass_rate","sign_normalizations","financial_position_preserved",
        "comparison_file","canonical_file","error"
    ]
    with (output_dir / "comparison_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nSummary: {output_dir / 'comparison_summary.csv'}")


if __name__ == "__main__":
    main()
