"""Sửa lệch cột/kỳ không mơ hồ trong baseline ba báo cáo đã lưu.

Không ghi đè file baseline gốc. Bản sửa được chép sang thư mục mới và mang rule
theo từng dòng để mọi thay đổi vẫn audit được.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


NUMBER_RE = r"\(?-?[\d][\d., ]*\)?"
PERIOD_INLINE_RE = {
    "current": re.compile(rf"năm\s*nay\s*:\s*(?P<value>{NUMBER_RE})", re.I),
    "prior": re.compile(rf"năm\s*trước\s*:\s*(?P<value>{NUMBER_RE})", re.I),
}
PERIOD_SUFFIX_RE = {
    "current": re.compile(rf"(?P<value>{NUMBER_RE})\s*(?:triệu\s*đồng|triệu\s*vnd|đồng|vnd)?\s*\(\s*năm\s*nay\s*\)", re.I),
    "prior": re.compile(rf"(?P<value>{NUMBER_RE})\s*(?:triệu\s*đồng|triệu\s*vnd|đồng|vnd)?\s*\(\s*năm\s*trước\s*\)", re.I),
}
NOTE_REF_RE = re.compile(r"^(?:[IVXLCDM]+\.\s*[A-Za-z0-9.,()]+|\d{1,3}(?:\.\d{1,2})?)$", re.I)
CODE_RE = re.compile(r"^\d{1,4}[A-Za-z]?$", re.I)
NUMERIC_LABEL_RE = re.compile(r"^\(?-?\d[\d., ]*\)?$")


def _strip(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"[*_`]+", "", text).strip()


def _number(value: Any):
    text = _strip(value).replace("−", "-").replace(" ", "")
    if not text or text in {"-", "–", "—", "..."}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", text):
        result = int(text.replace(".", ""))
    elif re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", text):
        result = int(text.replace(",", ""))
    elif re.fullmatch(r"-?\d+", text):
        result = int(text)
    else:
        return None
    return -abs(result) if negative else result


def _cells(raw_text: str) -> list[str]:
    if "|" not in raw_text:
        return []
    cells = [_strip(cell).strip("|") for cell in raw_text.split("|")]
    if raw_text.strip().startswith("|") and cells:
        cells = cells[1:]
    if raw_text.strip().endswith("|") and cells:
        cells = cells[:-1]
    return cells


def _value_observation(value: Any, period: str, old: dict, raw_text: str) -> dict:
    obs = copy.deepcopy(old)
    obs["period_key"] = "current" if period == "current" else "prior"
    obs["period_raw"] = "Năm nay" if period == "current" else "Năm trước"
    obs["value_raw"] = _strip(value)
    obs["value"] = _number(value)
    obs["raw_text"] = raw_text
    return obs


def _repair_inline(row: dict) -> str | None:
    observations = row.get("observations") or []
    if len(observations) >= 2:
        return None
    raw_text = str((observations[0] if observations else {}).get("raw_text") or "")
    if not raw_text:
        return None
    values = {}
    for period, pattern in PERIOD_INLINE_RE.items():
        match = pattern.search(raw_text)
        if match:
            values[period] = match.group("value")
    if len(values) < 2:
        for period, pattern in PERIOD_SUFFIX_RE.items():
            match = pattern.search(raw_text)
            if match:
                values[period] = match.group("value")
    if len(values) < 2:
        return None
    old_by_period = {obs.get("period_key"): obs for obs in row.get("observations") or []}
    fallback = next(iter(row.get("observations") or [{}]), {})
    row["observations"] = [
        _value_observation(values["current"], "current", old_by_period.get("current") or fallback, raw_text),
        _value_observation(values["prior"], "prior", old_by_period.get("prior") or fallback, raw_text),
    ]
    return "expand_inline_current_prior_pair"


def _repair_table_row(row: dict, source_line: str = "") -> str | None:
    observations = row.get("observations") or []
    raw_text = str((observations[0] if observations else {}).get("raw_text") or source_line)
    cells = _cells(raw_text)
    if len(cells) < 2:
        return None

    if not NUMERIC_LABEL_RE.fullmatch(_strip(row.get("label") or "")):
        return None

    # Dòng heading như ``I. ... | 15 | |`` có nhãn và tham chiếu thuyết minh
    # nhưng không có observation tài chính. Khôi phục các field đó mà không tự
    # tạo giá trị.
    if (
        len(cells) >= 3
        and cells[0]
        and _number(cells[0]) is None
        and cells[1]
        and _number(cells[1]) is not None
        and all(not cell for cell in cells[2:])
    ):
        row["label"] = cells[0]
        row["label_path"] = [cells[0]]
        row["note"] = cells[1]
        return "restore_heading_label_and_note_columns"

    # Chỉ dùng hai ô cuối khi cả hai là số/gạch. Cách này tránh xem tham chiếu
    # thuyết minh hoặc mã là observation tài chính.
    if len(cells) >= 3 and not all(_number(cell) is not None or cell in {"", "-", "–", "—"} for cell in cells[-2:]):
        return None
    final_values = cells[-2:] if len(cells) >= 3 else []
    has_two_values = len(final_values) == 2 and any(_number(cell) is not None for cell in final_values)
    if not has_two_values:
        return None

    first = cells[0] if cells else ""
    second = cells[1] if len(cells) > 1 else ""
    old_label = _strip(row.get("label") or "")
    old_note = _strip(row.get("note") or "")
    new_label = None
    new_note = None
    new_code = row.get("code")
    rule = None

    if CODE_RE.fullmatch(first) and second and not (_number(second) is not None):
        # Mã | nhãn | hiện tại | trước đây
        new_code = first
        new_label = second
        rule = "split_code_label_value_columns"
    elif first and _number(first) is None and not NOTE_REF_RE.fullmatch(first):
        # Nhãn | hiện tại | trước đây, hoặc Nhãn | tham chiếu thuyết minh | hiện tại | trước đây
        new_label = first
        if len(cells) >= 4 and second and (_number(second) is None):
            new_note = second
        rule = "shift_label_before_value_columns"
    elif first and NOTE_REF_RE.fullmatch(first):
        # Tham chiếu thuyết minh | hiện tại | trước đây, không có nhãn semantic trong dòng OCR này.
        new_label = ""
        new_note = first
        rule = "preserve_note_reference_without_promoting_value_to_label"
    elif not first:
        # Nhãn trống | hiện tại | trước đây là dòng tiếp nối/tổng không có nhãn.
        new_label = ""
        new_note = old_note or None
        rule = "preserve_unlabeled_value_row"

    if rule is None:
        return None

    old_obs = observations or [{}]
    row["label"] = new_label
    row["label_path"] = [new_label] if new_label else []
    row["note"] = new_note
    row["code"] = new_code
    row["observations"] = [
        _value_observation(final_values[0], "current", old_obs[0], raw_text),
        _value_observation(final_values[1], "prior", old_obs[-1], raw_text),
    ]
    return rule


def repair_baseline(document: dict, source_lines: list[str] | None = None) -> dict:
    repaired = copy.deepcopy(document)
    rules = Counter()
    for statement in repaired.get("statements", {}).values():
        for row in statement.get("rows", []):
            rule = _repair_inline(row)
            if rule is None:
                source_line = ""
                if source_lines:
                    try:
                        source_line = source_lines[int(row.get("source_line")) - 1]
                    except (TypeError, ValueError, IndexError):
                        source_line = ""
                rule = _repair_table_row(row, source_line)
            if rule:
                rules[rule] += 1
                row["repair_meta"] = {
                    "tool": "repair_main_statement_baselines_v1",
                    "rule": rule,
                    "source_line": row.get("source_line"),
                }
        statement["observation_count"] = sum(len(row.get("observations") or []) for row in statement.get("rows", []))
        statement["unknown_period_count"] = sum(
            1 for row in statement.get("rows", []) for obs in row.get("observations", [])
            if not obs.get("period_key")
        )
    repaired["repair_meta"] = {
        "tool": "repair_main_statement_baselines_v1",
        "source_baseline_schema": document.get("schema_version"),
        "rules": dict(sorted(rules.items())),
    }
    return repaired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("ground_truth/main_statements"))
    parser.add_argument("--source-dir", type=Path, default=Path("md_reports"))
    parser.add_argument("--output", type=Path, default=Path("ground_truth/main_statements_v2"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    total = Counter()
    for path in sorted(args.input.glob("*.baseline.json")):
        document = _load(path)
        source_path = args.source_dir / document.get("source_file", "")
        source_lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if source_path.exists() else None
        repaired = repair_baseline(document, source_lines)
        total.update((repaired.get("repair_meta") or {}).get("rules", {}))
        (args.output / path.name).write_text(json.dumps(repaired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "financial_main_statement_baseline_repair_v1",
        "source_directory": str(args.input),
        "output_directory": str(args.output),
        "files": len(list(args.output.glob("*.baseline.json"))),
        "rules": dict(sorted(total.items())),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
