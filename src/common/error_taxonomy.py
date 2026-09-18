"""Taxonomy chỉ dành cho audit của các dòng chưa đến được node semantic.

Taxonomy cố ý dựa trên cấu trúc và text có thể quan sát. Nó không dùng tên
report, mã cổ phiếu, mã báo cáo hay tham chiếu thuyết minh làm khóa identity.
Mục đích là đo được thay đổi parser tiếp theo: hàng đợi review có thể phân biệt
khoảng thiếu semantic thật với footer trang hoặc artifact co sập cột.
"""

from __future__ import annotations

from collections import Counter
import re
import unicodedata
from typing import Any, Iterable


REASON_STRUCTURAL_NOISE = "STRUCTURAL_NOISE"
REASON_PERIOD_INCOMPLETE = "PERIOD_VALUE_INCOMPLETE"
REASON_COLUMN_COLLAPSE = "COLUMN_MAJOR_COLLAPSE"
REASON_LABEL_NORMALIZATION = "LABEL_NORMALIZATION_GAP"
REASON_DUPLICATE = "DUPLICATE_OBSERVATION"
REASON_AMBIGUOUS = "AMBIGUOUS_MAPPING"
REASON_SEMANTIC_GAP = "SEMANTIC_MAPPING_GAP"


def _fold(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _is_structural_noise(label: str) -> bool:
    if not label:
        return True
    if label in {"trong do", "dien giai", "chi tieu", "ma so", "thuyet minh"}:
        return True
    if re.match(r"^(?:page|trang)\s*:?\s*\d+(?:\s*[-/]\s*\d+)?$", label):
        return True
    if re.match(r"^(?:ngay|date)\s*:?\s*\d{1,2}\b", label):
        return True
    if re.match(r"^m\s+s\s+d\s+n\b", label):
        return True
    if label.startswith((
        "nguoi lap", "ke toan truong", "tong giam doc", "pho tong giam doc",
        "chu tich", "ky ten", "ban hanh theo", "cac thuyet minh",
        "thuyet minh bao cao", "bao cao tai chinh", "don vi tinh",
        "thanh pho ", "chuc vu ", "bang ket qua ", "dien giai bao cao ",
        "ngan hang nha nuoc ",
        "bao cao ket qua ",
    )):
        return True
    if re.search(r"\b(?:tong giam doc|pho tong giam doc|ke toan truong|nguoi lap bieu|giam doc tai chinh|chuc vu)\s*$", label):
        return True
    if label.startswith(("theo ", "phuong phap", "tiep theo")):
        return True

    # Báo cáo bị làm phẳng có thể nối tên người ký hoặc địa chỉ vào dòng vẫn có
    # token số. Dùng heuristic ngôn ngữ thận trọng thay vì danh sách người/công
    # ty: nhãn kế toán thường có một marker semantic, còn tên ngắn toàn chữ thì
    # không. Các loại trừ giữ heading chung như "Theo phương pháp ..." và
    # "Một chỉ tiêu mới" ở đúng nhóm taxonomy thay vì xem chúng là tên.
    if re.fullmatch(r"[a-z]+(?: [a-z]+){1,7}", label):
        accounting_markers = (
            "doanh thu", "chi phi", "loi nhuan", "thue", "tai san",
            "co phieu", "co dong", "tien", "luu chuyen", "hoat dong",
            "du phong", "hang ton", "von", "no phai", "phai tra",
            "lai", "gia tri", "dich vu", "bao hiem", "ngan hang",
            "khoan", "thu nhap", "chi tieu", "so huu", "dau tu",
            "tang", "giam", "thay doi", "nhan vien", "quan ly",
            "cong ty", "cung cap", "ban hang", "giao dich", "khac",
        )
        heading_markers = (
            "theo ", "phuong phap", "tiep theo", "nam ", "ky ",
            "cac chi tieu", "don vi ",
        )
        if label.startswith(heading_markers):
            return True
        if not any(marker in label for marker in accounting_markers):
            return True
    return False


def _looks_column_collapsed(label: str, pattern: str) -> bool:
    if "column_major" in pattern or "plain_text_code" in pattern:
        if len(label) >= 80 or re.search(r"\bma\s+so\b", label):
            return True
    # Nhãn dài chứa nhiều khái niệm báo cáo độc lập là tín hiệu mạnh hơn độ dài
    # đơn thuần. Từ vựng này mang tính chung và không gắn với báo cáo cụ thể.
    concepts = (
        "doanh thu", "chi phi", "loi nhuan", "thue", "co dong",
        "co phieu", "tai chinh", "du phong",
    )
    if len(label) >= 130 and sum(token in label for token in concepts) >= 3:
        return True
    return False


def classify_unmapped_row(
    statement: str,
    row: Any,
    *,
    duplicate: bool = False,
) -> dict[str, Any]:
    """Phân loại lý do thận trọng cho một dòng chưa map."""

    label = _fold(_field(row, "label", _field(row, "source_label", "")))
    current = _field(row, "current")
    previous = _field(row, "previous")
    pattern = str(_field(row, "pattern", "") or _field(row, "pattern_id", "") or "")
    mapping_status = str(_field(row, "mapping_status", "unmapped") or "unmapped")
    signals: list[str] = []

    if mapping_status == "ambiguous":
        reason, severity = REASON_AMBIGUOUS, "high"
    elif _is_structural_noise(label):
        reason, severity = REASON_STRUCTURAL_NOISE, "low"
        signals.append("administrative_or_header_text")
    elif _looks_column_collapsed(label, pattern):
        reason, severity = REASON_COLUMN_COLLAPSE, "high"
        signals.append("long_or_multi-concept_label")
    elif re.match(r"^(?:dien giai|ghi chu|chi tieu|ma so|thuyet minh)\s*:", label):
        reason, severity = REASON_LABEL_NORMALIZATION, "medium"
        signals.append("field_prefix_in_label")
    elif duplicate:
        reason, severity = REASON_DUPLICATE, "medium"
        signals.append("same_semantic_signature_repeated")
    elif current is None or previous is None:
        reason, severity = REASON_PERIOD_INCOMPLETE, "medium"
        signals.append("one_primary_period_missing")
    else:
        reason, severity = REASON_SEMANTIC_GAP, "medium"
        signals.append("value_pair_present_without_catalog_match")

    return {
        "reason_code": reason,
        "severity": severity,
        "signals": signals,
        "statement": statement,
    }


def build_error_taxonomy(
    statement: str,
    rows: Iterable[Any],
    *,
    limit: int = 40,
) -> dict[str, Any]:
    """Tóm tắt các dòng chưa map cho output audit và ưu tiên review."""

    materialized = list(rows or [])
    candidates = [
        row for row in materialized
        if str(_field(row, "mapping_status", "unmapped") or "unmapped") != "mapped"
    ]

    signatures = Counter(
        (
            _fold(_field(row, "label", _field(row, "source_label", ""))),
            _field(row, "current"),
            _field(row, "previous"),
            _field(row, "section"),
        )
        for row in candidates
    )

    examples: list[dict[str, Any]] = []
    by_reason: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    for row in candidates:
        label = _field(row, "label", _field(row, "source_label", ""))
        signature = (
            _fold(label),
            _field(row, "current"),
            _field(row, "previous"),
            _field(row, "section"),
        )
        diagnosis = classify_unmapped_row(
            statement,
            row,
            duplicate=signatures[signature] > 1,
        )
        by_reason[diagnosis["reason_code"]] += 1
        by_severity[diagnosis["severity"]] += 1
        if len(examples) >= limit:
            continue
        if isinstance(row, dict):
            item = dict(row)
        else:
            item = {
                key: getattr(row, key)
                for key in (
                    "label", "source_label", "current", "previous", "section",
                    "code", "statement_code", "note", "note_ref", "source_line",
                    "pattern", "pattern_id", "mapping_status",
                )
                if hasattr(row, key)
            }
        if "label" not in item:
            item["label"] = label
        item.update(diagnosis)
        examples.append(item)

    return {
        "unmapped_total": len(candidates),
        "by_reason": dict(sorted(by_reason.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "examples": examples,
    }


def empty_error_taxonomy() -> dict[str, Any]:
    return {"unmapped_total": 0, "by_reason": {}, "by_severity": {}, "examples": []}
