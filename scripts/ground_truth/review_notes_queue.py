"""Kiểm tra từng item hàng đợi Notes với dòng Markdown nguồn được trích dẫn.

Lệnh tạo tập validation có evidence nguồn. Item không có evidence trực tiếp vẫn
được giữ rõ ràng trong hàng đợi để người dùng phân xử, không âm thầm nâng thành
gold data.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


def _fold(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[*_`#]+", "", text)
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _line(lines: list[str], number: Any) -> str:
    try:
        index = int(number) - 1
    except (TypeError, ValueError):
        return ""
    return lines[index] if 0 <= index < len(lines) else ""


def _nearby(lines: list[str], line_number: Any, radius: int = 8) -> str:
    try:
        index = int(line_number) - 1
    except (TypeError, ValueError):
        return ""
    return "\n".join(lines[max(0, index - radius): min(len(lines), index + radius + 1)])


def _contains(haystack: str, needle: Any) -> bool:
    folded = _fold(needle)
    return bool(folded) and folded in _fold(haystack)


def review_item(item: dict[str, Any], source_dir: Path) -> dict[str, Any]:
    result = dict(item)
    source_path = source_dir / str(item["source_file"])
    if not source_path.exists():
        result.update(
            decision="needs_manual_review",
            reviewer="source_audit_v1",
            review_notes=f"Source not found: {source_path}",
        )
        return result

    lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    row_line = _line(lines, item.get("row_source_line"))
    values = json.loads(item.get("values") or "[]")
    label = item.get("row_label") or ""
    label_ok = not label or _contains(row_line, label)
    value_results: list[dict[str, Any]] = []
    for value in values:
        value_line = _line(lines, value.get("source_line"))
        raw = str(value.get("raw") or "")
        value_results.append(
            {
                "raw": raw,
                "source_line": value.get("source_line"),
                "matched": bool(raw) and raw in value_line,
                "period_role": value.get("period_role"),
            }
        )
    values_ok = bool(value_results) and all(entry["matched"] for entry in value_results)
    period_labels = [value.get("period_label") for value in values if value.get("period_label")]
    context = _nearby(lines, item.get("row_source_line"))
    periods_supported = all(_contains(context, period) for period in period_labels)

    evidence = {
        "row_source_line": item.get("row_source_line"),
        "row_source_text": row_line,
        "label_matched": label_ok,
        "values": value_results,
        "period_labels_supported_nearby": periods_supported,
    }
    result["verified_label"] = label if label_ok else ""
    result["verified_values"] = json.dumps(value_results, ensure_ascii=False, separators=(",", ":"))
    result["verified_period_roles"] = "source_context" if periods_supported else "needs_human_check"
    result["verified_unit"] = str(item.get("row_unit") or "")
    result["verified_dimensions"] = str(item.get("dimensions") or "[]")
    result["reviewer"] = "source_audit_v1"
    result["source_evidence"] = evidence
    if not label:
        result["decision"] = "excluded_from_gold_unlabeled_row"
        result["review_notes"] = "Values are source-evidenced, but the source row has no semantic label."
    elif label_ok and values_ok:
        result["decision"] = "accepted_source_evidence"
        result["review_notes"] = "Label and every extracted raw value match their cited source lines."
    else:
        missing = []
        if not label_ok:
            missing.append("label")
        if not values_ok:
            missing.append("value")
        result["decision"] = "needs_manual_review"
        result["review_notes"] = "No direct source evidence for: " + ", ".join(missing) + "."
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=Path("ground_truth/notes_review/review_queue.json"))
    parser.add_argument("--source-dir", type=Path, default=Path("md_reports"))
    parser.add_argument("--output", type=Path, default=Path("ground_truth/notes_gold"))
    args = parser.parse_args()

    queue = json.loads(args.queue.read_text(encoding="utf-8-sig"))
    reviewed = [review_item(item, args.source_dir) for item in queue]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "reviewed_queue.json").write_text(
        json.dumps(reviewed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = list(queue[0]) + ["source_evidence"]
    with (args.output / "reviewed_queue.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in reviewed:
            row = dict(item)
            row["source_evidence"] = json.dumps(item.get("source_evidence", {}), ensure_ascii=False)
            writer.writerow(row)
    decisions = Counter(item["decision"] for item in reviewed)
    gold_items = [item for item in reviewed if item["decision"] == "accepted_source_evidence"]
    (args.output / "gold_standard.json").write_text(
        json.dumps(gold_items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "financial_notes_source_review_v1",
        "purpose": "Source-evidenced gold validation subset; excluded rows are retained in the review ledger.",
        "queue_items": len(reviewed),
        "decisions": dict(sorted(decisions.items())),
        "gold_standard_items": len(gold_items),
        "files": {
            "json": "reviewed_queue.json",
            "csv": "reviewed_queue.csv",
            "gold_standard": "gold_standard.json",
        },
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
