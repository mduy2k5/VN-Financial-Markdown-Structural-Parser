"""Build a per-report production quality evaluation.

The report combines three independent signals:

* production coverage from the batch comparison artifacts;
* normalized ``period + value`` evidence match against the repaired observation
  baseline (eligible mode);
* parser/gate diagnostics such as conflicts, unresolved rows and formula
  failures.

The baseline is parser-assisted, so the resulting match rate is a reproducible
evidence-confidence metric, not a claim of human-verified ground-truth
accuracy.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


STATEMENTS = (
    ("financial_position", "B01", "v05"),
    ("income_statement", "B02", "v05"),
    ("cash_flow", "B03", "v01"),
)

ISSUE_KEYS = (
    "semantic_dedup_conflicts",
    "source_recovery_conflicts",
    "ambiguous_source_nodes",
    "unresolved",
)

ISSUE_LABELS = {
    "semantic_dedup_conflicts": (
        "nhiều dòng bị gộp vào cùng một mã chuẩn; cần kiểm tra lại cây cha-con"
    ),
    "source_recovery_conflicts": (
        "không khôi phục chắc chắn được quan hệ hoặc giá trị từ dữ liệu nguồn"
    ),
    "ambiguous_source_nodes": (
        "nguồn mơ hồ, thiếu nhãn cha-con hoặc thiếu phạm vi kỳ báo cáo"
    ),
    "unresolved": "chưa xác định được dòng nguồn tương ứng",
    "formula_failed": "đối chiếu công thức hoặc quan hệ tổng không khớp",
    "unmapped_rows": "dòng nguồn chưa có mã chuẩn tương ứng trong schema",
}

FORMULA_LABELS = {
    "net_change_in_cash": "Lưu chuyển tiền thuần trong kỳ",
    "profit_before_tax": "Lợi nhuận trước thuế",
    "profit_after_tax": "Lợi nhuận sau thuế",
    "operating_result": "Kết quả hoạt động kinh doanh",
    "total_comprehensive_income": "Tổng thu nhập toàn diện",
    "gross_profit": "Lợi nhuận gộp",
    "revenue_net": "Doanh thu thuần",
    "net_interest": "Thu nhập lãi thuần",
    "net_service": "Thu nhập dịch vụ thuần",
    "net_other": "Thu nhập khác thuần",
}

EXCLUSION_LABELS = {
    "non_numeric_value": "giá trị không phải số",
    "non_primary_period": "giá trị thuộc kỳ phụ, không phải kỳ chính",
    "period_evidence_conflict": "bằng chứng về kỳ báo cáo mâu thuẫn",
    "placeholder_or_shifted_label": "nhãn tạm hoặc nhãn bị lệch dòng",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def pct(value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value) * 100:.2f}%"


def display_status(value: Any) -> str:
    """Translate machine status values for the human-facing report."""
    return {
        "ok": "Đạt",
        "review_required": "Cần review",
    }.get(str(value), str(value))


def num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def mean_or_none(values: list[float]) -> float | None:
    return mean(values) if values else None


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def first_int(data: dict[str, Any], keys: tuple[str, ...]) -> int:
    """Read the first available integer field from an artifact mapping."""
    for key in keys:
        if data.get(key) is not None:
            return int_or_zero(data.get(key))
    return 0


def statement_artifact(
    comparison: dict[str, Any], statement: str, version: str
) -> dict[str, Any]:
    return comparison[statement][version]


def _occurrence_source_line(node: dict[str, Any]) -> int | None:
    """Return the first useful source line recorded for a canonical node."""

    extraction_meta = node.get("extraction_meta") or {}
    occurrence_groups = (
        extraction_meta.get("occurrences"),
        extraction_meta.get("source_recovery_occurrences"),
        extraction_meta.get("source_recovery_equivalent_occurrences"),
    )
    for occurrences in occurrence_groups:
        if isinstance(occurrences, dict):
            occurrences = [occurrences]
        if not isinstance(occurrences, list):
            continue
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue
            try:
                line = int(occurrence.get("source_line"))
            except (TypeError, ValueError):
                continue
            if line > 0:
                return line
    return None


def _node_occurrences(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return recorded source occurrences for one canonical node."""

    extraction_meta = node.get("extraction_meta") or {}
    result: list[dict[str, Any]] = []
    for occurrences in (
        extraction_meta.get("occurrences"),
        extraction_meta.get("source_recovery_occurrences"),
        extraction_meta.get("source_recovery_equivalent_occurrences"),
    ):
        if isinstance(occurrences, dict):
            occurrences = [occurrences]
        if not isinstance(occurrences, list):
            continue
        result.extend(
            occurrence
            for occurrence in occurrences
            if isinstance(occurrence, dict)
        )
    return result


def _occurrence_for_line(
    node: dict[str, Any], line: int | None
) -> dict[str, Any] | None:
    occurrences = _node_occurrences(node)
    if line is not None:
        for occurrence in occurrences:
            try:
                if int(occurrence.get("source_line")) == line:
                    return occurrence
            except (TypeError, ValueError):
                continue
    return occurrences[0] if occurrences else None


def _source_window(source_lines: list[str] | None, line: int | None) -> str:
    if not source_lines or line is None or line <= 0:
        return ""
    start = max(0, line - 7)
    # Include the preceding period heading when the occurrence comes from the
    # second block of a period-major table (for example 31/12/2025 followed by
    # 31/12/2024). The explanation logic still checks the same source label.
    window = [
        str(item).strip()
        for item in source_lines[start : line + 2]
        if str(item).strip()
    ]
    return "\n".join(window)


def _period_marker(raw: str, period: str) -> bool:
    folded = raw.casefold()
    if period == "current":
        return bool(
            re.search(
                r"số\s*cuối\s*năm|năm\s*(?:nay|hiện\s*tại)|31[./-]12[./-]20\d{2}",
                folded,
            )
        )
    return bool(
        re.search(
            r"số\s*đầu\s*năm|năm\s*trước|01[./-]01[./-]20\d{2}|trình\s*bày\s*lại",
            folded,
        )
    )


def _period_dash_in_source(
    raw: str,
    period: str,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> bool:
    """Detect an explicit dash for the missing period in a source snippet."""

    if not raw:
        return False
    for line in raw.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) >= 2:
            # In the source formats used by this audit the two right-most
            # cells are current then previous. A dash in that slot is
            # authoritative; it means that the source did not report a
            # numeric value for that period.
            slot = cells[-2] if period == "current" else cells[-1]
            if re.fullmatch(r"[-–—]", slot):
                return True
        if period == "current":
            year_marker = (
                rf"|(?<![\d./-])(?:năm\s*)?{int(current_year)}"
                if current_year
                else "|(?<![\d./-])(?:năm\s*)?20\\d{2}"
            )
            date_marker = (
                rf"31[./-]12[./-]{int(current_year)}"
                if current_year
                else r"31[./-]12[./-]20\d{2}"
            )
            pattern = rf"(?:số\s*cuối\s*năm|năm\s*(?:nay|hiện\s*tại)|{date_marker}{year_marker})[^:|]*:\s*[-–—](?:\s|$)"
        else:
            year_marker = (
                rf"|(?<![\d./-])(?:năm\s*)?{int(previous_year)}"
                if previous_year
                else "|(?<![\d./-])(?:năm\s*)?20\\d{2}"
            )
            date_marker = (
                rf"(?:01[./-]01[./-]{int(current_year)}|31[./-]12[./-]{int(previous_year)})"
                if current_year and previous_year
                else r"(?:01[./-]01[./-]20\d{2}|31[./-]12[./-]20\d{2})"
            )
            pattern = rf"(?:số\s*đầu\s*năm|năm\s*trước|{date_marker}|trình\s*bày\s*lại{year_marker})[^:|]*:\s*[-–—](?:\s|$)"
        if re.search(pattern, line, flags=re.I):
            return True
    return False


def _period_block_role(
    line: str, current_year: int | None, previous_year: int | None
) -> str | None:
    folded = re.sub(r"[*_`#:]", "", line).strip().casefold()
    if "năm nay" in folded or "năm hiện tại" in folded:
        return "current"
    if "năm trước" in folded or "số đầu năm" in folded or "trình bày lại" in folded:
        return "previous"
    if current_year and re.search(
        rf"(?:31[./-]12[./-]{int(current_year)}|năm\s*{int(current_year)})",
        folded,
    ):
        return "current"
    if previous_year and re.search(
        rf"(?:31[./-]12[./-]{int(previous_year)}|01[./-]01[./-]{int(current_year or previous_year)}|năm\s*{int(previous_year)})",
        folded,
    ):
        return "previous"
    return None


