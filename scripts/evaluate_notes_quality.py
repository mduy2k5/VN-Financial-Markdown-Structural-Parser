"""Create a compact, reproducible quality report for Notes batch outputs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _percent(numerator: int, denominator: int) -> float:
    return round((100 * numerator / denominator), 2) if denominator else 0.0


def _rows(output_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted((output_dir / "notes_rows").glob("*.notes_rows.json")):
        rows.extend(_load_json(path))
    return rows


def _values(rows: list[dict]) -> list[dict]:
    values: list[dict] = []
    for row in rows:
        raw_values = row.get("values", "[]")
        values.extend(json.loads(raw_values) if isinstance(raw_values, str) else raw_values)
    return values


def evaluate(output_dir: Path, linked_dir: Path | None = None) -> dict:
    rows = _rows(output_dir)
    values = _values(rows)
    irs = [
        _load_json(path)
        for path in sorted((output_dir / "ir").glob("*.notes.ir.json"))
    ]
    dimensions = [json.loads(row.get("dimensions", "[]")) for row in rows]

    result = {
        "schema_version": "financial_notes_quality_report_v1",
        "output_directory": str(output_dir),
        "reports": len(irs),
        "rows": len(rows),
        "values": len(values),
        "value_quality": {
            "normalized_values": sum(value.get("normalized") is not None for value in values),
            "normalized_rate_pct": _percent(
                sum(value.get("normalized") is not None for value in values), len(values)
            ),
            "period_roles": dict(sorted(Counter(value.get("period_role") or "missing" for value in values).items())),
            "movement_roles": dict(sorted(Counter(value.get("movement_role") or "missing" for value in values).items())),
            "canonical_units": dict(sorted(Counter(row.get("row_unit_canonical") or "missing" for row in rows).items())),
        },
        "structural_quality": {
            "rows_with_dimensions": sum(bool(item) for item in dimensions),
            "rows_with_dimensions_rate_pct": _percent(sum(bool(item) for item in dimensions), len(rows)),
            "dimension_kinds": dict(sorted(Counter(dimension["kind"] for item in dimensions for dimension in item).items())),
            "section_ref_collisions": sum(item.get("diagnostics", {}).get("section_ref_collision_count", 0) for item in irs),
            "block_id_collisions": sum(item.get("diagnostics", {}).get("block_id_collision_count", 0) for item in irs),
            "repeated_logical_note_sections": sum(item.get("diagnostics", {}).get("repeated_logical_note_sections", 0) for item in irs),
        },
    }
    if linked_dir:
        summary = _load_json(linked_dir / "notes_summary.json")
        files = summary.get("files", [])
        reconciliation = Counter()
        for item in files:
            reconciliation.update(item.get("reconciliation", {}))
        result["primary_statement_linking"] = {
            "output_directory": str(linked_dir),
            "links": sum(item.get("links", 0) for item in files),
            "high_confidence_links": sum(item.get("high_confidence_links", 0) for item in files),
            "reconciliation": dict(sorted(reconciliation.items())),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output_notes"))
    parser.add_argument("--linked-output", type=Path, default=Path("output_notes_linked"))
    parser.add_argument("--report", type=Path, default=Path("ground_truth/notes/quality_report_current.json"))
    args = parser.parse_args()

    report = evaluate(args.output, args.linked_output if args.linked_output.exists() else None)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
