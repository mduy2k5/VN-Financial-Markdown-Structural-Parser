"""Audit the specialized v3 three-statement baseline candidate.

The generic baseline audit checks source hashes, observation provenance, and
basic label/value shifts.  This audit adds semantic gates for the three
specialized layouts repaired in v3.  It intentionally keeps STB quarantined:
its values are numerically verified against note 16, but their reassociation
across table rows still requires manual/PDF confirmation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Allow direct execution from the repository root on Windows.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_main_statement_baselines import audit_file
from scripts.repair_main_statement_baselines import _number, _strip


NUMBER_RE = r"\(?-?[\d][\d., ]*\)?"
DASHES = {"-", "–", "—", "..."}
PERIOD_VALUE_RE = {
    "current": re.compile(rf"31/12/2025\s*:\s*(?P<value>{NUMBER_RE})", re.I),
    "prior": re.compile(rf"31/12/2024\s*:\s*(?P<value>{NUMBER_RE})", re.I),
}

SGB_FILE = "SGB_BCTC_2025_hop_nhat_kiem_toan.md"
STB_FILE = "STB_BCTC_2025_hop_nhat_kiem_toan.md"
VBB_FILE = "VBB_BCTC_2025_hop_nhat_kiem_toan.md"

SGB_LABELS = dict(
    zip(
        range(515, 535),
        [
            "X. Tài sản cố định",
            "1. Tài sản cố định hữu hình",
            "Nguyên giá tài sản cố định hữu hình",
            "Hao mòn tài sản cố định hữu hình",
            "2. Tài sản cố định thuê tài chính",
            "Nguyên giá tài sản cố định thuê tài chính",
            "Hao mòn tài sản cố định thuê tài chính",
            "3. Tài sản cố định vô hình",
            "Nguyên giá tài sản cố định vô hình",
            "Hao mòn tài sản cố định vô hình",
            "XI. Bất động sản đầu tư",
            "Nguyên giá bất động sản đầu tư",
            "Hao mòn bất động sản đầu tư",
            "XII. Tài sản có khác",
            "1. Các khoản phải thu",
            "2. Các khoản lãi, phí phải thu",
            "3. Tài sản thuế TNDN hoãn lại",
            "4. Tài sản Có khác",
            "5. Các khoản dự phòng rủi ro cho các tài sản Có nội bảng khác",
            "TỔNG TÀI SẢN CÓ",
        ],
    )
)

STB_LABELS = {
    529: "II. Tiền gửi và vay các tổ chức tín dụng khác",
    530: "1. Tiền gửi của các tổ chức tín dụng khác",
    531: "2. Vay các tổ chức tín dụng khác",
}

VBB_LABELS = {
    1058: "Tăng vốn cổ phần từ góp vốn và/hoặc phát hành cổ phiếu",
    1059: "Tiền thu từ phát hành giấy tờ có giá dài hạn có đủ điều kiện tính vào vốn tự có và các khoản vốn vay dài hạn khác",
    1060: "Tiền chi thanh toán giấy tờ có giá dài hạn có đủ điều kiện tính vào vốn tự có và các khoản vốn vay dài hạn khác",
    1061: "Lưu chuyển tiền thuần từ hoạt động tài chính",
    1062: "Lưu chuyển tiền thuần trong năm",
    1063: "Tiền và các khoản tương đương tiền - đầu năm",
    1064: "Tiền và các khoản tương đương tiền cuối năm",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _line(lines: list[str], number: int) -> str:
    return lines[number - 1] if 1 <= number <= len(lines) else ""


def _cells(raw_text: str) -> list[str]:
    if "|" not in raw_text:
        return []
    cells = [_strip(cell).strip("|") for cell in raw_text.split("|")]
    if raw_text.strip().startswith("|") and cells:
        cells = cells[1:]
    if raw_text.strip().endswith("|") and cells:
        cells = cells[:-1]
    return cells


def _table_pair(lines: list[str], source_line: Any) -> dict[str, int | None]:
    try:
        raw_text = _line(lines, int(source_line))
    except (TypeError, ValueError):
        raw_text = ""
    cells = _cells(raw_text)
    result: dict[str, int | None] = {"current": None, "prior": None}
    if len(cells) < 2:
        return result
    for period, cell in zip(("current", "prior"), cells[-2:]):
        value = _number(cell)
        if value is not None:
            result[period] = value
        elif _strip(cell) in DASHES:
            # This is only a validation convention.  Baseline values remain
            # null for an explicit dash and are never rewritten to numeric 0.
            result[period] = 0
    return result


def _row_values(row: dict[str, Any], source_lines: list[str]) -> dict[str, int | None]:
    result: dict[str, int | None] = {"current": None, "prior": None}
    for observation in row.get("observations") or []:
        period = observation.get("period_key")
        if period in result and observation.get("value") is not None:
            result[period] = observation.get("value")
    fallback = _table_pair(source_lines, row.get("source_line"))
    for period in result:
        if result[period] is None:
            result[period] = fallback[period]
    return result


def _observation_count(row: dict[str, Any]) -> int:
    return len(row.get("observations") or [])


def _rows_by_source(statement: dict[str, Any], source_lines: list[int]) -> dict[int, dict[str, Any]]:
    wanted = set(source_lines)
    result: dict[int, dict[str, Any]] = {}
    for row in statement.get("rows", []):
        try:
            number = int(row.get("source_line"))
        except (TypeError, ValueError):
            continue
        if number in wanted and number not in result:
            result[number] = row
    return result


def _period_pair(lines: list[str], source_lines: list[int]) -> dict[str, int | None]:
    result: dict[str, int | None] = {"current": None, "prior": None}
    for period, source_line in zip(("current", "prior"), source_lines):
        match = PERIOD_VALUE_RE[period].search(_line(lines, source_line))
        if match:
            result[period] = _number(match.group("value"))
    return result


def _add_issue(
    report: dict[str, Any],
    issues: list[dict[str, Any]],
    path: Path,
    baseline: dict[str, Any],
    *,
    statement: str | None,
    row: dict[str, Any] | None,
    severity: str,
    issue: str,
    check: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    row = row or {}
    item = {
        "baseline": path.name,
        "source_file": baseline.get("source_file"),
        "statement": statement,
        "row_id": row.get("row_id"),
        "source_line": row.get("source_line"),
        "label": str(row.get("label") or ""),
        "note": str(row.get("note") or ""),
        "observation_count": _observation_count(row),
        "severity": severity,
        "issue": issue,
        "check": check,
        "evidence": json.dumps(evidence or {}, ensure_ascii=False, sort_keys=True),
    }
    issues.append(item)
    counts = Counter(report.get("issues") or {})
    counts[issue] += 1
    report["issues"] = dict(sorted(counts.items()))


def _check_equation(
    report: dict[str, Any],
    issues: list[dict[str, Any]],
    path: Path,
    baseline: dict[str, Any],
    *,
    statement_name: str,
    rows: dict[int, dict[str, Any]],
    target_line: int,
    component_lines: list[int],
    source_lines: list[str],
    check: str,
) -> bool:
    passed = True
    target_values = _row_values(rows[target_line], source_lines)
    component_values = [_row_values(rows[line], source_lines) for line in component_lines]
    for period in ("current", "prior"):
        values = [target_values[period], *(item[period] for item in component_values)]
        if any(value is None for value in values):
            passed = False
            _add_issue(
                report,
                issues,
                path,
                baseline,
                statement=statement_name,
                row=rows[target_line],
                severity="error",
                issue=f"{check}_unverifiable",
                check=check,
                evidence={"period": period, "values": values, "component_lines": component_lines},
            )
            continue
        expected = sum(value for value in values[1:] if value is not None)
        if values[0] != expected:
            passed = False
            _add_issue(
                report,
                issues,
                path,
                baseline,
                statement=statement_name,
                row=rows[target_line],
                severity="error",
                issue=f"{check}_mismatch",
                check=check,
                evidence={
                    "period": period,
                    "target": values[0],
                    "components": values[1:],
                    "expected": expected,
                    "component_lines": component_lines,
                },
            )
    return passed


def _audit_sgb(path: Path, baseline: dict[str, Any], source_lines: list[str], report: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    statement_name = "financial_position"
    statement = baseline.get("statements", {}).get(statement_name, {})
    rows = _rows_by_source(statement, list(SGB_LABELS))
    checks: dict[str, bool] = {}

    labels_ok = len(rows) == len(SGB_LABELS) and all(
        rows[line].get("label") == label for line, label in SGB_LABELS.items() if line in rows
    )
    checks["label_block_alignment"] = labels_ok
    if not labels_ok:
        _add_issue(
            report,
            issues,
            path,
            baseline,
            statement=statement_name,
            row=None,
            severity="error",
            issue="sgb_label_block_alignment_failed",
            check="label_block_alignment",
            evidence={"expected": SGB_LABELS, "actual": {line: rows[line].get("label") for line in rows}},
        )

    metadata_evidence = ((baseline.get("repair_meta") or {}).get("evidence") or {})
    excluded = metadata_evidence.get("excluded_label_lines")
    checks["non_tabular_child_excluded"] = excluded == [508]
    if not checks["non_tabular_child_excluded"]:
        _add_issue(
            report,
            issues,
            path,
            baseline,
            statement=statement_name,
            row=None,
            severity="error",
            issue="sgb_non_tabular_child_alignment_failed",
            check="non_tabular_child_excluded",
            evidence={"expected": [508], "actual": excluded},
        )

    if len(rows) == len(SGB_LABELS):
        checks["fixed_asset_total"] = _check_equation(
            report,
            issues,
            path,
            baseline,
            statement_name=statement_name,
            rows=rows,
            target_line=515,
            component_lines=[516, 522],
            source_lines=source_lines,
            check="sgb_fixed_asset_total",
        )
        checks["tangible_fixed_asset_net"] = _check_equation(
            report,
            issues,
            path,
            baseline,
            statement_name=statement_name,
            rows=rows,
            target_line=516,
            component_lines=[517, 518],
            source_lines=source_lines,
            check="sgb_tangible_fixed_asset_net",
        )
        checks["intangible_fixed_asset_net"] = _check_equation(
            report,
            issues,
            path,
            baseline,
            statement_name=statement_name,
            rows=rows,
            target_line=522,
            component_lines=[523, 524],
            source_lines=source_lines,
            check="sgb_intangible_fixed_asset_net",
        )
        checks["other_asset_total"] = _check_equation(
            report,
            issues,
            path,
            baseline,
            statement_name=statement_name,
            rows=rows,
            target_line=528,
            component_lines=[529, 530, 531, 532, 533],
            source_lines=source_lines,
            check="sgb_other_asset_total",
        )
    else:
        for check in ("fixed_asset_total", "tangible_fixed_asset_net", "intangible_fixed_asset_net", "other_asset_total"):
            checks[check] = False

    return checks


def _audit_stb(path: Path, baseline: dict[str, Any], source_lines: list[str], report: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    statement_name = "financial_position"
    statement = baseline.get("statements", {}).get(statement_name, {})
    rows = _rows_by_source(statement, [529, 530, 531, 532])
    checks: dict[str, bool] = {}

    labels_ok = len(rows) == 4 and all(rows[line].get("label") == label for line, label in STB_LABELS.items())
    checks["semantic_labels"] = labels_ok
    if not labels_ok:
        _add_issue(
            report,
            issues,
            path,
            baseline,
            statement=statement_name,
            row=None,
            severity="error",
            issue="stb_semantic_labels_failed",
            check="semantic_labels",
            evidence={"expected": STB_LABELS, "actual": {line: rows[line].get("label") for line in rows}},
        )

    placeholder = rows.get(532)
    placeholder_ok = bool(
        placeholder
        and placeholder.get("row_type") == "layout_placeholder"
        and not any(observation.get("value") is not None for observation in placeholder.get("observations") or [])
    )
    checks["no_orphan_numeric_row"] = placeholder_ok
    if not placeholder_ok:
        _add_issue(
            report,
            issues,
            path,
            baseline,
            statement=statement_name,
            row=placeholder,
            severity="error",
            issue="orphan_numeric_row",
            check="no_orphan_numeric_row",
            evidence={"expected_row_type": "layout_placeholder"},
        )

    detail_specs = {
        "total": (529, [4484, 4485]),
        "deposit": (530, [4468, 4469]),
        "loan": (531, [4480, 4481]),
    }
    detail_checks: dict[str, bool] = {}
    for role, (target_line, detail_lines) in detail_specs.items():
        target_values = _row_values(rows[target_line], source_lines) if target_line in rows else {"current": None, "prior": None}
        detail_values = _period_pair(source_lines, detail_lines)
        passed = target_values == detail_values
        detail_checks[role] = passed
        if not passed:
            _add_issue(
                report,
                issues,
                path,
                baseline,
                statement=statement_name,
                row=rows.get(target_line),
                severity="error",
                issue="stb_detail_value_mismatch",
                check=f"detail_value_{role}",
                evidence={"role": role, "target": target_values, "detail": detail_values, "detail_lines": detail_lines},
            )
    checks["detail_values"] = all(detail_checks.values())

    if len(rows) == 4:
        checks["deposit_plus_loan_equals_total"] = _check_equation(
            report,
            issues,
            path,
            baseline,
            statement_name=statement_name,
            rows=rows,
            target_line=529,
            component_lines=[530, 531],
            source_lines=source_lines,
            check="stb_deposit_plus_loan_total",
        )
    else:
        checks["deposit_plus_loan_equals_total"] = False

    manual_required = bool((baseline.get("repair_meta") or {}).get("manual_review_required"))
    checks["manual_review_complete"] = not manual_required
    if manual_required:
        _add_issue(
            report,
            issues,
            path,
            baseline,
            statement=statement_name,
            row=rows.get(529),
            severity="warning",
            issue="manual_review_required",
            check="manual_review_complete",
            evidence={
                "reason": "values were reassociated across a shifted table block",
                "required_action": "confirm against the source PDF/table layout",
            },
        )
    return checks


def _audit_vbb(path: Path, baseline: dict[str, Any], source_lines: list[str], report: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    statement_name = "cash_flow"
    statement = baseline.get("statements", {}).get(statement_name, {})
    required_lines = [1056, *range(1058, 1065), 988, 1003]
    rows = _rows_by_source(statement, required_lines)
    checks: dict[str, bool] = {}

    table_complete = all(line in rows for line in required_lines)
    labels_ok = table_complete and all(rows[line].get("label") == label for line, label in VBB_LABELS.items())
    checks["label_block_alignment"] = labels_ok
    if not labels_ok:
        _add_issue(
            report,
            issues,
            path,
            baseline,
            statement=statement_name,
            row=None,
            severity="error",
            issue="vbb_label_block_alignment_failed",
            check="label_block_alignment",
            evidence={"expected": VBB_LABELS, "actual": {line: rows[line].get("label") for line in rows if line in VBB_LABELS}},
        )

    unit_header = rows.get(1056)
    checks["unit_header_marked"] = bool(unit_header and unit_header.get("row_type") == "unit_header")
    if not checks["unit_header_marked"]:
        _add_issue(
            report,
            issues,
            path,
            baseline,
            statement=statement_name,
            row=unit_header,
            severity="error",
            issue="vbb_unit_header_not_marked",
            check="unit_header_marked",
        )

    note_ok = bool(rows.get(1063) and rows[1063].get("note") == "30" and rows.get(1064) and rows[1064].get("note") == "30")
    checks["cash_balance_note_refs"] = note_ok
    if not note_ok:
        _add_issue(
            report,
            issues,
            path,
            baseline,
            statement=statement_name,
            row=rows.get(1063),
            severity="error",
            issue="vbb_cash_balance_note_ref_missing",
            check="cash_balance_note_refs",
            evidence={"expected_note": "30"},
        )

    if table_complete:
        checks["financing_cash_flow_total"] = _check_equation(
            report,
            issues,
            path,
            baseline,
            statement_name=statement_name,
            rows=rows,
            target_line=1061,
            component_lines=[1058, 1059, 1060],
            source_lines=source_lines,
            check="vbb_financing_cash_flow_total",
        )
        # The operating and investing totals occur earlier in the same cash
        # flow statement; the financing block is the continuation table.
        checks["annual_cash_change"] = _check_equation(
            report,
            issues,
            path,
            baseline,
            statement_name=statement_name,
            rows=rows,
            target_line=1062,
            component_lines=[988, 1003, 1061],
            source_lines=source_lines,
            check="vbb_annual_cash_change",
        )
        checks["closing_cash_balance"] = _check_equation(
            report,
            issues,
            path,
            baseline,
            statement_name=statement_name,
            rows=rows,
            target_line=1064,
            component_lines=[1063, 1062],
            source_lines=source_lines,
            check="vbb_closing_cash_balance",
        )
    else:
        for check in ("financing_cash_flow_total", "annual_cash_change", "closing_cash_balance"):
            checks[check] = False
    return checks


def _specialized_audit(path: Path, baseline: dict[str, Any], source_lines: list[str], report: dict[str, Any], issues: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    source_file = Path(str(baseline.get("source_file") or "")).name
    if source_file == SGB_FILE:
        checks = _audit_sgb(path, baseline, source_lines, report, issues)
        status = "passed" if all(checks.values()) else "failed"
    elif source_file == STB_FILE:
        checks = _audit_stb(path, baseline, source_lines, report, issues)
        status = "needs_manual_review" if all(value for key, value in checks.items() if key != "manual_review_complete") else "failed"
    elif source_file == VBB_FILE:
        checks = _audit_vbb(path, baseline, source_lines, report, issues)
        status = "passed" if all(checks.values()) else "failed"
    else:
        checks = {}
        status = "not_applicable"
    return checks, status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baselines", type=Path, default=Path("ground_truth/main_statements_v3_specialized"))
    parser.add_argument("--source-dir", type=Path, default=Path("md_reports"))
    parser.add_argument("--output", type=Path, default=Path("ground_truth/main_statements_v3_specialized_audit"))
    args = parser.parse_args()

    reports: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for path in sorted(args.baselines.glob("*.baseline.json")):
        baseline = _load(path)
        source_path = args.source_dir / str(baseline.get("source_file") or "")
        if source_path.exists():
            source_lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        else:
            source_lines = []
        report, generic_issues = audit_file(path, args.source_dir)
        issues.extend(generic_issues)
        checks, status = _specialized_audit(path, baseline, source_lines, report, issues)
        report["specialized_checks"] = checks
        report["specialized_status"] = status
        report["can_unquarantine"] = bool(report.get("source_hash_matches")) and not bool(report.get("issues"))
        reports.append(report)

    issue_counts = Counter(item["issue"] for item in issues)
    eligible = [report["baseline"] for report in reports if report.get("can_unquarantine")]
    quarantined = [report["baseline"] for report in reports if not report.get("can_unquarantine")]
    manifest = {
        "schema_version": "financial_main_statement_baseline_specialized_audit_v1",
        "baseline_directory": str(args.baselines),
        "source_directory": str(args.source_dir),
        "baseline_files": len(reports),
        "source_hash_matches": sum(bool(report.get("source_hash_matches")) for report in reports),
        "issues": dict(sorted(issue_counts.items())),
        "specialized_status": dict(sorted(Counter(report.get("specialized_status") for report in reports).items())),
        "eligible_for_linking": eligible,
        "quarantined": quarantined,
        "reports": reports,
        "files": {"issues": "issues.csv"},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audit.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = [
        "baseline",
        "source_file",
        "statement",
        "row_id",
        "source_line",
        "label",
        "note",
        "observation_count",
        "severity",
        "issue",
        "check",
        "evidence",
    ]
    with (args.output / "issues.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(issues)
    print(json.dumps({key: value for key, value in manifest.items() if key != "reports"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
