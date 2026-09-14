from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from income_mapper import (
    IncomeMapper, auto_sector, load_rows, save_debug_rows,
    DEFAULT_SCHEMA, DEFAULT_ALIASES,
)


def process_one(path: Path, out: Path, args):
    rows, cy, py = load_rows(path, args.current_year, args.previous_year)
    sector = args.sector
    if sector == "auto":
        sector = auto_sector(rows, args.schema, args.aliases) if rows else args.empty_sector

    if sector not in {"bank", "enterprise"}:
        special = sector if sector in {"insurance", "securities"} else None
        result = {
            "source_name": path.name,
            "sector": sector,
            "status": "unsupported_sector" if special else "sector_unknown",
            "rows_total": len(rows),
            "message": (f"Detected {special} income profile, but no schema is installed for it." if special
                        else "Cannot determine bank/enterprise profile from discovered income rows.")
        }
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{path.stem}.income.status.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{path.name}: SKIP sector=unknown rows={len(rows)}")
        return result

    mapper = IncomeMapper(
        args.schema, args.aliases, sector=sector,
        regex_fallback=args.regex_fallback,
        regex_min_score=args.regex_min_score,
        regex_gap=args.regex_gap,
    )
    mapped_rows = mapper.map_rows(rows)
    canonical = mapper.canonical(mapped_rows, path.name, cy, py)

    out.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    (out / f"{stem}.income.canonical.json").write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_debug_rows(mapped_rows, out / f"{stem}.income.mapping.csv")

    s = canonical["mapping_summary"]
    print(
        f"{path.name}: sector={sector} status={canonical['status']} "
        f"rows={s['rows_total']} mapped={s['mapped']} unmapped={s['unmapped']} "
        f"valued={s['valued_nodes']} current={s['current_nodes']} "
        f"previous={s['previous_nodes']} both={s['both_period_nodes']}"
    )
    return {
        "file": path.name,
        "sector": sector,
        "status": canonical["status"],
        **s,
    }


def main():
    ap = argparse.ArgumentParser(description="Map common-converter income rows/observations to canonical income schema.")
    ap.add_argument("input", help="CSV/JSON row file or folder")
    ap.add_argument("--output", default="output_income_map")
    ap.add_argument("--sector", choices=["auto", "bank", "enterprise", "insurance", "securities"], default="auto")
    ap.add_argument("--empty-sector", choices=["unknown", "bank", "enterprise", "insurance", "securities"], default="unknown",
                    help="Only used when no rows can be discovered. Prefer unknown unless routing is known externally.")
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    ap.add_argument("--aliases", default=str(DEFAULT_ALIASES))
    ap.add_argument("--current-year", type=int, default=None)
    ap.add_argument("--previous-year", type=int, default=None)
    ap.add_argument("--regex-fallback", dest="regex_fallback", action="store_true", default=True)
    ap.add_argument("--no-regex-fallback", dest="regex_fallback", action="store_false")
    ap.add_argument("--regex-min-score", type=float, default=0.93)
    ap.add_argument("--regex-gap", type=float, default=0.08)
    args = ap.parse_args()

    p = Path(args.input)
    out = Path(args.output)
    if p.is_file():
        files = [p]
    else:
        files = sorted([*p.glob("*.rows.json"), *p.glob("*.json"), *p.glob("*.csv")])
        # Avoid recursively remapping outputs from previous runs when scanning a folder.
        files = [f for f in files if ".income.canonical" not in f.name and ".income.status" not in f.name]

    report = [process_one(f, out, args) for f in files]
    if report:
        fields = sorted({k for r in report for k in r.keys()})
        with (out / "income_mapping_report.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader(); w.writerows(report)
        (out / "income_mapping_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