def _line_source_label(line: str) -> str:
    candidate = re.sub(r"^[*+\-\s]+", "", str(line)).strip()
    candidate = re.sub(r"[*_`#]+", "", candidate)
    if ":" in candidate:
        candidate = candidate.split(":", 1)[0]
    return re.sub(r"\s+", " ", candidate).strip().casefold()


def _period_block_dash_for_label(
    raw: str,
    period: str,
    source_label: str | None,
    current_year: int | None,
    previous_year: int | None,
) -> bool:
    """Find a dash under the same label in a nearby period-major block."""

    if not raw or not source_label:
        return False
    wanted = re.sub(r"\s+", " ", source_label).strip().casefold()
    active_role = None
    for line in raw.splitlines():
        role = _period_block_role(line, current_year, previous_year)
        if role:
            active_role = role
            continue
        if _line_source_label(line) != wanted or active_role != period:
            continue
        tail = line.split(":", 1)[1].strip() if ":" in line else ""
        if re.fullmatch(r"[-–—]", tail):
            return True
    return False


def _explicit_period_value_in_source(
    raw: str,
    period: str,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> bool:
    if period == "current":
        year_marker = (
            rf"|(?<![\d./-])(?:năm\s*)?{int(current_year)}"
            if current_year
            else "|(?<![\d./-])(?:năm\s*)?20\\d{2}"
        )
        date_marker = (
            rf"31[./-]12[./-]{int(current_year)}"
            if current_year
            else r"31[./-]12[./-]20\d{2}"
        )
        pattern = rf"(?:số\s*cuối\s*năm|năm\s*(?:nay|hiện\s*tại)|{date_marker}{year_marker})[^:|]*:\s*\(?-?\d[\d., ]*\)?"
    else:
        year_marker = (
            rf"|(?<![\d./-])(?:năm\s*)?{int(previous_year)}"
            if previous_year
            else "|(?<![\d./-])(?:năm\s*)?20\\d{2}"
        )
        date_marker = (
            rf"(?:01[./-]01[./-]{int(current_year)}|31[./-]12[./-]{int(previous_year)})"
            if current_year and previous_year
            else r"(?:01[./-]01[./-]20\d{2}|31[./-]12[./-]20\d{2})"
        )
        pattern = rf"(?:số\s*đầu\s*năm|năm\s*trước|{date_marker}|trình\s*bày\s*lại{year_marker})[^:|]*:\s*\(?-?\d[\d., ]*\)?"
    return any(re.search(pattern, line, flags=re.I) for line in raw.splitlines())


def _numeric_tokens_in_source(raw: str) -> list[str]:
    tokens = re.findall(r"\(?-?\d[\d., ]*\)?", raw or "")
    return [token for token in tokens if not re.fullmatch(r"20\d{2}", token.strip("() "))]


def _same_label_period_evidence(
    raw: str,
    source_label: str | None,
    period: str,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> str | None:
    """Inspect only the requested source label, not neighbouring child rows."""

    if not raw or not source_label:
        return None
    wanted = re.sub(r"\s+", " ", source_label).strip().casefold()
    active_role = None
    for line in raw.splitlines():
        role = _period_block_role(line, current_year, previous_year)
        if role:
            active_role = role
            continue
        if _line_source_label(line) != wanted:
            continue
        tail = line.split(":", 1)[1].strip() if ":" in line else ""
        if re.fullmatch(r"[-–—]", tail):
            if active_role == period:
                return "dash"
            continue
        if active_role == period and re.search(r"\(?-?\d[\d., ]*\)?", tail):
            return "value"
    return None


def _source_has_previous_first_positional_columns(
    source_lines: list[str] | None,
) -> bool:
    """Detect a Markdown block whose headers are previous-period then current."""

    if not source_lines:
        return False
    # Limit the search to the first balance-sheet statement.  The same source
    # file can contain note tables later with a different column order; those
    # notes must not explain a B01 comparison score.
    start = 0
    for index, line in enumerate(source_lines):
        folded_line = str(line).casefold()
        if "bảng cân đối" not in folded_line and "tình hình tài chính" not in folded_line:
            continue
        lookahead = " ".join(
            str(item).casefold() for item in source_lines[index : index + 260]
        )
        if "nguồn vốn" in lookahead or "nợ phải trả" in lookahead:
            start = index
            break
    end = len(source_lines)
    for index in range(start + 1, len(source_lines)):
        folded_line = str(source_lines[index]).casefold()
        if (
            "báo cáo kết quả kinh doanh" in folded_line
            or "báo cáo lưu chuyển tiền tệ" in folded_line
        ):
            end = index
            break
    scoped_lines = source_lines[start:end]
    folded = [str(line).casefold() for line in scoped_lines]
    for start, line in enumerate(folded):
        if "|" in line or ":" in line or _numeric_tokens_in_source(line):
            continue
        if "số đầu năm" not in line and "trình bày lại" not in line:
            continue
        for end in range(start + 1, min(len(folded), start + 35)):
            if "|" in folded[end] or ":" in folded[end] or _numeric_tokens_in_source(folded[end]):
                continue
            if "số cuối năm" not in folded[end]:
                continue
            for data_line in scoped_lines[end + 1 : min(len(scoped_lines), end + 45)]:
                stripped = str(data_line).strip()
                if "|" in stripped:
                    continue
                if len(_numeric_tokens_in_source(stripped)) >= 2:
                    return True
            break
    return False


def _normalized_numeric(value: Any) -> str:
    """Normalize audit values only for human-readable conflict classification."""

    text = str(value or "").strip()
    if not text:
        return ""
    negative = text.startswith("(") and text.endswith(")")
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return ""
    return ("-" if negative else "") + digits.lstrip("0") or "0"


def _recovery_conflict_explanations(
    diagnostics: dict[str, Any],
    canonical: dict[str, Any] | None = None,
    limit: int = 3,
) -> list[str]:
    """Explain source-recovery conflicts with the actual label and values.

    A count such as ``source_recovery_conflicts=10`` is not actionable by
    itself.  The report should show whether the evidence is a swapped-period
    pair or two different values that share an ambiguous source label.
    """

    conflicts = diagnostics.get("source_recovery_conflicts") or []
    if not isinstance(conflicts, list):
        return []
    details: list[str] = []
    for item in conflicts[:limit]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "không có nhãn")
        line = item.get("source_line")
        line_text = f"dòng nguồn {line}" if line else "không rõ dòng nguồn"
        recovered_current = item.get("recovered_current")
        recovered_previous = item.get("recovered_previous")
        existing_current = item.get("existing_current")
        existing_previous = item.get("existing_previous")
        if (
            _normalized_numeric(recovered_current)
            == _normalized_numeric(existing_previous)
            and _normalized_numeric(recovered_previous)
            == _normalized_numeric(existing_current)
        ):
            reason = (
                "hai cặp số giống nhau nhưng bị đảo thứ tự kỳ; nguồn/Markdown đang đặt "
                "kỳ trước trước kỳ hiện tại hoặc collector chưa có đủ dấu cột"
            )
        else:
            reason = (
                "cùng nhãn xuất hiện ở nhiều cấp hoặc nhiều block nhưng thiếu cây cha-con, "
                "nên không thể chứng minh cặp số nào thuộc node schema hiện có"
            )
        target_node_id = str(item.get("target_node_id") or "")
        target_node = next(
            (
                node
                for node in (canonical or {}).get("nodes") or []
                if str(node.get("node_id") or "") == target_node_id
            ),
            None,
        )
        # Older audit artifacts predate ``target_node_id`` in the conflict
        # record.  Recover the node from its source line so the report remains
        # useful when rebuilt against an existing audit directory.
        if target_node is None and canonical:
            try:
                conflict_line = int(line)
            except (TypeError, ValueError):
                conflict_line = None
            for candidate in canonical.get("nodes") or []:
                if any(
                    int(occurrence.get("source_line")) == conflict_line
                    and str(occurrence.get("source_label") or "") == label
                    for occurrence in _node_occurrences(candidate)
                    if str(occurrence.get("source_line") or "").isdigit()
                ):
                    target_node = candidate
                    target_node_id = str(candidate.get("node_id") or "")
                    break
        source_path = str(
            item.get("source_hierarchy_path")
            or item.get("source_parent_label")
            or ""
        )
        existing_paths: list[str] = []
        if target_node:
            for occurrence in _node_occurrences(target_node):
                context = occurrence.get("source_context") or {}
                path = context.get("path") or []
                if isinstance(path, list):
                    path_text = " > ".join(str(part) for part in path if part)
                else:
                    path_text = str(path)
                if path_text and path_text not in existing_paths:
                    existing_paths.append(path_text)
            if not source_path:
                for occurrence in _node_occurrences(target_node):
                    try:
                        if int(occurrence.get("source_line")) != int(line):
                            continue
                    except (TypeError, ValueError):
                        continue
                    context = occurrence.get("source_context") or {}
                    path = context.get("path") or []
                    if isinstance(path, list):
                        source_path = " > ".join(str(part) for part in path if part)
                    else:
                        source_path = str(path)
                    if source_path:
                        break
        if len(existing_paths) > 1:
            reason = (
                f"cùng nhãn được dùng dưới các cây khác nhau ({' | '.join(existing_paths[:2])}); "
                "schema hiện chỉ có một node nên không đủ định danh để tách các cấp cha-con"
            )
        elif source_path and existing_paths and source_path in existing_paths:
            reason = (
                "cùng nhãn xuất hiện hai lần dưới cùng một cây nguồn nhưng Markdown không có "
                "nhãn con hoặc dấu phân cách cho cặp số thứ hai; parser không được tự chọn một cặp"
            )
        details.append(
            f"`{label}` ({line_text}): nguồn khôi phục ra kỳ hiện tại={recovered_current}, "
            f"kỳ trước={recovered_previous}, trong khi node đã có kỳ hiện tại="
            f"{existing_current}, kỳ trước={existing_previous}; {reason}"
        )
    return details


def _semantic_conflict_explanation(diagnostics: dict[str, Any]) -> str | None:
    """Describe real semantic collisions separately from structural collisions."""

    semantic = diagnostics.get("semantic_dedup") or {}
    conflicting_nodes = semantic.get("conflicting_nodes") or []
    structural = semantic.get("structural_context_collisions") or []
    parts: list[str] = []
    if conflicting_nodes:
        names = []
        for item in conflicting_nodes[:4]:
            if isinstance(item, dict):
                names.append(str(item.get("node_id") or item.get("canonical_name") or "node không tên"))
            else:
                names.append(str(item))
        parts.append(
            "xung đột semantic thật tại " + ", ".join(f"`{name}`" for name in names)
            + "; cùng một mã chuẩn nhận các giá trị khác nhau nên không được tự ghi đè"
        )
    collision_count = 0
    collision_details: list[str] = []
    for item in structural:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "node không tên")
        collisions = item.get("collisions") or []
        collision_count += len(collisions)
        for collision in collisions[:2]:
            if not isinstance(collision, dict):
                continue
            first = collision.get("first_source_line")
            second = collision.get("conflicting_source_line")
            collision_details.append(
                f"`{node_id}` tại dòng {first} và {second}"
            )
    if collision_count:
        detail = ", ".join(collision_details[:3])
        parts.append(
            f"có {collision_count} va chạm cấu trúc parent/child ({detail}); đây là trường hợp "
            "Markdown dùng cùng một mã schema cho dòng cha và dòng con, không phải parser đọc sai số"
        )
    return "; ".join(parts) if parts else None


