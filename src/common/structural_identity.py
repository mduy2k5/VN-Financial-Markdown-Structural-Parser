"""Identity cấu trúc cho observation nguồn.

Mã báo cáo và tham chiếu thuyết minh là metadata nguồn. Chúng hữu ích trong
output audit nhưng không phải identity semantic ổn định: OCR có thể tách chúng,
cùng mã có thể xuất hiện ở schedule khác và tham chiếu thuyết minh thuộc tầng
tài liệu khác. Module này cung cấp identity dùng khi giữ hoặc reconcile dòng nguồn.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def clean_identity_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[*_`#]+", "", text)
    return re.sub(r"\s+", " ", text).strip(" |:\t\r\n")


def normalize_identity_label(value: Any) -> str:
    text = clean_identity_text(value)
    text = re.sub(r"^\s*(?:\d+|[ivxlcdm]+)\s*[.)-]\s*", "", text, flags=re.I)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def structural_identity(
    *,
    statement: str,
    label: Any,
    section: Any = "",
    parent_label: Any = "",
    hierarchy_path: Any = "",
    occurrence_rank: int | None = None,
) -> tuple[str, ...]:
    """Trả về tuple identity nguồn không phụ thuộc mã.

    Chỉ dùng ``occurrence_rank`` khi cùng nhãn chuẩn hóa xuất hiện nhiều lần
    trong cùng context cấu trúc. Cố ý không đưa mã và tham chiếu thuyết minh vào.
    """

    context = hierarchy_path or parent_label or ""
    rank = "" if occurrence_rank is None else str(int(occurrence_rank))
    return (
        clean_identity_text(statement).upper(),
        normalize_identity_label(section),
        normalize_identity_label(context),
        normalize_identity_label(label),
        rank,
    )


def occurrence_rank(
    seen: dict[tuple[str, ...], int],
    *,
    statement: str,
    label: Any,
    section: Any = "",
    parent_label: Any = "",
    hierarchy_path: Any = "",
) -> int:
    """Gán rank bắt đầu từ một cách xác định mà không dùng mã nguồn."""

    base = structural_identity(
        statement=statement,
        label=label,
        section=section,
        parent_label=parent_label,
        hierarchy_path=hierarchy_path,
    )
    seen[base] = seen.get(base, 0) + 1
    return seen[base]
