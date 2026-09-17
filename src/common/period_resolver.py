"""Small shared policy for assigning explicit statement dates to periods.

The document-level year resolver lives in :mod:`report_period`.  This module
only contains the date-to-role policy used by source recovery and Notes.
"""

from __future__ import annotations


def period_role_for_date(
    day: int,
    month: int,
    year: int,
    current_year: int | None,
    previous_year: int | None,
) -> str | None:
    """Map a source date to ``current`` or ``previous``.

    Parser years are calendar years of statement end dates, not necessarily
    December years. A day-one opening date is comparative evidence even when
    it falls in the current calendar year.
    """

    if current_year is not None and year == current_year:
        if day == 1:
            return "previous"
        return "current"
    if previous_year is not None and year == previous_year:
        return "previous"
    return None
