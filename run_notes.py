from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.notes.pipeline import NotesPipeline
from src.notes.row_exporter import export_note_rows, write_aggregate_rows

try:
    from flat_parser.preprocess import filter_noise
    from flat_parser.textnorm import normalize_lines
    from flat_parser.statement_scanner import scan_statements
except Exception:
    filter_noise = normalize_lines = scan_statements = None


def main():
    ap = argparse.ArgumentParser(description="v23 Notes runner with row-level export")
    ap.add_argument("input", help="Markdown file or folder")
    ap.add_argument("--output", default="output_notes")
    ap.add_argument("--sector", choices=["enterprise", "bank", "securities", "insurance", "auto"], default="auto")
    ap.add_argument("--current-year", type=int, default=2025)
    ap.add_argument("--previous-year", type=int, default=2024)
    ap.add_argument(
        "--write-ir",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also preserve full Generic Note IR JSON under <output>/ir/.",
    )
    args = ap.parse_args()

    inp = Path(args.input)
    files = [inp] if inp.is_file() else sorted(
        p for p in inp.rglob("*")
        if p.is_file() and p.suffix.lower() in {".md", ".txt"}
    )
    if not files:
        raise SystemExit("No Markdown/TXT files found")

    out = Path(args.output)
    rows_dir = out / "notes_rows"
    ir_dir = out / "ir"
    out.mkdir(parents=True, exist_ok=True)
    rows_dir.mkdir(parents=True, exist_ok=True)
    if args.write_ir:
        ir_dir.mkdir(parents=True, exist_ok=True)

    pipe = NotesPipeline(current_year=args.current_year, previous_year=args.previous_year)
    summary = []
    all_rows = []

    for path in files:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        scanner = None
        sector = args.sector
        if scan_statements is not None:
            try:
                scanner = scan_statements(filter_noise(normalize_lines(text)))
            except Exception:
                scanner = None
            if sector == "auto":
                sector = ((scanner or {}).get("sector") or {}).get("sector") or "enterprise"
        elif sector == "auto":
            sector = "enterprise"

        result = pipe.parse_text(
            text,
            source_name=path.name,
            sector=sector,
            scanner_result=scanner,
        )
        d = result.get("diagnostics") or {}

        ir_file = None
        if args.write_ir and d.get("notes_found"):
            ir_path = ir_dir / f"{path.stem}.notes.ir.json"
            ir_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            ir_file = str(ir_path.relative_to(out))

        export = export_note_rows(result, rows_dir, stem=path.stem, write_json=True)
        all_rows.extend(export["rows"])

        summary.append({
            "source_name": path.name,
            "sector": sector,
            "notes_found": bool(d.get("notes_found")),
            "sections": d.get("section_count", 0),
            "tables": d.get("table_count", 0),
            "rows": export["row_count"],
            "rows_csv": f"notes_rows/{export['csv_file']}",
            "rows_json": f"notes_rows/{export['json_file']}" if export["json_file"] else None,
            "ir_file": ir_file,
        })
        print(
            f"[NOTES] {path.name}: sections={summary[-1]['sections']} "
            f"tables={summary[-1]['tables']} rows={summary[-1]['rows']} "
            f"-> notes_rows/{export['csv_file']}"
        )

    aggregate = write_aggregate_rows(rows_dir, all_rows)

    (out / "notes_summary.json").write_text(
        json.dumps({
            "files": summary,
            "aggregate_rows": aggregate,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"[DONE] files={len(files)} extracted_rows={aggregate['row_count']} "
        f"folder={rows_dir}"
    )


if __name__ == "__main__":
    main()
