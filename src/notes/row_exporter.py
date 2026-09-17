from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROW_FIELDS = [
    "source_name",
    "sector",
    "note_id_raw",
    "note_id_normalized",
    "note_title",
    "note_title_normalized",
    "section_start_line",
    "section_end_line",
    "pages",
    "sector_topic",
    "block_id",
    "block_form",
    "semantic_shape",
    "block_start_line",
    "block_end_line",
    "headers",
    "dimensions",
    "row_index",
    "row_label",
    "row_label_normalized",
    "row_role",
    "row_code",
    "row_note_ref",
    "row_source_line",
    "row_unit",
    "row_unit_canonical",
    "current_raw",
    "current_normalized",
    "previous_raw",
    "previous_normalized",
    "value_count",
    "values",
    "raw_cells",
    "linked_targets",
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _as_list(value: Any) -> list:
    """Keep nested export fields as collections across legacy IR variants."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _first_by_role(values: list[dict], role: str):
    for value in values:
        if value.get("period_role") == role:
            return value
    return None


def flatten_note_rows(note_ir: dict) -> list[dict]:
    """Flatten Generic Note IR to one record per extracted source row.

    This is intentionally a presentation/export layer only. It does not change
    extraction, linking, reconciliation, or canonical values.

    Multi-axis tables are preserved losslessly in the `values`, `headers`, and
    `dimensions` JSON columns while also exposing `current_*` / `previous_*`
    convenience columns when those roles were inferred.
    """
    source_name = note_ir.get("source_name")
    sector = note_ir.get("sector")
    rows: list[dict] = []

    for section in note_ir.get("sections") or []:
        linked_targets = [
            {
                "target_ref": x.get("target_ref"),
                "relation": x.get("relation"),
                "confidence": x.get("confidence"),
            }
            for x in (section.get("links") or [])
        ]

        for block in section.get("blocks") or []:
            block_rows = block.get("rows") or []
            for row_index, row in enumerate(block_rows, start=1):
                values = _as_list(row.get("values"))
                current = _first_by_role(values, "current") or {}
                previous = _first_by_role(values, "previous") or {}

                row_unit = None
                for value in values:
                    if value.get("unit"):
                        row_unit = value.get("unit")
                        break
                row_unit = row_unit or block.get("unit") or section.get("unit")
                row_unit_canonical = None
                for value in values:
                    if value.get("unit_canonical"):
                        row_unit_canonical = value.get("unit_canonical")
                        break
                row_unit_canonical = row_unit_canonical or block.get("unit_canonical") or section.get("unit_canonical")

                rows.append({
                    "source_name": source_name,
                    "sector": sector,
                    "note_id_raw": section.get("note_id_raw"),
                    "note_id_normalized": section.get("note_id_normalized"),
                    "note_title": section.get("title_raw"),
                    "note_title_normalized": section.get("title_normalized"),
                    "section_start_line": section.get("source_start_line"),
                    "section_end_line": section.get("source_end_line"),
                    "pages": _as_list(section.get("pages")),
                    "sector_topic": section.get("sector_topic"),
                    "block_id": block.get("block_id"),
                    "block_form": block.get("form"),
                    "semantic_shape": block.get("semantic_shape"),
                    "block_start_line": block.get("source_start_line"),
                    "block_end_line": block.get("source_end_line"),
                    "headers": _as_list(block.get("headers_raw")),
                    "dimensions": _as_list(block.get("dimensions")),
                    "row_index": row_index,
                    "row_label": row.get("label_raw"),
                    "row_label_normalized": row.get("label_normalized"),
                    "row_role": row.get("row_role"),
                    "row_code": row.get("code"),
                    "row_note_ref": row.get("note_ref"),
                    "row_source_line": row.get("source_line"),
                    "row_unit": row_unit,
                    "row_unit_canonical": row_unit_canonical,
                    "current_raw": current.get("raw"),
                    "current_normalized": current.get("normalized"),
                    "previous_raw": previous.get("raw"),
                    "previous_normalized": previous.get("normalized"),
                    "value_count": len(values),
                    "values": _as_list(values),
                    "raw_cells": _as_list(row.get("raw_cells")),
                    "linked_targets": linked_targets,
                })
    return rows


def write_rows_csv(path: str | Path, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ROW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            for field in ("pages", "headers", "dimensions", "values", "raw_cells", "linked_targets"):
                if isinstance(csv_row.get(field), (list, dict)):
                    csv_row[field] = _json(csv_row[field])
            writer.writerow(csv_row)
    return path


def write_rows_json(path: str | Path, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_note_rows(
    note_ir: dict,
    output_dir: str | Path,
    *,
    stem: str | None = None,
    write_json: bool = True,
) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_name = note_ir.get("source_name") or "input"
    if stem is None:
        stem = Path(source_name).stem

    rows = flatten_note_rows(note_ir)
    csv_path = write_rows_csv(output_dir / f"{stem}.notes_rows.csv", rows)
    json_path = None
    if write_json:
        json_path = write_rows_json(output_dir / f"{stem}.notes_rows.json", rows)

    return {
        "row_count": len(rows),
        "csv_file": csv_path.name,
        "json_file": json_path.name if json_path else None,
        "rows": rows,
    }


def write_aggregate_rows(output_dir: str | Path, rows: list[dict]) -> dict:
    output_dir = Path(output_dir)
    csv_path = write_rows_csv(output_dir / "all_notes_rows.csv", rows)
    json_path = write_rows_json(output_dir / "all_notes_rows.json", rows)
    return {
        "row_count": len(rows),
        "csv_file": csv_path.name,
        "json_file": json_path.name,
    }
