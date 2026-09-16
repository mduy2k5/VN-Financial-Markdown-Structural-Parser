from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


DEFAULT_REPORTS = [
    "CTG_BCTC_2025_hop_nhat_kiem_toan",
    "DIG_BCTC_2025_hop_nhat_kiem_toan",
    "NVB_BCTC_2025_hop_nhat_kiem_toan",
    "DXS_BCTC_2025_hop_nhat_kiem_toan",
    "VCB_BCTC_2025_hop_nhat_kiem_toan",
    "ABB_BCTC_2025_hop_nhat_kiem_toan",
    "ACB_BCTC_2025_hop_nhat_kiem_toan",
    "ANV_BCTC_2025_hop_nhat_kiem_toan",
    "GVR_BCTC_2025_hop_nhat_kiem_toan",
    "BSR_BCTC_2025_hop_nhat_kiem_toan",
    "SAB_BCTC_2025_hop_nhat_kiem_toan",
    "CTS_BCTC_2025_hop_nhat_kiem_toan",
]

QUEUE_FIELDS = [
    "source_file",
    "ground_truth_file",
    "sector",
    "selection_reason",
    "review_bucket",
    "note_id_normalized",
    "note_title",
    "block_id",
    "row_index",
    "row_source_line",
    "row_label",
    "row_code",
    "row_role",
    "row_unit",
    "current_raw",
    "current_normalized",
    "previous_raw",
    "previous_normalized",
    "values",
    "headers",
    "dimensions",
    "raw_cells",
    "verified_label",
    "verified_values",
    "verified_period_roles",
    "verified_unit",
    "verified_dimensions",
    "decision",
    "reviewer",
    "review_notes",
]


def bucket(row: dict[str, Any]) -> str:
    if not row.get("row_label"):
        return "empty_label"
    if row.get("block_form") == "table" and row.get("dimensions"):
        return "table_with_dimensions"
    if row.get("semantic_shape") in {"movement", "matrix", "aging", "reconciliation"}:
        return str(row.get("semantic_shape"))
    if row.get("value_count", 0) and int(row["value_count"]) >= 3:
        return "multi_value"
    if row.get("current_normalized") is not None and row.get("previous_normalized") is not None:
        return "current_previous"
    if row.get("current_normalized") is not None or row.get("previous_normalized") is not None:
        return "single_period"
    return "no_period_role"


def select_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(bucket(row), []).append(row)
    for values in grouped.values():
        values.sort(key=lambda item: (int(item.get("row_source_line") or 0), item.get("block_id") or ""))

    selected: list[dict[str, Any]] = []
    keys = sorted(grouped)
    while len(selected) < min(limit, len(rows)) and keys:
        progressed = False
        for key in keys:
            values = grouped[key]
            if values and len(selected) < limit:
                selected.append(values.pop(0))
                progressed = True
        if not progressed:
            break
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a stratified human-review queue for Notes ground truth.")
    parser.add_argument("--ground-truth", default="ground_truth/notes")
    parser.add_argument("--output", default="ground_truth/notes_review")
    parser.add_argument("--per-report", type=int, default=100)
    parser.add_argument("--reports", nargs="*", default=DEFAULT_REPORTS)
    args = parser.parse_args()

    gt_dir = Path(args.ground_truth)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    queue: list[dict[str, Any]] = []
    report_summary: list[dict[str, Any]] = []
    for stem in args.reports:
        gt_path = gt_dir / f"{stem}.notes.ground_truth.json"
        if not gt_path.exists():
            raise SystemExit(f"Ground truth file not found: {gt_path}")
        document = json.loads(gt_path.read_text(encoding="utf-8-sig"))
        selected = select_rows(document.get("rows") or [], args.per_report)
        reason = "; ".join(
            {
                "CTG_BCTC_2025_hop_nhat_kiem_toan": ["high_section_fragmentation", "bank"],
                "DIG_BCTC_2025_hop_nhat_kiem_toan": ["high_decoy_count", "enterprise"],
                "NVB_BCTC_2025_hop_nhat_kiem_toan": ["low_scope_confidence", "bank"],
                "DXS_BCTC_2025_hop_nhat_kiem_toan": ["low_scope_confidence", "enterprise"],
                "VCB_BCTC_2025_hop_nhat_kiem_toan": ["low_scope_confidence", "bank"],
                "ABB_BCTC_2025_hop_nhat_kiem_toan": ["bullet_ocr_target", "bank"],
                "ACB_BCTC_2025_hop_nhat_kiem_toan": ["matrix_target", "bank"],
                "ANV_BCTC_2025_hop_nhat_kiem_toan": ["bullet_ocr_target", "enterprise"],
                "GVR_BCTC_2025_hop_nhat_kiem_toan": ["largest_row_count", "enterprise"],
                "BSR_BCTC_2025_hop_nhat_kiem_toan": ["matrix_and_movement", "enterprise"],
                "SAB_BCTC_2025_hop_nhat_kiem_toan": ["matrix_and_large_rows", "enterprise"],
                "CTS_BCTC_2025_hop_nhat_kiem_toan": ["securities_sector", "securities"],
            }.get(stem, ["representative_sample", document.get("sector") or "unknown"])
        )
        for row in selected:
            item = {
                "source_file": document["source_file"],
                "ground_truth_file": gt_path.name,
                "sector": document.get("sector"),
                "selection_reason": reason,
                "review_bucket": bucket(row),
                **{field: row.get(field) for field in QUEUE_FIELDS[5:22]},
                "values": json.dumps(row.get("values") or [], ensure_ascii=False, separators=(",", ":")),
                "headers": json.dumps(row.get("headers") or [], ensure_ascii=False, separators=(",", ":")),
                "dimensions": json.dumps(row.get("dimensions") or [], ensure_ascii=False, separators=(",", ":")),
                "raw_cells": json.dumps(row.get("raw_cells") or [], ensure_ascii=False, separators=(",", ":")),
                "verified_label": "",
                "verified_values": "",
                "verified_period_roles": "",
                "verified_unit": "",
                "verified_dimensions": "",
                "decision": "",
                "reviewer": "",
                "review_notes": "",
            }
            queue.append(item)
        report_summary.append(
            {
                "source_file": document["source_file"],
                "available_rows": len(document.get("rows") or []),
                "selected_rows": len(selected),
                "selection_reason": reason,
            }
        )

    csv_path = output_dir / "review_queue.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(queue)

    json_path = output_dir / "review_queue.json"
    json_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "schema_version": "financial_notes_review_queue_v1",
        "purpose": "Human verification queue; not yet a verified gold standard.",
        "report_count": len(report_summary),
        "row_count": len(queue),
        "per_report_limit": args.per_report,
        "review_fields": QUEUE_FIELDS[-8:],
        "reports": report_summary,
        "files": {"csv": csv_path.name, "json": json_path.name},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key != "reports"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
