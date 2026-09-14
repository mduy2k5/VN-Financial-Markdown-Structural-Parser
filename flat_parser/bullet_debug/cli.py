from __future__ import annotations
import argparse
from pathlib import Path
from .flow import BulletDebugFlow


def main() -> None:
    ap = argparse.ArgumentParser(description="Debug four star-bullet structural patterns into a 5-column CSV.")
    ap.add_argument("input", help="Markdown file or directory")
    ap.add_argument("--output", required=True, help="Output CSV file (single input) or directory")
    ap.add_argument("--recursive", action="store_true")
    args = ap.parse_args()

    src = Path(args.input)
    out = Path(args.output)
    flow = BulletDebugFlow()

    if src.is_file():
        debug = out.with_suffix(".debug.json")
        rows, info = flow.run_file(src, out, debug)
        print(f"{src.name}: {len(rows)} rows -> {out}")
        return

    out.mkdir(parents=True, exist_ok=True)
    globber = src.rglob("*.md") if args.recursive else src.glob("*.md")
    total = 0
    files = 0
    for p in sorted(globber):
        csv_path = out / f"{p.stem}.bullet_debug.csv"
        dbg_path = out / f"{p.stem}.bullet_debug.json"
        rows, _ = flow.run_file(p, csv_path, dbg_path)
        total += len(rows); files += 1
        print(f"{p.name}: {len(rows)}")
    print(f"files={files} rows={total}")

if __name__ == "__main__":
    main()
