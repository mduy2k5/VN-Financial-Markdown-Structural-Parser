"""Chính sách dùng chung để gán ngày báo cáo rõ vào các kỳ.

Bộ giải quyết năm ở cấp tài liệu nằm trong :mod:`report_period`. Module này chỉ
chứa chính sách đổi ngày thành role dùng bởi khôi phục nguồn và Notes.
"""

from __future__ import annotations


def period_role_for_date(
    day: int,
    month: int,
    year: int,
    current_year: int | None,
    previous_year: int | None,
) -> str | None:
    """Đổi ngày nguồn thành ``current`` hoặc ``previous``.

    Năm parser là năm lịch của ngày kết thúc báo cáo, không nhất thiết là năm
    tháng 12. Ngày đầu tháng một là evidence so sánh dù nằm trong năm hiện tại.
    """

    if current_year is not None and year == current_year:
        if day == 1:
            return "previous"
        return "current"
    if previous_year is not None and year == previous_year:
        return "previous"
    return None
