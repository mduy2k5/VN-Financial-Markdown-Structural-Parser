"""Build a specialized v3 candidate from repaired three-statement baselines.

This pass handles the three layouts that remain quarantined after the generic
baseline repair:

* SGB: labels are detached from a 20-row financial-position table;
* STB: the liability value block is shifted by one row relative to its labels;
* VBB: labels are detached from a seven-row financing cash-flow table.

The input directory is never used as an output directory.  The specialized
candidate is intentionally auditable and keeps the previous repair metadata.
The STB candidate is marked as requiring manual review because values are
re-associated with semantic rows using an independent note disclosure.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Allow direct execution from the repository root on Windows, where Python
# otherwise puts ``scripts/`` rather than the repository root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.repair_main_statement_baselines import _number


TOOL = "repair_specialized_main_statement_baselines_v1"
SCHEMA_VERSION = "financial_main_statement_baseline_specialized_repair_v1"
NUMBER_RE = r"\(?-?[\d][\d., ]*\)?"
PERIOD_VALUE_RE = {
    "current": re.compile(rf"31/12/2025\s*:\s*(?P<value>{NUMBER_RE})", re.I),
    "prior": re.compile(rf"31/12/2024\s*:\s*(?P<value>{NUMBER_RE})", re.I),
}

SGB_FILE = "SGB_BCTC_2025_hop_nhat_kiem_toan.md"
STB_FILE = "STB_BCTC_2025_hop_nhat_kiem_toan.md"
VBB_FILE = "VBB_BCTC_2025_hop_nhat_kiem_toan.md"


class SpecializedRepairError(RuntimeError):
    """Raised when a specialized layout does not match its expected evidence."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _clean_label(line: str) -> str:
    text = re.sub(r"^\s*(?:\*+\s*)+", "", line)
    text = re.sub(r"^\s*#+\s*", "", text)
    text = re.sub(r"[*_`]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _line(lines: list[str], number: int) -> str:
    if number < 1 or number > len(lines):
        return ""
    return lines[number - 1]


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_map(statement: dict[str, Any], source_lines: list[int]) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    wanted = set(source_lines)
    for row in statement.get("rows", []):
        try:
            source_line = int(row.get("source_line"))
        except (TypeError, ValueError):
            continue
        if source_line in wanted:
            if source_line in rows:
                raise SpecializedRepairError(f"duplicate baseline row source_line={source_line}")
            rows[source_line] = row
    missing = sorted(wanted - set(rows))
    if missing:
        raise SpecializedRepairError(f"baseline rows missing source lines: {missing}")
    return rows


def _set_label(
    row: dict[str, Any],
    label: str,
    *,
    label_source_line: int | None,
    rule: str,
    extra: dict[str, Any] | None = None,
) -> None:
    row["label"] = label
    row["label_path"] = [label] if label else []
    meta = {
        "tool": TOOL,
        "rule": rule,
        "row_source_line": row.get("source_line"),
        "label_source_line": label_source_line,
    }
    if label_source_line is not None:
        meta["label_source_text"] = extra.pop("label_source_text", None) if extra else None
    if extra:
        meta.update(extra)
    row["repair_meta"] = meta


def _refresh_statement_counts(document: dict[str, Any]) -> None:
    for statement in document.get("statements", {}).values():
        rows = statement.get("rows", [])
        statement["observation_count"] = sum(len(row.get("observations") or []) for row in rows)
        statement["unknown_period_count"] = sum(
            1
            for row in rows
            for observation in row.get("observations", [])
            if not observation.get("period_key")
        )


def _period_pair(line: str) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for period, pattern in PERIOD_VALUE_RE.items():
        match = pattern.search(line)
        result[period] = _number(match.group("value")) if match else None
    return result


def _observation_values(row: dict[str, Any]) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for observation in row.get("observations") or []:
        period = observation.get("period_key")
        if period in {"current", "prior"}:
            result[period] = observation.get("value")
    return result


def _sgb_labels_and_rows(source_lines: list[str]) -> tuple[list[tuple[int, str]], list[int], list[int]]:
    table_header = next(
        (index + 1 for index, value in enumerate(source_lines) if re.match(r"^\|\s*Thuyết minh", value, re.I)),
        None,
    )
    if table_header is None:
        raise SpecializedRepairError("SGB financial-position table header not found")

    statement_header = next(
        (
            index + 1
            for index in range(table_header - 1, 0, -1)
            if "CHỈ TIÊU" in _clean_label(source_lines[index - 1]).upper()
        ),
        None,
    )
    if statement_header is None:
        raise SpecializedRepairError("SGB statement label block anchor not found")

    labels: list[tuple[int, str]] = []
    excluded: list[int] = []
    for line_number in range(statement_header + 1, table_header):
        raw = _line(source_lines, line_number)
        label = _clean_label(raw)
        if not label:
            continue
        if "trong đó" in label.lower():
            excluded.append(line_number)
            continue
        if raw.lstrip().startswith("*") or label.upper() == "TỔNG TÀI SẢN CÓ":
            labels.append((line_number, label))

    data_lines: list[int] = []
    for line_number in range(table_header + 2, len(source_lines) + 1):
        if not _line(source_lines, line_number).lstrip().startswith("|"):
            break
        data_lines.append(line_number)

    if len(labels) != 20 or len(data_lines) != 20:
        raise SpecializedRepairError(
            f"SGB expected 20 labels/20 data rows, got {len(labels)}/{len(data_lines)}; excluded={excluded}"
        )
    if excluded != [508]:
        raise SpecializedRepairError(f"SGB unexpected non-tabular child labels: {excluded}")
    return labels, data_lines, excluded


def _repair_sgb(document: dict[str, Any], source_lines: list[str]) -> dict[str, Any]:
    statement = document.get("statements", {}).get("financial_position")
    if statement is None:
        raise SpecializedRepairError("SGB financial_position statement missing")
    labels, data_lines, excluded = _sgb_labels_and_rows(source_lines)
    rows = _row_map(statement, data_lines)
    changes: list[dict[str, Any]] = []
    for (label_line, label), data_line in zip(labels, data_lines):
        row = rows[data_line]
        old_label = row.get("label")
        _set_label(
            row,
            label,
            label_source_line=label_line,
            rule="align_detached_financial_position_label_block",
            extra={
                "label_source_text": _line(source_lines, label_line),
                "value_source_line": data_line,
                "old_label": old_label,
                "non_tabular_label_lines": excluded,
            },
        )
        changes.append({"row_id": row.get("row_id"), "source_line": data_line, "old_label": old_label, "label": label})
    return {
        "rules": Counter({"align_detached_financial_position_label_block": len(changes)}),
        "manual_review_required": False,
        "evidence": {
            "statement": "financial_position",
            "label_lines": [line for line, _ in labels],
            "value_lines": data_lines,
            "excluded_label_lines": excluded,
            "changes": changes,
        },
    }


def _vbb_labels(source_lines: list[str]) -> list[tuple[int, str]]:
    label_lines = [1042, 1043, 1044, 1045, 1047, 1049, 1051]
    labels = [(line_number, _clean_label(_line(source_lines, line_number))) for line_number in label_lines]
    if any(not label for _, label in labels):
        raise SpecializedRepairError(f"VBB has an empty specialized label: {labels}")
    if not _line(source_lines, 1054).lstrip().startswith("**Thuyết minh**"):
        raise SpecializedRepairError("VBB financing table header moved from expected source line")
    if _line(source_lines, 1056).strip() != "| | **Triệu đồng** | **Triệu đồng**":
        raise SpecializedRepairError("VBB unit row changed from expected layout")
    return labels


def _repair_vbb(document: dict[str, Any], source_lines: list[str]) -> dict[str, Any]:
    statement = document.get("statements", {}).get("cash_flow")
    if statement is None:
        raise SpecializedRepairError("VBB cash_flow statement missing")
    labels = _vbb_labels(source_lines)
    data_lines = list(range(1058, 1065))
    rows = _row_map(statement, [1056, *data_lines])

    unit_row = rows[1056]
    unit_row["row_type"] = "unit_header"
    unit_row["semantic_status"] = "not_a_statement_line"
    unit_row["repair_meta"] = {
        "tool": TOOL,
        "rule": "mark_unit_header_row",
        "row_source_line": 1056,
        "source_text": _line(source_lines, 1056),
    }

    changes: list[dict[str, Any]] = []
    note_sources = {1058 + 5: 1050, 1058 + 6: 1052}
    for (label_line, label), data_line in zip(labels, data_lines):
        row = rows[data_line]
        old_label = row.get("label")
        extra = {
            "label_source_text": _line(source_lines, label_line),
            "value_source_line": data_line,
            "old_label": old_label,
        }
        if data_line in note_sources:
            row["note"] = "30"
            extra["note_source_line"] = note_sources[data_line]
            extra["note_source_text"] = _line(source_lines, note_sources[data_line])
        _set_label(
            row,
            label,
            label_source_line=label_line,
            rule="align_detached_financing_cash_flow_label_block",
            extra=extra,
        )
        changes.append({"row_id": row.get("row_id"), "source_line": data_line, "old_label": old_label, "label": label})

    return {
        "rules": Counter(
            {
                "mark_unit_header_row": 1,
                "align_detached_financing_cash_flow_label_block": len(changes),
            }
        ),
        "manual_review_required": False,
        "evidence": {
            "statement": "cash_flow",
            "label_lines": [line for line, _ in labels],
            "value_lines": data_lines,
            "note_lines": [1050, 1052],
            "changes": changes,
        },
    }


def _detail_evidence(source_lines: list[str]) -> dict[str, dict[str, Any]]:
    evidence = {
        "deposit": {"label": "1. Tiền gửi của các tổ chức tín dụng khác", "lines": [4468, 4469]},
        "loan": {"label": "2. Vay các tổ chức tín dụng khác", "lines": [4480, 4481]},
        "total": {"label": "Tổng cộng Tiền gửi và vay các tổ chức tín dụng khác", "lines": [4484, 4485]},
    }
    for item in evidence.values():
        # The detail lines are one line per period, so normalize them below.
        current = _period_pair(_line(source_lines, item["lines"][0])).get("current")
        prior = _period_pair(_line(source_lines, item["lines"][1])).get("prior")
        if current is None or prior is None:
            raise SpecializedRepairError(f"STB detail evidence missing for {item['label']}")
        item["values"] = {"current": current, "prior": prior}
        item["texts"] = [_line(source_lines, line_number) for line_number in item["lines"]]
        item.pop("_unused", None)
    return evidence


def _repair_stb(document: dict[str, Any], source_lines: list[str]) -> dict[str, Any]:
    statement = document.get("statements", {}).get("financial_position")
    if statement is None:
        raise SpecializedRepairError("STB financial_position statement missing")
    source_row_lines = [529, 530, 531, 532]
    rows = _row_map(statement, source_row_lines)
    details = _detail_evidence(source_lines)

    assignments = [
        (529, "II. Tiền gửi và vay các tổ chức tín dụng khác", "16", "total", 530),
        (530, "1. Tiền gửi của các tổ chức tín dụng khác", None, "deposit", 531),
        (531, "2. Vay các tổ chức tín dụng khác", None, "loan", 532),
    ]
    changes: list[dict[str, Any]] = []
    for target_line, label, note, detail_key, value_line in assignments:
        target = rows[target_line]
        value_row = rows[value_line]
        old_label = target.get("label")
        old_observations = copy.deepcopy(target.get("observations") or [])
        observed = _observation_values(value_row)
        expected = details[detail_key]["values"]
        if observed != expected:
            raise SpecializedRepairError(
                f"STB table/detail mismatch for {detail_key}: table={observed}, detail={expected}"
            )
        target["observations"] = copy.deepcopy(value_row.get("observations") or [])
        target["note"] = note
        target["semantic_status"] = "reassociated_from_shifted_value_block"
        _set_label(
            target,
            label,
            label_source_line=target_line,
            rule="realign_shifted_liability_value_block",
            extra={
                "label_source_text": _line(source_lines, target_line),
                "value_source_line": value_line,
                "detail_evidence": {
                    "section": "16. Tiền gửi và vay các tổ chức tín dụng khác",
                    "role": detail_key,
                    "lines": details[detail_key]["lines"],
                    "values": details[detail_key]["values"],
                },
                "old_label": old_label,
                "old_observation_count": len(old_observations),
            },
        )
        changes.append(
            {
                "row_id": target.get("row_id"),
                "target_source_line": target_line,
                "value_source_line": value_line,
                "old_label": old_label,
                "label": label,
                "detail_role": detail_key,
            }
        )

    orphan = rows[532]
    orphan_raw = [
        {
            "source_line": observation.get("source_line"),
            "value_raw": observation.get("value_raw"),
            "raw_text": observation.get("raw_text"),
        }
        for observation in orphan.get("observations") or []
    ]
    orphan["label"] = ""
    orphan["label_path"] = []
    orphan["note"] = None
    orphan["observations"] = []
    orphan["row_type"] = "layout_placeholder"
    orphan["semantic_status"] = "consumed_by_specialized_realignment_requires_manual_review"
    orphan["repair_meta"] = {
        "tool": TOOL,
        "rule": "consume_shifted_value_row_as_layout_placeholder",
        "row_source_line": 532,
        "source_text": _line(source_lines, 532),
        "original_observations": orphan_raw,
        "consumed_by_row_id": rows[531].get("row_id"),
    }

    return {
        "rules": Counter(
            {
                "realign_shifted_liability_value_block": len(assignments),
                "consume_shifted_value_row_as_layout_placeholder": 1,
            }
        ),
        "manual_review_required": True,
        "evidence": {
            "statement": "financial_position",
            "table_lines": source_row_lines,
            "detail_section": "16. Tiền gửi và vay các tổ chức tín dụng khác",
            "detail_evidence": details,
            "changes": changes,
            "orphan_row_source_line": 532,
        },
    }


def specialize_document(document: dict[str, Any], source_lines: list[str]) -> dict[str, Any]:
    repaired = copy.deepcopy(document)
    source_file = Path(str(document.get("source_file") or "")).name
    result = {
        "rules": Counter(),
        "manual_review_required": False,
        "specialized": False,
        "evidence": {},
    }
    if source_file == SGB_FILE:
        result.update(_repair_sgb(repaired, source_lines))
        result["specialized"] = True
    elif source_file == STB_FILE:
        result.update(_repair_stb(repaired, source_lines))
        result["specialized"] = True
    elif source_file == VBB_FILE:
        result.update(_repair_vbb(repaired, source_lines))
        result["specialized"] = True
    else:
        result["rules"] = Counter()

    _refresh_statement_counts(repaired)
    repaired["repair_meta"] = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "input_baseline_schema": document.get("schema_version"),
        "source_file": source_file,
        "specialized": result["specialized"],
        "manual_review_required": result["manual_review_required"],
        "rules": dict(sorted(result["rules"].items())),
        "evidence": result["evidence"],
        "previous_repair_meta": document.get("repair_meta"),
    }
    return repaired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("ground_truth/main_statements_v2"))
    parser.add_argument("--source-dir", type=Path, default=Path("md_reports"))
    parser.add_argument("--output", type=Path, default=Path("ground_truth/main_statements_v3_specialized"))
    args = parser.parse_args()

    input_dir = args.input.resolve()
    output_dir = args.output.resolve()
    if input_dir == output_dir:
        raise SystemExit("Refusing to use the v3 output directory as the input directory")
    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")
    args.output.mkdir(parents=True, exist_ok=True)

    reports: list[dict[str, Any]] = []
    total = Counter()
    manual_review: list[str] = []
    for path in sorted(args.input.glob("*.baseline.json")):
        document = _load(path)
        source_path = args.source_dir / str(document.get("source_file") or "")
        if not source_path.exists():
            raise SystemExit(f"Source file missing for {path.name}: {source_path}")
        source_lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        repaired = specialize_document(document, source_lines)
        metadata = repaired["repair_meta"]
        total.update(metadata.get("rules") or {})
        if metadata.get("manual_review_required"):
            manual_review.append(path.name)
        output_path = args.output / path.name
        output_path.write_text(json.dumps(repaired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        reports.append(
            {
                "baseline": path.name,
                "source_file": document.get("source_file"),
                "source_sha256": document.get("source_sha256"),
                "source_hash_matches": _source_hash(source_path) == document.get("source_sha256"),
                "specialized": metadata.get("specialized", False),
                "manual_review_required": metadata.get("manual_review_required", False),
                "rules": metadata.get("rules", {}),
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "input_directory": str(args.input),
        "output_directory": str(args.output),
        "baseline_files": len(reports),
        "specialized_files": sum(bool(report["specialized"]) for report in reports),
        "source_hash_matches": sum(bool(report["source_hash_matches"]) for report in reports),
        "manual_review_required": manual_review,
        "rules": dict(sorted(total.items())),
        "reports": reports,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key != "reports"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
