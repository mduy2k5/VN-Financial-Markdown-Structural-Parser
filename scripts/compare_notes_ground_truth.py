from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Keep direct script execution independent of the Python interpreter's script-dir
# import rules.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


NESTED_ROW_FIELDS = {
    "pages",
    "headers",
    "dimensions",
    "values",
    "raw_cells",
    "linked_targets",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for field in NESTED_ROW_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = json.loads(value)
    return normalized


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def semantic_row(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("block_id"),
        row.get("row_label_normalized") or row.get("row_label"),
        row.get("row_role"),
        row.get("row_code"),
        row.get("current_normalized"),
        row.get("previous_normalized"),
        row.get("row_unit_canonical") or row.get("row_unit"),
    )


def value_row(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("block_id"),
        row.get("current_normalized"),
        row.get("previous_normalized"),
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_report(
    gt_path: Path,
    rows_path: Path,
    ir_path: Path,
    source_path: Path,
) -> dict[str, Any]:
    gt = load_json(gt_path)
    current_rows = [normalize_row(row) for row in load_json(rows_path)]
    expected_rows = [normalize_row(row) for row in gt.get("rows") or []]
    current_ir = load_json(ir_path)

    current_counter = Counter(stable_json(row) for row in current_rows)
    expected_counter = Counter(stable_json(row) for row in expected_rows)
    current_semantic = Counter(stable_json(semantic_row(row)) for row in current_rows)
    expected_semantic = Counter(stable_json(semantic_row(row)) for row in expected_rows)
    current_values = Counter(stable_json(value_row(row)) for row in current_rows)
    expected_values = Counter(stable_json(value_row(row)) for row in expected_rows)
    missing_rows = sum((expected_counter - current_counter).values())
    unexpected_rows = sum((current_counter - expected_counter).values())
    semantic_missing = sum((expected_semantic - current_semantic).values())
    semantic_unexpected = sum((current_semantic - expected_semantic).values())
    value_missing = sum((expected_values - current_values).values())
    value_unexpected = sum((current_values - expected_values).values())

    current_scope = ((current_ir.get("diagnostics") or {}).get("scope") or {})
    expected_scope = gt.get("scope") or {}
    scope_fields = ("found", "start_line", "end_line", "confidence", "evidence")
    scope_equal = all(current_scope.get(key) == expected_scope.get(key) for key in scope_fields)

    sections_equal = current_ir.get("sections") == gt.get("sections")
    links_equal = (current_ir.get("links") or []) == (gt.get("links") or [])
    reconciliation_equal = (current_ir.get("reconciliation") or {}) == (
        gt.get("reconciliation") or {}
    )
    diagnostics_equal = (current_ir.get("diagnostics") or {}) == (
        gt.get("diagnostics") or {}
    )
    ordered_rows_equal = current_rows == expected_rows
    source_hash_equal = source_path.exists() and sha256(source_path) == gt.get("source_sha256")

    exact_match = all(
        (
            source_hash_equal,
            scope_equal,
            sections_equal,
            links_equal,
            reconciliation_equal,
            diagnostics_equal,
            ordered_rows_equal,
        )
    )
    return {
        "source_file": gt.get("source_file"),
        "ground_truth_file": gt_path.name,
        "current_rows_file": rows_path.name,
        "current_ir_file": ir_path.name,
        "source_hash_equal": source_hash_equal,
        "expected_row_count": len(expected_rows),
        "current_row_count": len(current_rows),
        "ordered_rows_equal": ordered_rows_equal,
        "missing_rows": missing_rows,
        "unexpected_rows": unexpected_rows,
        "semantic_rows_equal": semantic_missing == 0 and semantic_unexpected == 0,
        "semantic_missing_rows": semantic_missing,
        "semantic_unexpected_rows": semantic_unexpected,
        "value_rows_equal": value_missing == 0 and value_unexpected == 0,
        "value_missing_rows": value_missing,
        "value_unexpected_rows": value_unexpected,
        "scope_equal": scope_equal,
        "sections_equal": sections_equal,
        "links_equal": links_equal,
        "reconciliation_equal": reconciliation_equal,
        "diagnostics_equal": diagnostics_equal,
        "exact_match": exact_match,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare current Notes output with source-grounded Notes baselines."
    )
    parser.add_argument("--ground-truth", default="ground_truth/notes")
    parser.add_argument("--current", default="output/notes/raw")
    parser.add_argument("--sources", default="md_reports")
    parser.add_argument(
        "--report",
        default="ground_truth/notes/comparison_current.json",
    )
    args = parser.parse_args()

    gt_dir = Path(args.ground_truth)
    current_dir = Path(args.current)
    source_dir = Path(args.sources)
    report_path = Path(args.report)

    gt_files = sorted(gt_dir.glob("*.notes.ground_truth.json"))
    comparisons: list[dict[str, Any]] = []
    missing_current: list[dict[str, str]] = []

    for gt_path in gt_files:
        gt = load_json(gt_path)
        source_file = gt["source_file"]
        stem = Path(source_file).stem
        rows_path = current_dir / "notes_rows" / f"{stem}.notes_rows.json"
        ir_path = current_dir / "ir" / f"{stem}.notes.ir.json"
        if not ir_path.exists() and (current_dir / f"{stem}.notes.ir.json").exists():
            ir_path = current_dir / f"{stem}.notes.ir.json"
        if not rows_path.exists() or not ir_path.exists():
            missing_current.append(
                {
                    "source_file": source_file,
                    "rows_missing": str(not rows_path.exists()).lower(),
                    "ir_missing": str(not ir_path.exists()).lower(),
                }
            )
            continue
        comparisons.append(
            compare_report(gt_path, rows_path, ir_path, source_dir / source_file)
        )

    exact_matches = sum(item["exact_match"] for item in comparisons)
    summary = {
        "schema_version": "financial_notes_ground_truth_comparison_v1",
        "ground_truth_directory": str(gt_dir),
        "current_output_directory": str(current_dir),
        "ground_truth_reports": len(gt_files),
        "compared_reports": len(comparisons),
        "missing_current_reports": len(missing_current),
        "exact_match_reports": exact_matches,
        "different_reports": len(comparisons) - exact_matches,
        "expected_rows": sum(item["expected_row_count"] for item in comparisons),
        "current_rows": sum(item["current_row_count"] for item in comparisons),
        "missing_rows": sum(item["missing_rows"] for item in comparisons),
        "unexpected_rows": sum(item["unexpected_rows"] for item in comparisons),
        "semantic_equal_reports": sum(item["semantic_rows_equal"] for item in comparisons),
        "semantic_missing_rows": sum(item["semantic_missing_rows"] for item in comparisons),
        "semantic_unexpected_rows": sum(item["semantic_unexpected_rows"] for item in comparisons),
        "value_equal_reports": sum(item["value_rows_equal"] for item in comparisons),
        "value_missing_rows": sum(item["value_missing_rows"] for item in comparisons),
        "value_unexpected_rows": sum(item["value_unexpected_rows"] for item in comparisons),
        "source_hash_mismatches": sum(not item["source_hash_equal"] for item in comparisons),
        "scope_mismatches": sum(not item["scope_equal"] for item in comparisons),
        "section_mismatches": sum(not item["sections_equal"] for item in comparisons),
        "row_order_mismatches": sum(not item["ordered_rows_equal"] for item in comparisons),
        "limitations": (
            "The current ground truth is parser-assisted and marked requires_manual_review. "
            "This comparison measures reproducibility/regression against that snapshot, not "
            "accuracy against a human-verified gold standard."
        ),
        "missing_current": missing_current,
        "files": comparisons,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in summary.items() if key not in {"files", "missing_current", "limitations"}}, ensure_ascii=False, indent=2))
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
