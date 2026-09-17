from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Make direct execution (`python scripts/build_notes_ground_truth.py`) resolve the
# repository packages consistently across Windows Python installations.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.notes.pipeline import NotesPipeline
from src.notes.row_exporter import flatten_note_rows
from src.common import infer_report_year_pair

try:
    from flat_parser.preprocess import filter_noise
    from flat_parser.statement_scanner import scan_statements
    from flat_parser.textnorm import normalize_lines
except Exception:
    filter_noise = normalize_lines = scan_statements = None


NESTED_ROW_FIELDS = {
    "pages",
    "headers",
    "dimensions",
    "values",
    "raw_cells",
    "linked_targets",
}


def source_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def native_rows(note_ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Return row-level records with native JSON arrays instead of CSV strings."""
    rows = flatten_note_rows(note_ir)
    for row in rows:
        for field in NESTED_ROW_FIELDS:
            value = row.get(field)
            if isinstance(value, str):
                row[field] = json.loads(value)
    return rows


def parse_sector(text: str) -> tuple[str, dict[str, Any] | None]:
    if scan_statements is None:
        return "enterprise", None
    try:
        scanner = scan_statements(filter_noise(normalize_lines(text)))
    except Exception:
        return "enterprise", None
    sector = ((scanner or {}).get("sector") or {}).get("sector") or "enterprise"
    return sector, scanner


def build_document(
    path: Path,
    pipe: NotesPipeline,
    current_year: int,
    previous_year: int,
) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    sector, scanner = parse_sector(text)
    note_ir = pipe.parse_text(
        text,
        source_name=path.name,
        sector=sector,
        scanner_result=scanner,
    )
    diagnostics = note_ir.get("diagnostics") or {}
    scope = diagnostics.get("scope") or {}
    rows = native_rows(note_ir)

    return {
        "schema_version": "financial_notes_ground_truth_v1",
        "source_file": path.name,
        "source_sha256": source_hash(raw),
        "symbol": path.stem.split("_", 1)[0],
        "period": {
            "current_year": current_year,
            "previous_year": previous_year,
        },
        "review": {
            "status": "requires_manual_review",
            "origin": "parser_assisted_from_md_report",
            "note": (
                "Source-grounded baseline generated from Markdown. Scope, OCR rows, "
                "dimensions and semantic links must be reviewed before treating this "
                "artifact as a human-verified gold standard."
            ),
        },
        "scope": {
            "found": bool(scope.get("found")),
            "start_line": scope.get("start_line"),
            "end_line": scope.get("end_line"),
            "confidence": scope.get("confidence"),
            "evidence": scope.get("evidence") or [],
        },
        "sector": note_ir.get("sector"),
        "summary": {
            "section_count": diagnostics.get("section_count", 0),
            "block_count": diagnostics.get("block_count", 0),
            "table_count": diagnostics.get("table_count", 0),
            "row_count": len(rows),
            "link_count": diagnostics.get("link_count", 0),
            "high_confidence_links": diagnostics.get("high_confidence_links", 0),
        },
        "sections": note_ir.get("sections") or [],
        "rows": rows,
        "links": note_ir.get("links") or [],
        "reconciliation": note_ir.get("reconciliation") or {},
        "diagnostics": diagnostics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build source-grounded Notes ground-truth baselines from Markdown reports."
    )
    parser.add_argument("input", nargs="?", default="md_reports")
    parser.add_argument("--output", default="ground_truth/notes")
    parser.add_argument("--current-year", type=int, default=None)
    parser.add_argument("--previous-year", type=int, default=None)
    args = parser.parse_args()

    input_path = Path(args.input)
    files = [input_path] if input_path.is_file() else sorted(input_path.glob("*.md"))
    if not files:
        raise SystemExit(f"No Markdown reports found in {input_path}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_files: list[dict[str, Any]] = []

    for path in files:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        year_resolution = infer_report_year_pair(
            text,
            source_name=path.name,
            current_year=args.current_year,
            previous_year=args.previous_year,
        )
        pipe = NotesPipeline(
            current_year=year_resolution["current_year"],
            previous_year=year_resolution["previous_year"],
        )
        document = build_document(
            path,
            pipe,
            year_resolution["current_year"],
            year_resolution["previous_year"],
        )
        document["period"]["year_resolution"] = year_resolution
        output_name = f"{path.stem}.notes.ground_truth.json"
        output_path = output_dir / output_name
        output_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary = document["summary"]
        manifest_files.append(
            {
                "source_file": path.name,
                "ground_truth_file": output_name,
                "source_sha256": document["source_sha256"],
                "current_year": document["period"]["current_year"],
                "previous_year": document["period"]["previous_year"],
                "sector": document["sector"],
                "scope_found": document["scope"]["found"],
                "scope_confidence": document["scope"]["confidence"],
                **summary,
                "review_status": document["review"]["status"],
            }
        )
        print(
            f"[NOTES_GT] {path.name}: sections={summary['section_count']} "
            f"rows={summary['row_count']} -> {output_name}"
        )

    manifest = {
        "schema_version": "financial_notes_ground_truth_manifest_v1",
        "source_directory": str(input_path),
        "report_count": len(manifest_files),
        "scope_found_count": sum(bool(item["scope_found"]) for item in manifest_files),
        "total_sections": sum(item["section_count"] for item in manifest_files),
        "total_rows": sum(item["row_count"] for item in manifest_files),
        "review_status": "requires_manual_review",
        "files": manifest_files,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[DONE] reports={manifest['report_count']} "
        f"scope_found={manifest['scope_found_count']} rows={manifest['total_rows']}"
    )


if __name__ == "__main__":
    main()