def _missing_period_cause(
    period: str,
    raw: str,
    line: int | None,
    source_label: str | None = None,
    current_year: int | None = None,
    previous_year: int | None = None,
    occurrence: dict[str, Any] | None = None,
    node_kind: str | None = None,
) -> str:
    """Explain why one period is absent without hiding behind a metric name."""

    shown_line = f"dòng nguồn {line}" if line else "không xác định được dòng nguồn"
    snippet = re.sub(r"\s+", " ", raw).strip()
    if len(snippet) > 180:
        snippet = snippet[:177] + "..."

    occurrence_values = [
        value
        for value in (occurrence or {}).get("values") or []
        if isinstance(value, dict)
    ]
    occurrence_periods = [
        str(value.get("period_label") or value.get("period_key") or "")
        for value in occurrence_values
        if value.get("period_key") in {"current", "previous"}
    ]
    occurrence_pattern = str((occurrence or {}).get("pattern_id") or "")

    # A period-children observation is a wrapper with its own value only for
    # the periods explicitly listed in that block.  Numbers in nested child
    # rows must not be presented as a missing value of the wrapper itself.
    if occurrence_pattern == "SP_PERIOD_CHILDREN" and not any(
        value.get("period_key") == period for value in occurrence_values
    ):
        reported = ", ".join(occurrence_periods) or "một kỳ"
        return (
            f"{shown_line}: block nguồn của chính chỉ tiêu này chỉ ghi {reported}; "
            f"không có giá trị cho {('kỳ hiện tại' if period == 'current' else 'kỳ trước')} "
            "ở cùng cấp. Các số xuất hiện ở các dòng con lân cận là số của dòng con, "
            "không được tự gán vào dòng cha; độ phủ thấp ở đây do cấu trúc nguồn không "
            "cung cấp giá trị tổng cho kỳ đó, không phải parser tự làm mất số"
            + (f" (nguồn: {snippet})" if snippet else "")
        )

    same_label_evidence = _same_label_period_evidence(
        raw,
        source_label,
        period,
        current_year,
        previous_year,
    )
    if (
        same_label_evidence == "dash"
        or _period_block_dash_for_label(
            raw,
            period,
            source_label,
            current_year,
            previous_year,
        )
        or (
            same_label_evidence is None
            and _period_dash_in_source(raw, period, current_year, previous_year)
        )
    ):
        return (
            f"{shown_line}: nguồn ghi dấu '-' đúng ở block/nhãn của kỳ này, nghĩa là kỳ đó không có "
            "giá trị số được báo; parser giữ là rỗng và không tự đổi thành 0"
            + (f" (nguồn: {snippet})" if snippet else "")
        )
    if same_label_evidence == "value":
        return (
            f"{shown_line}: nguồn có giá trị rõ cho {('kỳ hiện tại' if period == 'current' else 'kỳ trước')} "
            "ngay trên nhãn này nhưng kết quả chưa gắn được vào node; "
            "đây là lỗi mapping/parser cần xử lý, không phải dữ liệu nguồn thiếu"
            + (f" (nguồn: {snippet})" if snippet else "")
        )
    pipe_numeric_pair = any(
        len(_numeric_tokens_in_source(line)) >= 2 and "|" in line
        for line in raw.splitlines()
    )
    if pipe_numeric_pair:
        return (
            f"{shown_line}: nguồn có hai cột số trên cùng dòng nhưng kết quả chưa "
            f"gắn đủ {('kỳ hiện tại' if period == 'current' else 'kỳ trước')}; "
            "đây là lỗi parser/ánh xạ cột cần xử lý"
            + (f" (nguồn: {snippet})" if snippet else "")
        )
    if (
        same_label_evidence is None
        and occurrence_pattern not in {"SP_PERIOD_CHILDREN", "SP_LABEL_VALUE_INLINE"}
        and _explicit_period_value_in_source(
            raw, period, current_year, previous_year
        )
    ):
        return (
            f"{shown_line}: nguồn có dấu kỳ và số nhưng chưa chứng minh được số đó "
            "thuộc đúng nhãn/node này; cần kiểm tra schema/cây cha-con trước khi kết luận parser"
            + (f" (nguồn: {snippet})" if snippet else "")
        )
    tokens = _numeric_tokens_in_source(raw)
    if tokens or _period_marker(raw, period):
        return (
            f"{shown_line}: nguồn chỉ thể hiện một giá trị hoặc một block kỳ cho "
            f"chỉ tiêu này, không có bằng chứng số cho {('kỳ hiện tại' if period == 'current' else 'kỳ trước')}; "
            "độ phủ thấp phản ánh dữ liệu nguồn/Markdown chưa cung cấp đủ kỳ ở đúng node"
            + (f" (nguồn: {snippet})" if snippet else "")
        )
    return (
        f"{shown_line}: không tìm thấy bằng chứng nguồn rõ ràng cho kỳ bị thiếu; "
        "cần kiểm tra lại dòng Markdown và cây cha-con; chưa đủ bằng chứng để quy kết parser"
    )


