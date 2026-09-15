from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.notes.pipeline import NotesPipeline

try:
    from flat_parser.preprocess import filter_noise
    from flat_parser.textnorm import normalize_lines
    from flat_parser.statement_scanner import scan_statements
except Exception:
    filter_noise = normalize_lines = scan_statements = None


def main():
    ap = argparse.ArgumentParser(description="v22.5.0 Notes Foundation runner")
    ap.add_argument("input", help="Markdown file or folder")
    ap.add_argument("--output", default="output_notes")
    ap.add_argument("--sector", choices=["enterprise", "bank", "securities", "insurance", "auto"], default="auto")
    ap.add_argument("--current-year", type=int, default=2025)
    ap.add_argument("--previous-year", type=int, default=2024)
    args = ap.parse_args()

    inp = Path(args.input)
    files = [inp] if inp.is_file() else sorted(inp.rglob("*.md"))
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    pipe = NotesPipeline(current_year=args.current_year, previous_year=args.previous_year)
    summary = []

    for path in files:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        scanner = None
        sector = args.sector
        if scan_statements is not None:
            scanner = scan_statements(filter_noise(normalize_lines(text)))
            if sector == "auto":
                sector = ((scanner.get("sector") or {}).get("sector") or "enterprise")
        elif sector == "auto":
            sector = "enterprise"

        result = pipe.parse_text(
            text,
            source_name=path.name,
            sector=sector,
            scanner_result=scanner,
        )
        dest = out / f"{path.stem}.notes.ir.json"
        dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        d = result.get("diagnostics") or {}
        summary.append({
            "source_name": path.name,
            "sector": sector,
            "notes_found": d.get("notes_found"),
            "sections": d.get("section_count", 0),
            "tables": d.get("table_count", 0),
            "rows": d.get("row_count", 0),
            "decoy_primary_headings": len(d.get("primary_heading_decoys_inside_notes") or []),
            "output": dest.name,
        })
        print(f"[NOTES] {path.name}: sections={summary[-1]['sections']} tables={summary[-1]['tables']} rows={summary[-1]['rows']}")

    (out / "notes_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
