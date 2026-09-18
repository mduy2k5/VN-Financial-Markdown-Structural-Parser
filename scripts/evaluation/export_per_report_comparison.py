"""Xuất bảng so sánh gọn theo report từ artifact đánh giá hiện có.

Exporter hoạt động theo dữ liệu: đọc danh sách report do comparator tạo và ghép
Notes theo ``source_file``. Lệnh không biết mã cổ phiếu, mẫu tên file hay số
report kỳ vọng.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


STATEMENTS = (
    ("financial_position", "B01"),
    ("income_statement", "B02"),
    ("cash_flow", "B03"),
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rate_percent(value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value) * 100:.2f}%"


def pair_cell(metrics: dict[str, Any]) -> str:
    expected = int(metrics.get("numeric_value_pairs") or 0)
    matched = int(metrics.get("numeric_value_pairs_matched") or 0)
    return f"{matched}/{expected} ({rate_percent(metrics.get('numeric_value_match_rate'))})"


def row_from_report(report: dict[str, Any], notes_by_source: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_file = str(report.get("source_file") or "")
    statements = report.get("statements") or {}
    rates = []
    row: dict[str, Any] = {
        "source_file": source_file,
        "ground_truth_file": report.get("ground_truth_file"),
        "source_hash": "OK" if report.get("source_hash_equal") else "MISMATCH",
        "raw_expected_values_found": "YES" if report.get("all_expected_values_found") else "NO",
    }
    for statement, short_name in STATEMENTS:
        metrics = statements.get(statement) or {}
        pair_rate = metrics.get("numeric_value_match_rate")
        value_rate = metrics.get("value_only_match_rate")
        row[f"{short_name}_pair"] = pair_cell(metrics)
        row[f"{short_name}_pair_rate"] = rate_percent(pair_rate)
        row[f"{short_name}_value_only"] = rate_percent(value_rate)
        row[f"{short_name}_missing_pairs"] = int(metrics.get("numeric_value_pairs_missing") or 0)
        if pair_rate is not None:
            rates.append(float(pair_rate))

    notes = notes_by_source.get(source_file)
    notes_ok = bool(notes and notes.get("value_rows_equal"))
    row["notes_values"] = "OK" if notes_ok else ("MISSING" if notes is None else "DIFF")
    row["notes_missing_rows"] = int((notes or {}).get("value_missing_rows") or 0)
    row["notes_unexpected_rows"] = int((notes or {}).get("value_unexpected_rows") or 0)
    row["min_pair_rate"] = rate_percent(min(rates) if rates else None)
    row["all_main_pairs_ge_90"] = "YES" if len(rates) == len(STATEMENTS) and all(rate >= 0.90 for rate in rates) else "NO"
    row["status"] = "PASS" if row["source_hash"] == "OK" and notes_ok and row["all_main_pairs_ge_90"] == "YES" else "REVIEW"
    return row


def markdown_table(rows: list[dict[str, Any]], mode: str) -> str:
    headers = [
        "File", "B01 kỳ + giá trị", "B02 kỳ + giá trị", "B03 kỳ + giá trị",
        "B01 value-only", "B02 value-only", "B03 value-only", "Notes giá trị",
        "Hash", "Min pair", "≥90% cả 3", "Trạng thái",
    ]
    lines = [
        f"# Kết quả đối chiếu theo từng file ({mode})",
        "",
        "Các ô kỳ + giá trị có dạng `matched/expected (rate)`. `value-only` chỉ kiểm tra tập giá trị số; `≥90% cả 3` yêu cầu numeric pair của cả B01/B02/B03 đạt ít nhất 90%.",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        values = [
            row["source_file"], row["B01_pair"], row["B02_pair"], row["B03_pair"],
            row["B01_value_only"], row["B02_value_only"], row["B03_value_only"],
            row["notes_values"], row["source_hash"], row["min_pair_rate"],
            row["all_main_pairs_ge_90"], row["status"],
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines.extend([
        "",
        f"Tổng số file: **{len(rows)}**.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--main-comparison",
        type=Path,
        default=Path("output/evaluations/comparison_main_statements_eligible.json"),
    )
    parser.add_argument(
        "--notes-comparison",
        type=Path,
        default=Path("output/evaluations/comparison_notes.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/evaluations/comparison_main_statements_per_report"),
        help="Output stem; .csv and .md are appended automatically.",
    )
    args = parser.parse_args()

    main_comparison = load_json(args.main_comparison)
    notes_comparison = load_json(args.notes_comparison)
    notes_by_source = {
        str(item.get("source_file")): item
        for item in (notes_comparison.get("files") or [])
    }
    rows = [
        row_from_report(report, notes_by_source)
        for report in (main_comparison.get("reports") or [])
    ]

    fields = [
        "source_file", "ground_truth_file", "source_hash", "raw_expected_values_found",
        "B01_pair", "B01_pair_rate", "B01_value_only", "B01_missing_pairs",
        "B02_pair", "B02_pair_rate", "B02_value_only", "B02_missing_pairs",
        "B03_pair", "B03_pair_rate", "B03_value_only", "B03_missing_pairs",
        "notes_values", "notes_missing_rows", "notes_unexpected_rows", "min_pair_rate",
        "all_main_pairs_ge_90", "status",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    csv_path = args.output.with_suffix(".csv")
    md_path = args.output.with_suffix(".md")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    mode = str(main_comparison.get("ground_truth_mode") or "unknown")
    md_path.write_text(markdown_table(rows, mode), encoding="utf-8")
    summary = {
        "source": str(args.main_comparison),
        "ground_truth_mode": mode,
        "reports": len(rows),
        "pass_reports": sum(row["status"] == "PASS" for row in rows),
        "review_reports": sum(row["status"] != "PASS" for row in rows),
        "csv": str(csv_path),
        "markdown": str(md_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