def missing_period_examples(
    canonical: dict[str, Any] | None,
    period: str,
    source_lines: list[str] | None = None,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> list[str]:
    """Return a few source-backed labels missing one reporting period."""
    if not canonical:
        return []
    other_period = "previous" if period == "current" else "current"
    examples: list[str] = []
    seen: set[str] = set()
    for node in canonical.get("nodes") or []:
        # Coverage is measured on semantic schema nodes.  Recovered/source-only
        # observations are intentionally retained for provenance, but including
        # them here would make a perfectly complete canonical node look as if a
        # period were missing (the source-only duplicate may contain one value).
        if node.get("kind") == "source_observation":
            continue
        value = node.get("value") or {}
        if value.get(period) is not None or value.get(other_period) is None:
            continue
        label = str(node.get("canonical_name") or node.get("node_id") or "")
        if not label or label in seen:
            continue
        seen.add(label)
        line = _occurrence_source_line(node)
        source_label = label
        occurrence = _occurrence_for_line(node, line)
        if occurrence:
            source_label = str(
                occurrence.get("source_label") or source_label
            )
        raw = _source_window(source_lines, line)
        cause = _missing_period_cause(
            period,
            raw,
            line,
            source_label,
            current_year,
            previous_year,
            occurrence,
            str(node.get("kind") or ""),
        )
        examples.append(f"{label}: {cause}")
        if len(examples) >= 4:
            break
    return examples


def statement_explanation(
    current: dict[str, Any],
    short_name: str,
    canonical: dict[str, Any] | None,
    evaluation: dict[str, Any] | None = None,
    source_lines: list[str] | None = None,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> str:
    """Explain the concrete reason behind a statement's weak metrics."""
    mapping = current.get("mapping") or {}
    parser = current.get("parser") or {}
    errors = current.get("error_taxonomy") or {}
    quality = current.get("quality") or {}
    diagnostics = (canonical or {}).get("diagnostics") or {}
    evaluation = evaluation or {}
    explanations: list[str] = []
    status = str(current.get("status") or "")

    denominator = first_int(
        mapping, ("coverage_value_nodes", "canonical_value_nodes", "input_rows")
    )
    current_have = first_int(
        mapping, ("coverage_current_value_nodes", "current_value_nodes")
    )
    previous_have = first_int(
        mapping, ("coverage_previous_value_nodes", "previous_value_nodes")
    )
    for period_label, coverage, available in (
        ("kỳ hiện tại", num(mapping.get("current_coverage")), current_have),
        ("kỳ trước", num(mapping.get("previous_coverage")), previous_have),
    ):
        if status == "no_structural_rows":
            continue
        if coverage is None or coverage >= 0.999999:
            continue
        if denominator:
            missing = max(denominator - available, 0)
            explanations.append(
                f"{period_label} chỉ có {available}/{denominator} nhóm dòng có giá trị "
                f"({pct(coverage)}), thiếu {missing} nhóm"
            )
            examples = missing_period_examples(
                canonical,
                "current" if period_label == "kỳ hiện tại" else "previous",
                source_lines,
                current_year,
                previous_year,
            )
            if examples:
                explanations.append(
                    f"nguyên nhân cụ thể của phần thiếu {period_label}: "
                    + "; ".join(examples)
                )
        else:
            explanations.append(
                f"{period_label} chỉ đạt {pct(coverage)} nhưng bộ audit không lưu "
                "được số nhóm dòng bị thiếu"
            )

    unmapped = int_or_zero(errors.get("unmapped_total"))
    mapping_rate = num(mapping.get("mapping_rate"))
    if unmapped:
        examples = current.get("unmapped_examples") or []
        if isinstance(examples, dict):
            examples = [examples]
        example_text: list[str] = []
        for example in examples[:3]:
            label = str(example.get("label") or "không có nhãn")
            code = example.get("code") or example.get("statement_code")
            line = example.get("source_line")
            suffix = []
            if code:
                suffix.append(f"mã {code}")
            if line:
                suffix.append(f"dòng nguồn {line}")
            example_text.append(
                f"{label}" + (f" ({', '.join(suffix)})" if suffix else "")
            )
        detail = "; ví dụ: " + "; ".join(example_text) if example_text else ""
        explanations.append(
            f"{unmapped} dòng nguồn không gắn được vào mã chuẩn trong schema{detail}"
        )

    incomplete_coverage = any(
        num(mapping.get(key)) is not None and num(mapping.get(key)) < 0.999999
        for key in ("current_coverage", "previous_coverage")
    )
    weak_coverage = any(
        num(mapping.get(key)) is not None and num(mapping.get(key)) < 0.95
        for key in ("current_coverage", "previous_coverage")
    )
    if incomplete_coverage and status != "no_structural_rows":
        if unmapped:
            explanations.append(
                "một phần độ phủ thấp đến từ các dòng nguồn chưa có mapping"
            )
        elif mapping_rate is not None and mapping_rate >= 0.95:
            explanations.append(
                "các dòng trong vùng đã được nhận diện và gắn mã; vì vậy phần thiếu "
                "không phải do bỏ sót toàn bộ dòng. Cần đọc các ví dụ nguồn ở trên để "
                "phân biệt dấu '-' (nguồn không báo số), block chỉ có một kỳ (nguồn "
                "thiếu kỳ), hay hai số cùng dòng chưa được gắn đủ kỳ (nghi vấn parser)"
            )
        else:
            explanations.append(
                "độ phủ thấp chưa thể quy hết cho parser: một phần có thể do nguồn chỉ "
                "ghi một kỳ hoặc dùng dấu '-', phần còn lại có thể do schema/cây cha-con "
                "chưa đủ để ánh xạ; các ví dụ dòng nguồn là bằng chứng quyết định"
            )

    pair_rate = num(evaluation.get("numeric_value_match_rate"))
    label_rate = num(evaluation.get("value_match_rate"))
    value_only_rate = num(evaluation.get("value_only_match_rate"))
    missing_pairs = int_or_zero(evaluation.get("numeric_value_pairs_missing"))
    if pair_rate is not None and pair_rate < 0.95:
        missing_examples = evaluation.get("missing_examples") or []
        if isinstance(missing_examples, dict):
            missing_examples = [missing_examples]
        pair_examples: list[str] = []
        for example in missing_examples[:4]:
            label = str(example.get("label") or "không có nhãn")
            period = {
                "current": "kỳ hiện tại",
                "previous": "kỳ trước",
            }.get(str(example.get("period")), str(example.get("period") or "không rõ kỳ"))
            value = example.get("value")
            pair_examples.append(f"{label} ({period}, giá trị {value})")
        detail = (
            "; ví dụ: " + "; ".join(pair_examples)
            if pair_examples
            else ""
        )
        explanations.append(
            f"bộ đối chiếu còn thiếu {missing_pairs} cặp kỳ + giá trị "
            f"(tỷ lệ khớp {pct(pair_rate)}){detail}"
        )

    unexpected_values = int_or_zero(evaluation.get("unexpected_values"))
    if unexpected_values and pair_rate is not None and pair_rate < 0.95:
        explanations.append(
            f"kết quả parse có thêm {unexpected_values} giá trị không xuất hiện trong "
            "bộ đối chiếu; cần kiểm tra đó là dòng thuyết minh/dòng lặp, alias khác "
            "hay mapping thừa"
        )

    if (
        label_rate is not None
        and label_rate < 0.95
        and value_only_rate is not None
        and value_only_rate >= 0.95
    ):
        explanations.append(
            f"giá trị số khớp theo nội dung ở mức {pct(value_only_rate)}, nhưng "
            f"khớp cả tên + kỳ + giá trị chỉ đạt {pct(label_rate)}; phần chênh lệch "
            "nhiều khả năng do alias, khác cấp cha-con hoặc dòng nguồn chỉ giữ theo "
            "nguồn chứ không phải sai số học"
        )

    if (
        short_name == "B01"
        and pair_rate is not None
        and pair_rate < 0.95
        and _source_has_previous_first_positional_columns(source_lines)
    ):
        explanations.append(
            "nguồn đặt cột `Số đầu năm (Trình bày lại)` trước `Số cuối năm`; "
            "các dòng dữ liệu dạng hai số phải đọc số thứ nhất là kỳ trước và số thứ hai "
            "là kỳ hiện tại. Tỷ lệ khớp thấp ở file này bị kéo xuống một phần do bộ đối "
            "chiếu plain-sequential có dòng theo thứ tự ngược; parser hiện bám đúng thứ tự "
            "cột ghi trong Markdown, nên đây là lệch kiến trúc nguồn/baseline chứ không phải parser đảo số"
        )

    ground_truth_quality = evaluation.get("ground_truth_quality") or {}
    excluded_by_reason = ground_truth_quality.get("excluded_by_reason") or {}
    if excluded_by_reason:
        excluded_text = ", ".join(
            f"{EXCLUSION_LABELS.get(str(reason), str(reason))} {count} trường hợp"
            for reason, count in excluded_by_reason.items()
        )
        explanations.append(
            "bộ đối chiếu đã loại khỏi phép so sánh "
            f"{excluded_text}; các giá trị này không nên quy trực tiếp thành lỗi parser"
        )

    source_mapping = diagnostics.get("source_observation_mapping") or {}
    source_nodes = int_or_zero(source_mapping.get("source_nodes"))
    linked_source_nodes = int_or_zero(source_mapping.get("linked_source_nodes"))
    source_only_nodes = int_or_zero(source_mapping.get("source_only_nodes"))
    ambiguous_source_nodes = int_or_zero(
        source_mapping.get("ambiguous_source_nodes")
    )
    low_label_with_good_values = (
        label_rate is not None
        and label_rate < 0.95
        and value_only_rate is not None
        and value_only_rate >= 0.95
    )
    if source_nodes and (incomplete_coverage or low_label_with_good_values):
        if low_label_with_good_values and not weak_coverage:
            source_detail = (
                f"giá trị số đã khớp ở mức {pct(value_only_rate)}, nhưng vùng nguồn tạo "
                f"{source_nodes} dòng quan sát; chỉ {linked_source_nodes} dòng nối được "
                f"vào schema và còn {source_only_nodes} dòng chỉ giữ theo nguồn"
            )
        else:
            source_detail = (
                f"vùng này tạo {source_nodes} dòng quan sát; chỉ {linked_source_nodes} "
                f"dòng nối được vào schema, còn {source_only_nodes} dòng chỉ giữ theo "
                "nguồn"
            )
        if ambiguous_source_nodes:
            source_detail += (
                f" và {ambiguous_source_nodes} dòng còn mơ hồ về node tương ứng"
            )
        if low_label_with_good_values:
            explanations.append(
                source_detail
                + "; vì vậy phần tỷ lệ thấp nằm ở tên/quan hệ schema (alias hoặc cây cha-con), "
                "không nằm ở việc đọc sai giá trị số"
            )
        elif incomplete_coverage and not weak_coverage:
            explanations.append(
                source_detail
                + "; các dòng chỉ giữ theo nguồn làm giảm độ phủ của node schema, "
                "nhưng chưa đủ bằng chứng để kết luận parser đọc sai số"
            )
        else:
            explanations.append(
                source_detail
                + "; phần này chỉ được giữ theo dữ liệu nguồn, làm giảm khả năng khớp tên, nhưng chưa đủ "
                "cơ sở để kết luận đó là lỗi parser"
            )

    formula_checks = diagnostics.get("formula_checks") or []
    failed_formulas = [
        check for check in formula_checks if str(check.get("status")) == "fail"
    ]
    if not failed_formulas and int_or_zero(quality.get("formula_failed")):
        explanations.append(
            f"có {int_or_zero(quality.get('formula_failed'))} phép đối chiếu tổng/công "
            "thức không khớp; bộ audit không lưu chi tiết phép tính"
        )
    elif failed_formulas:
        formula_text = []
        for check in failed_formulas[:4]:
            raw_name = check.get("name") or "phép kiểm tra không tên"
            name = FORMULA_LABELS.get(str(raw_name), str(raw_name))
            raw_period = check.get("period")
            period = {
                "current": "kỳ hiện tại",
                "previous": "kỳ trước",
            }.get(str(raw_period), "không rõ kỳ")
            reported = check.get("reported")
            expected = check.get("expected")
            difference = check.get("difference")
            formula_text.append(
                f"{name} ({period}: báo cáo {reported}, tính lại {expected}, "
                f"lệch {difference})"
            )
        explanations.append(
            "các phép đối chiếu không khớp: " + "; ".join(formula_text)
        )

    recovery = diagnostics.get("source_statement_recovery") or {}
    recovery_conflicts = int_or_zero(
        recovery.get("conflicts") or parser.get("source_recovery_conflicts")
    )
    structural_ambiguities = int_or_zero(recovery.get("structural_ambiguities"))
    period_ambiguities = int_or_zero(recovery.get("period_scope_ambiguities"))
    if recovery_conflicts:
        conflict_details = _recovery_conflict_explanations(diagnostics, canonical)
        detail = (
            "; ví dụ cụ thể: " + "; ".join(conflict_details)
            if conflict_details
            else ""
        )
        explanations.append(
            f"khôi phục từ nguồn còn {recovery_conflicts} xung đột; điều này nghĩa là "
            "bằng chứng nguồn và node schema hiện có đưa ra hai cặp giá trị khác nhau, "
            "nên parser giữ lại xung đột thay vì âm thầm ghi đè"
            + detail
        )
    semantic_detail = _semantic_conflict_explanation(diagnostics)
    if semantic_detail:
        explanations.append(semantic_detail)
    if structural_ambiguities:
        explanations.append(
            f"nguồn có {structural_ambiguities} vị trí mơ hồ về cấu trúc cha-con"
        )
    if period_ambiguities:
        ambiguity_rows = diagnostics.get("source_period_scope_ambiguities") or []
        labels = [
            str(item.get("source_label"))
            for item in ambiguity_rows[:3]
            if item.get("source_label")
        ]
        detail = f" ({', '.join(labels)})" if labels else ""
        explanations.append(
            f"có {period_ambiguities} nhãn chứa đồng thời giá trị quý và lũy kế, "
            f"không có dấu phân cách kỳ đủ rõ{detail}"
        )

    locator_reason = str(parser.get("locator_reason") or "")
    if status == "no_structural_rows":
        if "scope_overlap_too_low" in locator_reason:
            overlap = locator_reason.split(":", 1)[-1]
            try:
                overlap_text = pct(float(overlap))
            except ValueError:
                overlap_text = "thấp"
            explanations.append(
                "không tìm thấy dòng có cấu trúc phù hợp; vùng nguồn chính chỉ "
                f"khớp {overlap_text} với mẫu statement nên không đủ cơ sở để map"
            )
        else:
            explanations.append(
                "không tìm thấy dòng có cấu trúc phù hợp cho statement này; "
                "cần kiểm tra lại bố cục nguồn hoặc Markdown"
            )
    elif "scope_overlap_too_low" in locator_reason:
        overlap = locator_reason.split(":", 1)[-1]
        try:
            overlap_text = pct(float(overlap))
        except ValueError:
            overlap_text = "thấp"
        explanations.append(
            "vùng nguồn chính chỉ khớp "
            f"{overlap_text} với mẫu statement; parser phải dựa thêm vào vùng "
            "bổ sung hoặc giữ dòng ở dạng chỉ theo dữ liệu nguồn"
        )

    if not explanations:
        explanations.append(
            "không có nguyên nhân thiếu độ phủ hoặc cảnh báo nội bộ trong bộ audit"
        )
    return ". ".join(explanations) + "."


def collect_statement_diagnostics(
    current: dict[str, Any], short_name: str, public_status: str
) -> tuple[dict[str, Any], dict[str, int], list[str]]:
    mapping = current.get("mapping") or {}
    parser = current.get("parser") or {}
    quality = current.get("quality") or {}
    errors = current.get("error_taxonomy") or {}
    issue_counts: dict[str, int] = {}
    reasons: list[str] = []

    for key in ISSUE_KEYS:
        value = int(parser.get(key) or 0)
        if value:
            issue_counts[key] = value
            reasons.append(
                f"{short_name}: {ISSUE_LABELS[key]} ({value} trường hợp)"
            )

    formula_failed = int(quality.get("formula_failed") or 0)
    if formula_failed:
        issue_counts["formula_failed"] = formula_failed
        reasons.append(
            f"{short_name}: {ISSUE_LABELS['formula_failed']} "
            f"({formula_failed} trường hợp)"
        )

    unmapped = int(errors.get("unmapped_total") or 0)
    if unmapped:
        issue_counts["unmapped_rows"] = unmapped
        reasons.append(
            f"{short_name}: {ISSUE_LABELS['unmapped_rows']} "
            f"({unmapped} dòng)"
        )

    current_coverage = num(mapping.get("current_coverage"))
    previous_coverage = num(mapping.get("previous_coverage"))
    denominator = first_int(
        mapping, ("coverage_value_nodes", "canonical_value_nodes", "input_rows")
    )
    for period_label, coverage, available in (
        ("kỳ hiện tại", current_coverage, first_int(
            mapping, ("coverage_current_value_nodes", "current_value_nodes")
        )),
        ("kỳ trước", previous_coverage, first_int(
            mapping, ("coverage_previous_value_nodes", "previous_value_nodes")
        )),
    ):
        if coverage is not None and coverage < 0.95:
            if denominator:
                missing = max(denominator - available, 0)
                reasons.append(
                    f"{short_name}: {period_label} chỉ có {available}/{denominator} "
                    f"nhóm dòng có giá trị ({pct(coverage)}), thiếu {missing} nhóm"
                )
            else:
                reasons.append(
                    f"{short_name}: {period_label} chỉ đạt {pct(coverage)}; "
                    "bộ audit không lưu được số nhóm dòng bị thiếu"
                )

    mapping_rate = num(mapping.get("mapping_rate"))
    if mapping_rate is not None and mapping_rate < 0.95:
        reasons.append(
            f"{short_name}: tỷ lệ ánh xạ dòng nguồn thấp ({pct(mapping_rate)}); "
            "nhiều dòng chưa gắn được vào mã chuẩn"
        )

    statement_status = str(current.get("status") or public_status)
    if statement_status != "ok" and not any(
        reason.startswith(f"{short_name}:") for reason in reasons
    ):
        reasons.append(
            f"{short_name}: trạng thái cần review; chưa có nguyên nhân chi tiết"
        )

    detail = {
        "status": statement_status,
        "current_coverage": current_coverage,
        "previous_coverage": previous_coverage,
        "mapping_rate": mapping_rate,
        "formula_failed": formula_failed,
        "issue_total": sum(issue_counts.values()),
    }
    return detail, issue_counts, reasons


def assessment(row: dict[str, Any]) -> str:
    status = row["overall_status"]
    coverage = row["coverage_min"]
    pair = row["pair_min"]
    issues = row["issue_total"]
    if status == "ok" and not issues and (coverage or 0) >= 0.95:
        return "A - đạt production"
    if pair is not None and pair < 0.90 and coverage is not None and coverage < 0.90:
        return "D - khớp thấp + thiếu phủ"
    if pair is not None and pair < 0.90:
        return "D - khớp giá trị thấp"
    if coverage is not None and coverage < 0.90:
        return "D - độ phủ thấp"
    if issues >= 10:
        return "C - nhiều xung đột"
    if issues:
        return "C - còn xung đột"
    return "B - cần review gate"


def file_conclusion(row: dict[str, Any]) -> str:
    """Return a short human-readable conclusion for one report file."""
    if row["overall_status"] == "ok" and not row["issue_total"]:
        return (
            "Đạt production gate; không phát hiện xung đột gộp mã, lỗi khôi phục "
            "nguồn hoặc lỗi đối chiếu công thức trong audit hiện tại."
        )

    reasons: list[str] = []
    if row["semantic_dedup_conflicts"]:
        reasons.append(
            "nhiều dòng bị gộp vào cùng mã chuẩn, cần kiểm tra cây cha-con "
            f"({row['semantic_dedup_conflicts']} trường hợp)"
        )
    if row["source_recovery_conflicts"]:
        reasons.append(
            "không khôi phục chắc chắn được quan hệ/giá trị từ nguồn "
            f"({row['source_recovery_conflicts']} trường hợp)"
        )
    if row["ambiguous_source_nodes"]:
        reasons.append(
            "nguồn mơ hồ, thiếu nhãn cha-con hoặc phạm vi kỳ "
            f"({row['ambiguous_source_nodes']} trường hợp)"
        )
    if row["formula_failed"]:
        reasons.append(
            "đối chiếu công thức hoặc quan hệ tổng không khớp "
            f"({row['formula_failed']} trường hợp)"
        )
    if row["unresolved"]:
        reasons.append(
            "chưa xác định được dòng nguồn tương ứng "
            f"({row['unresolved']} trường hợp)"
        )
    if row["unmapped_rows"]:
        reasons.append(
            "dòng nguồn chưa có mã chuẩn tương ứng trong schema "
            f"({row['unmapped_rows']} dòng)"
        )
    if row["coverage_min"] is not None and row["coverage_min"] < 0.95:
        reasons.append(
            "độ phủ thấp nhất "
            f"{pct(row['coverage_min'])}; một số chỉ tiêu thiếu giá trị "
            "ở một trong hai kỳ hoặc chưa được ánh xạ"
        )
    if row["pair_min"] is not None and row["pair_min"] < 0.90:
        reasons.append(
            "tỷ lệ khớp đồng thời kỳ và giá trị thấp nhất "
            f"{pct(row['pair_min'])}"
        )

    if not reasons:
        reasons.append("cần review gate theo tiêu chí bảo thủ")
    return "; ".join(reasons) + "."


def build_rows(
    comparison_path: Path,
    manifest_path: Path,
    audit_dir: Path,
    sources_dir: Path | None = None,
) -> list[dict[str, Any]]:
    comparison = load_json(comparison_path)
    manifest = load_json(manifest_path)
    manifest_by_source = {
        item["source"]["name"]: item for item in manifest.get("reports") or []
    }
    rows: list[dict[str, Any]] = []

    for evaluated in comparison.get("reports") or []:
        source_name = str(evaluated.get("source_file") or "")
        stem = Path(source_name).stem
        manifest_item = manifest_by_source[source_name]
        current_comparison = load_json(audit_dir / f"{stem}.comparison.json")
        source_lines: list[str] | None = None
        if sources_dir:
            source_path = sources_dir / source_name
            if source_path.exists():
                source_lines = source_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
        coverage_values: list[float] = []
        pair_values: list[float] = []
        label_values: list[float] = []
        issue_counts: dict[str, int] = {}
        reasons: list[str] = []
        row: dict[str, Any] = {
            "file": source_name,
            "symbol": source_name.split("_", 1)[0],
            "overall_status": manifest_item.get("status", ""),
            "source_hash": "OK" if evaluated.get("source_hash_equal") else "MISMATCH",
            "year_conflict": bool(
                (current_comparison.get("year_resolution") or {}).get("conflict")
            ),
        }

        current_statement_data = {
            "financial_position": statement_artifact(
                current_comparison, "financial_position", "v05"
            ),
            "income_statement": statement_artifact(
                current_comparison, "income_statement", "v05"
            ),
            "cash_flow": statement_artifact(
                current_comparison, "cash_flow_statement", "v01"
            ),
        }
        canonical_suffixes = {
            "financial_position": "financial_position",
            "income_statement": "income",
            "cash_flow": "cashflow",
        }
        canonical_statement_data: dict[str, dict[str, Any]] = {}
        for statement, suffix in canonical_suffixes.items():
            canonical_path = audit_dir / f"{stem}.{suffix}.canonical.json"
            canonical_statement_data[statement] = (
                load_json(canonical_path) if canonical_path.exists() else {}
            )

        for statement, short_name, version in STATEMENTS:
            public_status = (manifest_item.get("statements") or {}).get(statement, "")
            current = current_statement_data[statement]
            detail, statement_issues, statement_reasons = collect_statement_diagnostics(
                current, short_name, public_status
            )
            evaluation = evaluated["statements"][statement]
            current_cov = detail["current_coverage"]
            previous_cov = detail["previous_coverage"]
            for value in (current_cov, previous_cov):
                if value is not None:
                    coverage_values.append(value)
            for key, value in statement_issues.items():
                issue_counts[key] = issue_counts.get(key, 0) + value
            reasons.extend(statement_reasons)

            pair_rate = num(evaluation.get("numeric_value_match_rate"))
            label_rate = num(evaluation.get("value_match_rate"))
            if pair_rate is not None:
                pair_values.append(pair_rate)
            if label_rate is not None:
                label_values.append(label_rate)

            row[f"{short_name}_status"] = public_status
            row[f"{short_name}_coverage"] = (
                f"{pct(current_cov)}/{pct(previous_cov)}"
            )
            row[f"{short_name}_pair_rate"] = pair_rate
            row[f"{short_name}_label_rate"] = label_rate
            row[f"{short_name}_missing_pairs"] = int(
                evaluation.get("numeric_value_pairs_missing") or 0
            )
            row[f"{short_name}_explanation"] = statement_explanation(
                current,
                short_name,
                canonical_statement_data.get(statement),
                evaluation,
                source_lines,
                int_or_zero((current_comparison.get("year_resolution") or {}).get("current_year"))
                or int_or_zero(current_comparison.get("current_year"))
                or None,
                int_or_zero((current_comparison.get("year_resolution") or {}).get("previous_year"))
                or int_or_zero(current_comparison.get("previous_year"))
                or None,
            )

        if row["year_conflict"]:
            reasons.append(
                "không xác định nhất quán được năm báo cáo giữa các phần của nguồn"
            )

        row.update(
            {
                "coverage_min": min(coverage_values) if coverage_values else None,
                "coverage_avg": mean_or_none(coverage_values),
                "pair_min": min(pair_values) if pair_values else None,
                "pair_avg": mean_or_none(pair_values),
                "label_min": min(label_values) if label_values else None,
                "label_avg": mean_or_none(label_values),
                "missing_pairs": sum(
                    row[f"{short_name}_missing_pairs"] for _, short_name, _ in STATEMENTS
                ),
                "issue_total": sum(issue_counts.values()),
                "semantic_dedup_conflicts": issue_counts.get(
                    "semantic_dedup_conflicts", 0
                ),
                "source_recovery_conflicts": issue_counts.get(
                    "source_recovery_conflicts", 0
                ),
                "unmapped_rows": issue_counts.get("unmapped_rows", 0),
                "formula_failed": issue_counts.get("formula_failed", 0),
                "ambiguous_source_nodes": issue_counts.get(
                    "ambiguous_source_nodes", 0
                ),
                "unresolved": issue_counts.get("unresolved", 0),
                "reasons": "; ".join(dict.fromkeys(reasons)),
            }
        )
        row["conservative_score"] = (
            min(row["coverage_min"], row["pair_min"])
            if row["coverage_min"] is not None and row["pair_min"] is not None
            else None
        )
        row["assessment"] = assessment(row)
        rows.append(row)

    rows.sort(
        key=lambda item: (
            0 if item["overall_status"] == "ok" else 1,
            -(item["conservative_score"] or 0),
            item["issue_total"],
            -(item["label_avg"] or 0),
            item["symbol"],
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def markdown_report(
    rows: list[dict[str, Any]],
    comparison_path: Path,
    manifest_path: Path,
    audit_dir: Path,
) -> str:
    ok_reports = [row for row in rows if row["overall_status"] == "ok"]
    weakest_coverage = sorted(
        rows, key=lambda row: (row["coverage_min"] or 9, row["symbol"])
    )[:10]
    weakest_pair = sorted(
        rows, key=lambda row: (row["pair_min"] or 9, row["symbol"])
    )[:10]
    conflict_heavy = sorted(
        rows, key=lambda row: (-row["issue_total"], row["symbol"])
    )[:10]
    statement_gate_counts = {
        short_name: sum(
            1 for row in rows if row.get(f"{short_name}_status") == "ok"
        )
        for _, short_name, _ in STATEMENTS
    }
    weakest_pair_name = weakest_pair[0]["symbol"] if weakest_pair else "-"
    weakest_coverage_name = (
        weakest_coverage[0]["symbol"] if weakest_coverage else "-"
    )
    dynamic_issue_lines = [
        f"- `{row['symbol']}`: {row['reasons'] or 'còn review gate; chưa có nguyên nhân chi tiết.'}"
        for row in conflict_heavy[:5]
        if row["issue_total"] or row["overall_status"] != "ok"
    ]

    lines = [
        "# Báo cáo đánh giá kết quả hiện tại",
        "",
        f"- Phạm vi: **{len(rows)} file**, chỉ kiểm tra dữ liệu nguồn; phần ghi chú tắt.",
        f"- Manifest: `{manifest_path}`",
        f"- Audit directory: `{audit_dir}`",
        f"- Bộ dữ liệu đối chiếu: `{comparison_path}`",
        f"- Thời điểm lập: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Kết luận điều hành",
        "",
        f"- Tổng số file đạt production: **{len(ok_reports)}/{len(rows)}**: "
        + ", ".join(row["symbol"] for row in ok_reports)
        + ".",
        f"- Đạt gate theo statement: **B01 {statement_gate_counts['B01']}/{len(rows)}**; "
        f"**B02 {statement_gate_counts['B02']}/{len(rows)}**; "
        f"**B03 {statement_gate_counts['B03']}/{len(rows)}**.",
        "- File chính xác/tin cậy nhất theo tiêu chí bảo thủ là các file vừa đạt gate, vừa không có xung đột và có độ phủ/khớp bằng chứng cao.",
        f"- File yếu nhất về khớp bằng chứng số là **{weakest_pair_name}**; "
        f"file yếu nhất về độ phủ là **{weakest_coverage_name}**.",
        "",
        "## Cách đọc các chỉ số",
        "",
        "- `Độ phủ thấp nhất/trung bình`: tỷ lệ chỉ tiêu có đủ giá trị ở cả kỳ hiện tại và kỳ trước, tính trên B01/B02/B03. Giá trị thấp nhất cho biết phần yếu nhất của file.",
        "- `Khớp kỳ + giá trị thấp nhất/trung bình`: tỷ lệ khớp chính xác cả kỳ và giá trị với bộ dữ liệu đối chiếu v2; đây là mức độ khớp của bằng chứng số.",
        "- `Khớp tên + kỳ + giá trị thấp nhất`: yêu cầu khớp thêm tên chỉ tiêu, nên chặt hơn và có thể giảm khi nguồn dùng tên/alias khác nhau.",
        "- Các tỷ lệ trên **không phải accuracy tuyệt đối do con người xác nhận**. Baseline được tạo có hỗ trợ của parser; production gate vẫn ưu tiên xung đột, dòng chưa xác định, lỗi đối chiếu công thức và độ phủ.",
        "- Điểm bảo thủ dùng để xếp hạng lấy giá trị thấp hơn giữa độ phủ thấp nhất và mức khớp kỳ + giá trị thấp nhất; không dùng điểm này để tự động bỏ qua gate.",
        "",
        "## Cách đọc nguyên nhân trong từng file",
        "",
        "- `Kỳ hiện tại chỉ có X/Y nhóm dòng có giá trị`: Y là số nhóm được dùng làm mẫu kiểm tra, X là số nhóm có giá trị ở kỳ đó; phần thiếu là Y-X, không phải phần trăm lỗi chung của toàn bộ báo cáo.",
        "- Nếu báo cáo ghi `các dòng đã được nhận diện và gắn mã` thì parser đã tìm thấy dòng và mã chuẩn; tỷ lệ thấp đến từ việc dòng đó không có giá trị ở kỳ tương ứng trong kết quả parse. Cần đối chiếu Markdown gốc để kết luận nguồn thiếu hay cách trình bày làm mất kỳ.",
        "- Nếu ghi `dòng chỉ giữ theo nguồn` thì dòng có trong tài liệu nhưng chưa nối được vào schema chuẩn; đây là giới hạn schema hoặc cần bổ sung mapping, không được tự động coi là parser đọc sai.",
        "- Nếu ghi `không tìm thấy dòng có cấu trúc phù hợp` thì statement không được nhận diện đủ từ bố cục nguồn; đây là lỗi nhận diện cấu trúc hoặc nguồn/Markdown quá lệch mẫu, cần review riêng.",
        "- Nếu ghi `đối chiếu công thức không khớp` thì giá trị tổng trên báo cáo không bằng phép tính lại từ các dòng thành phần; đây là cảnh báo về giá trị/mapping/dấu, không phải chỉ báo coverage.",
        "",
        "## Nhóm tốt nhất",
        "",
            "| File | Trạng thái | Độ phủ thấp nhất | Khớp kỳ + giá trị thấp nhất | Khớp tên + kỳ + giá trị thấp nhất | Số cảnh báo | Nhận định |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in sorted(ok_reports, key=lambda item: item["rank"]):
        lines.append(
            f"| {row['symbol']} | {display_status(row['overall_status'])} | {pct(row['coverage_min'])} | "
            f"{pct(row['pair_min'])} | {pct(row['label_min'])} | {row['issue_total']} | {row['assessment']} |"
        )

    def add_rank_section(title: str, selected: list[dict[str, Any]], key: str) -> None:
        lines.extend(["", f"## {title}", "", "| File | Chỉ số | Độ phủ thấp nhất | Khớp kỳ + giá trị thấp nhất | Số cảnh báo | Nguyên nhân chính |", "|---|---:|---:|---:|---:|---|"])
        for row in selected:
            value = row[key]
            shown_value = str(value) if key == "issue_total" else pct(value)
            lines.append(
                f"| {row['symbol']} | {shown_value} | {pct(row['coverage_min'])} | "
                f"{pct(row['pair_min'])} | {row['issue_total']} | {row['reasons'] or 'Không có'} |"
            )

    add_rank_section("10 file yếu nhất về độ phủ", weakest_coverage, "coverage_min")
    add_rank_section("10 file yếu nhất về khớp bằng chứng số", weakest_pair, "pair_min")
    add_rank_section("10 file có nhiều lỗi nội bộ nhất", conflict_heavy, "issue_total")

    lines.extend(
        [
            "",
            "## Bảng đánh giá từng file",
            "",
            "`Độ phủ B01/B02/B03` có dạng `kỳ hiện tại/kỳ trước`. Ví dụ `90%/80%` nghĩa là kỳ hiện tại có 90% chỉ tiêu được lấy giá trị, còn kỳ trước có 80%. `Khớp giá trị số` là tỷ lệ khớp cả kỳ và giá trị; `Khớp nhãn` là tỷ lệ khớp thêm cả tên chỉ tiêu.",
            "",
            "| Hạng | File | Trạng thái | B01 độ phủ | B02 độ phủ | B03 độ phủ | Độ phủ thấp nhất/trung bình | Khớp kỳ + giá trị thấp nhất/trung bình | Khớp tên + kỳ + giá trị thấp nhất | Số cảnh báo | Đánh giá |",
            "|---:|---|---|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['rank']} | {row['symbol']} | {display_status(row['overall_status'])} | "
            f"{row['B01_coverage']} | {row['B02_coverage']} | {row['B03_coverage']} | "
            f"{pct(row['coverage_min'])}/{pct(row['coverage_avg'])} | "
            f"{pct(row['pair_min'])}/{pct(row['pair_avg'])} | {pct(row['label_min'])} | "
            f"{row['issue_total']} | {row['assessment']} |"
        )

    lines.extend(["", "## Kết quả chi tiết từng file", ""])
    for row in rows:
        lines.extend(
            [
                f"### {row['rank']}. {row['symbol']} — {row['assessment']}",
                "",
                f"- File: `{row['file']}`; trạng thái tổng thể: **{display_status(row['overall_status'])}**; "
                f"kiểm tra toàn vẹn nguồn: **{row['source_hash']}**; "
                f"năm báo cáo không nhất quán: **{'có' if row['year_conflict'] else 'không'}**.",
                f"- B01: **{display_status(row['B01_status'])}**, độ phủ "
                f"(kỳ hiện tại/kỳ trước) `{row['B01_coverage']}`, khớp kỳ + giá trị "
                f"`{pct(row['B01_pair_rate'])}`, khớp tên + kỳ + giá trị "
                f"`{pct(row['B01_label_rate'])}`, số cặp kỳ/giá trị chưa khớp "
                f"`{row['B01_missing_pairs']}`. Giải thích: "
                f"{row['B01_explanation']}",
                f"- B02: **{display_status(row['B02_status'])}**, độ phủ "
                f"(kỳ hiện tại/kỳ trước) `{row['B02_coverage']}`, khớp kỳ + giá trị "
                f"`{pct(row['B02_pair_rate'])}`, khớp tên + kỳ + giá trị "
                f"`{pct(row['B02_label_rate'])}`, số cặp kỳ/giá trị chưa khớp "
                f"`{row['B02_missing_pairs']}`. Giải thích: "
                f"{row['B02_explanation']}",
                f"- B03: **{display_status(row['B03_status'])}**, độ phủ "
                f"(kỳ hiện tại/kỳ trước) `{row['B03_coverage']}`, khớp kỳ + giá trị "
                f"`{pct(row['B03_pair_rate'])}`, khớp tên + kỳ + giá trị "
                f"`{pct(row['B03_label_rate'])}`, số cặp kỳ/giá trị chưa khớp "
                f"`{row['B03_missing_pairs']}`. Giải thích: "
                f"{row['B03_explanation']}",
                f"- Tổng hợp: độ phủ thấp nhất/trung bình "
                f"`{pct(row['coverage_min'])}/{pct(row['coverage_avg'])}`, "
                f"khớp kỳ + giá trị thấp nhất/trung bình "
                f"`{pct(row['pair_min'])}/{pct(row['pair_avg'])}`, "
                f"khớp tên + kỳ + giá trị thấp nhất `{pct(row['label_min'])}`, "
                f"tổng số cặp kỳ/giá trị chưa khớp `{row['missing_pairs']}`, "
                f"số cảnh báo `{row['issue_total']}`.",
                f"- Nguyên nhân hoặc lý do bị chặn: {row['reasons'] or 'Không có.'}",
                f"- Kết luận: {file_conclusion(row)}",
                "",
            ]
        )

    lines.extend(
        [
            "",
            "## Nguyên nhân chính của các file yếu",
            "",
            "- Các file có nhiều cảnh báo nhất theo kết quả audit hiện tại:",
            *dynamic_issue_lines,
            "- Tỷ lệ khớp được tính từ bộ dữ liệu đối chiếu có hỗ trợ parser; không được dùng một mình để kết luận production nếu vẫn còn xung đột, thiếu độ phủ hoặc nguồn mơ hồ.",
            "",
            "## Artifact chi tiết",
            "",
            "- Bảng CSV máy đọc: `current_evaluation_by_file.csv`.",
            "- JSON đầy đủ: `current_evaluation_by_file.json`.",
            "- So sánh evidence gốc/eligible: xem các file JSON trong thư mục audit.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument(
        "--sources",
        type=Path,
        default=Path("md_reports"),
        help="Thư mục Markdown nguồn dùng để giải thích nguyên nhân thiếu kỳ.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/evaluations/current_evaluation_report_vi.md"),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("output/evaluations/current_evaluation_by_file.csv"),
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("output/evaluations/current_evaluation_by_file.json"),
    )
    args = parser.parse_args()

    rows = build_rows(args.comparison, args.manifest, args.audit_dir, args.sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.json.parent.mkdir(parents=True, exist_ok=True)

    args.output.write_text(
        markdown_report(rows, args.comparison, args.manifest, args.audit_dir),
        encoding="utf-8",
    )
    json_rows = {
        "schema_version": "current_evaluation_by_file_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparison": str(args.comparison),
        "manifest": str(args.manifest),
        "audit_dir": str(args.audit_dir),
        "reports": rows,
    }
    args.json.write_text(
        json.dumps(json_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fields = [
        "rank", "symbol", "file", "overall_status", "source_hash", "year_conflict",
        "B01_status", "B01_coverage", "B01_pair_rate", "B01_label_rate", "B01_missing_pairs", "B01_explanation",
        "B02_status", "B02_coverage", "B02_pair_rate", "B02_label_rate", "B02_missing_pairs", "B02_explanation",
        "B03_status", "B03_coverage", "B03_pair_rate", "B03_label_rate", "B03_missing_pairs", "B03_explanation",
        "coverage_min", "coverage_avg", "pair_min", "pair_avg", "label_min", "label_avg",
        "missing_pairs", "issue_total", "semantic_dedup_conflicts", "source_recovery_conflicts",
        "formula_failed", "unmapped_rows", "ambiguous_source_nodes", "unresolved", "conservative_score",
        "assessment", "reasons",
    ]
    with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps({
        "reports": len(rows),
        "production_ok": sum(row["overall_status"] == "ok" for row in rows),
        "markdown": str(args.output),
        "csv": str(args.csv),
        "json": str(args.json),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
