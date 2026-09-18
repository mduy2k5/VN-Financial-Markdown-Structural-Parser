from __future__ import annotations

from typing import Optional

try:
    from ..common.value_semantics import (
        UNIT_BILLION_VND,
        UNIT_MILLION_VND,
        UNIT_SHARE,
        UNIT_THOUSAND_VND,
        UNIT_UNKNOWN,
        UNIT_VND,
        UNIT_VND_PER_SHARE,
        detect_unit,
        fold_text,
    )
except ImportError:
    from common.value_semantics import (
        UNIT_BILLION_VND,
        UNIT_MILLION_VND,
        UNIT_SHARE,
        UNIT_THOUSAND_VND,
        UNIT_UNKNOWN,
        UNIT_VND,
        UNIT_VND_PER_SHARE,
        detect_unit,
        fold_text,
    )


_CANONICAL_UNITS = {
    UNIT_UNKNOWN,
    UNIT_VND,
    UNIT_THOUSAND_VND,
    UNIT_MILLION_VND,
    UNIT_BILLION_VND,
    UNIT_VND_PER_SHARE,
    UNIT_SHARE,
    "percent",
}


def canonical_unit(raw: Optional[str]) -> Optional[str]:
    """Trả về từ vựng đơn vị ổn định mà không đổi độ lớn số.

    Đơn vị raw/hiển thị vẫn nằm trong ``NoteValue.unit``. Helper này chỉ cung
    cấp nhãn semantic có thể so sánh cho đánh giá và liên kết.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in _CANONICAL_UNITS:
        return text
    folded = fold_text(text).replace(" ", "_")
    if folded in _CANONICAL_UNITS:
        return folded
    ctx = detect_unit(text, source="notes_unit_normalization")
    return None if ctx.unit == UNIT_UNKNOWN else ctx.unit
