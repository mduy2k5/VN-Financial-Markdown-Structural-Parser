from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.notes.pipeline import NotesPipeline
from src.notes.scanner import detect_notes_scope, explain_notes_scope_candidates

try:
    from flat_parser.preprocess import filter_noise
    from flat_parser.textnorm import normalize_lines
    from flat_parser.statement_scanner import scan_statements
except Exception:
    filter_noise = normalize_lines = scan_statements = None


def _files(inp: Path) -> list[Path]:
    if inp.is_file():
        return [inp]
    return sorted(p for p in inp.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"})


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _scanner_for(text: str):
    if scan_statements is None:
        return None
    try:
        return scan_statements(filter_noise(normalize_lines(text)))
    except Exception:
        return None


def _sector(scanner: dict | None) -> str:
    return (((scanner or {}).get("sector") or {}).get("sector") or "enterprise")


def evaluate_file(path: Path, pipe: NotesPipeline, per_file: Path | None = None) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    scanner = _scanner_for(text)
    sector = _sector(scanner)
    result = pipe.parse_text(
        text,
        source_name=path.name,
        sector=sector,
        scanner_result=scanner,
        primary=None,
    )
    d = result.get("diagnostics") or {}
    shapes = d.get("semantic_shapes") or {}
    forms = d.get("block_forms") or {}
    scope = d.get("scope") or {}
    candidates = explain_notes_scope_candidates(text)
    rejected = [x for x in candidates if x.get("rejected")]

    row = {
        "source_name": path.name,
        "sector": sector,
        "notes_found": bool(d.get("notes_found")),
        "scope_start": result.get("scope_start_line"),
        "scope_end": result.get("scope_end_line"),
        "scope_confidence": result.get("scope_confidence"),
        "section_count": d.get("section_count", 0),
        "block_count": d.get("block_count", 0),
        "table_count": d.get("table_count", 0),
        "row_count": d.get("row_count", 0),
        "breakdown_count": shapes.get("breakdown", 0),
        "movement_count": shapes.get("movement", 0),
        "matrix_count": shapes.get("matrix", 0),
        "reconciliation_count": shapes.get("reconciliation", 0),
        "aging_count": shapes.get("aging", 0),
        "narrative_count": shapes.get("narrative", 0),
        "unknown_count": shapes.get("unknown", 0),
        "table_form_count": forms.get("table", 0),
        "paragraph_form_count": forms.get("paragraph", 0),
        "link_count": d.get("link_count", 0),
        "high_confidence_links": d.get("high_confidence_links", 0),
        "decoy_primary_heading_count": len(d.get("primary_heading_decoys_inside_notes") or []),
        "scope_rejected_candidate_count": len(rejected),
        "scope_evidence": " | ".join(scope.get("evidence") or []),
    }

    if per_file is not None:
        per_file.mkdir(parents=True, exist_ok=True)
        (per_file / f"{path.stem}.notes.ir.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (per_file / f"{path.stem}.scope_candidates.json").write_text(
            json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="v23 Notes Scope & Coverage evaluator")
    ap.add_argument("input", help="Markdown/TXT file or folder")
    ap.add_argument("--output", default="output/notes/v23_eval")
    ap.add_argument("--current-year", type=int, default=None)
    ap.add_argument("--previous-year", type=int, default=None)
    ap.add_argument("--write-per-file", action=argparse.BooleanOptionalAction, default=False)
    args = ap.parse_args()

    inp = Path(args.input)
    paths = _files(inp)
    if not paths:
        raise SystemExit("No Markdown/TXT files found")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    per_file = out / "per_file" if args.write_per_file else None
    pipe = NotesPipeline(current_year=args.current_year, previous_year=args.previous_year)

    rows = []
    for i, path in enumerate(paths, start=1):
        row = evaluate_file(path, pipe, per_file=per_file)
        rows.append(row)
        print(
            f"[{i:02d}/{len(paths):02d}] {path.name}: "
            f"notes={row['notes_found']} sections={row['section_count']} "
            f"tables={row['table_count']} rows={row['row_count']}"
        )

    _write_csv(out / "inventory.csv", rows)
    (out / "inventory.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    found = [r for r in rows if r["notes_found"]]
    summary = {
        "version": "v23",
        "file_count": len(rows),
        "notes_detected": len(found),
        "notes_detection_rate": round(len(found) / len(rows), 6) if rows else 0.0,
        "sections": sum(int(r["section_count"] or 0) for r in rows),
        "tables": sum(int(r["table_count"] or 0) for r in rows),
        "rows": sum(int(r["row_count"] or 0) for r in rows),
        "breakdown": sum(int(r["breakdown_count"] or 0) for r in rows),
        "movement": sum(int(r["movement_count"] or 0) for r in rows),
        "matrix": sum(int(r["matrix_count"] or 0) for r in rows),
        "reconciliation": sum(int(r["reconciliation_count"] or 0) for r in rows),
        "aging": sum(int(r["aging_count"] or 0) for r in rows),
        "narrative": sum(int(r["narrative_count"] or 0) for r in rows),
        "unknown": sum(int(r["unknown_count"] or 0) for r in rows),
        "rejected_scope_candidates": sum(int(r["scope_rejected_candidate_count"] or 0) for r in rows),
        "decoy_primary_headings_inside_notes": sum(int(r["decoy_primary_heading_count"] or 0) for r in rows),
        "release_gates": {
            "notes_scope_detection_target": "all discovered Markdown reports",
            "false_primary_capture_target": 0,
            "primary_regression_target": "unchanged",
        },
    }
    (out / "coverage_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    misses = [r for r in rows if not r["notes_found"]]
    suspicious = [
        r for r in rows
        if r["notes_found"] and (
            int(r["section_count"] or 0) == 0
            or int(r["scope_rejected_candidate_count"] or 0) > 0
            or float(r["scope_confidence"] or 0) < 0.90
        )
    ]
    _write_csv(out / "scope_misses.csv", misses)
    _write_csv(out / "suspicious_scope.csv", suspicious)

    # Structural extraction backlog: narratives/unknowns are where v23.1 should focus.
    backlog = sorted(rows, key=lambda r: (-(int(r["narrative_count"] or 0) + int(r["unknown_count"] or 0)), r["source_name"]))
    _write_csv(out / "structural_backlog.csv", backlog)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
