from __future__ import annotations

"""Attach source/page/period provenance to Notes without changing raw values.

Notes frequently put the period label in prose immediately before a bullet
tree.  The structural parser intentionally preserves that prose separately,
so numeric leaves can otherwise keep ``period_role=None`` even though the
source clearly says which fiscal year the panel belongs to.  This module adds
that missing provenance as metadata and, when the source contains one explicit
fiscal-year panel, fills missing ``NoteValue.period_*`` fields.  It does not
pair values or rewrite an already identified ``current``/``previous`` value.
"""

import re
from bisect import bisect_right
from typing import Any

from .note_ir import NoteSection
from .structural_parser import _period_role


YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
PAGE_HEADING_RE = re.compile(r"^\s*#\s*Page\s+(?P<page>\d+)\s*$", re.I)
PAGE_METADATA_RE = re.compile(
    r"^\s*-\s*(?:\*\*|__)?\s*page\s*(?:\*\*|__)?\s*:\s*"
    r"(?:\*\*|__)?\s*(?P<page>\d+)\s*(?:\*\*|__)?\s*$",
    re.I,
)
PERIOD_CUE_RE = re.compile(
    r"(?i)(?:"
    r"cho\s+năm|cho\s+nam|"
    r"năm\s+tài\s+chính|nam\s+tai\s+chinh|"
    r"tại\s+ngày|tai\s+ngay|"
    r"ngày\s+31\s+tháng|ngay\s+31\s+thang|"
    r"năm\s+nay|nam\s+nay|năm\s+trước|nam\s+truoc|"
    r"số\s+cuối\s+năm|so\s+cuoi\s+nam"
    r")"
)
FISCAL_PERIOD_CUE_RE = re.compile(
    r"(?i)(?:"
    r"cho\s+năm|cho\s+nam|"
    r"năm\s+tài\s+chính|nam\s+tai\s+chinh|"
    r"năm\s+nay|nam\s+nay|năm\s+trước|nam\s+truoc|"
    r"số\s+cuối\s+năm|so\s+cuoi\s+nam"
    r")"
)


def _clean_markdown(value: str) -> str:
    return re.sub(r"[*_`]+", "", value or "").strip().rstrip(":").strip()


def _page_markers(lines: list[str]) -> list[tuple[int, int]]:
    markers: list[tuple[int, int]] = []
    for line_no, raw in enumerate(lines, start=1):
        match = PAGE_HEADING_RE.match(raw) or PAGE_METADATA_RE.match(raw)
        if match:
            markers.append((line_no, int(match.group("page"))))
    return markers


def _period_markers(
    lines: list[str],
    *,
    current_year: int | None,
    previous_year: int | None,
) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for line_no, raw in enumerate(lines, start=1):
        clean = _clean_markdown(raw)
        if not clean or not PERIOD_CUE_RE.search(clean):
            continue
        role = _period_role(
            clean,
            current_year=current_year,
            previous_year=previous_year,
        )
        if role not in {"current", "previous", "quarter"}:
            continue
        years = sorted({int(x) for x in YEAR_RE.findall(clean)})
        # A table header such as ``2025 | 2024`` describes two columns, not
        # one inherited panel.  Do not choose the last year and accidentally
        # label the entire following tree with the wrong period.
        if len(years) > 1:
            continue
        date_year = years[0] if years else None
        is_fiscal_period = bool(FISCAL_PERIOD_CUE_RE.search(clean))
        fiscal_year = date_year if is_fiscal_period else None
        markers.append({
            "line": line_no,
            "label": clean,
            "role": role,
            "period_kind": "fiscal_year" if is_fiscal_period else "point_in_time",
            "fiscal_year": fiscal_year,
            "date_year": date_year,
            "method": "explicit_period_marker",
        })
    return markers


def _pages_for_range(
    start_line: int,
    end_line: int,
    page_markers: list[tuple[int, int]],
    page_marker_lines: list[int],
) -> list[int]:
    if not page_markers:
        return []
    start_index = max(0, bisect_right(page_marker_lines, start_line) - 1)
    end_index = max(0, bisect_right(page_marker_lines, end_line) - 1)
    pages = [page for _, page in page_markers[start_index : end_index + 1]]
    if not pages:
        pages = [page_markers[start_index][1]]
    return list(dict.fromkeys(pages))


def _nearest_period(
    start_line: int,
    end_line: int,
    markers: list[dict[str, Any]],
    *,
    lower_bound: int,
) -> dict[str, Any] | None:
    candidates = [
        marker
        for marker in markers
        if lower_bound <= marker["line"] <= end_line
    ]
    if not candidates:
        return None
    # Prefer the last explicit marker in the block/range.  This handles a
    # page header such as 2025 followed by the table's explicit 2024 panel.
    before_start = [marker for marker in candidates if marker["line"] <= start_line]
    return (before_start or candidates)[-1]


def _context(
    start_line: int,
    end_line: int,
    *,
    section_start_line: int,
    page_markers: list[tuple[int, int]],
    page_marker_lines: list[int],
    period_markers: list[dict[str, Any]],
) -> dict[str, Any]:
    pages = _pages_for_range(
        start_line,
        end_line,
        page_markers,
        page_marker_lines,
    )
    # Allow the page/report header immediately before a section, but do not
    # carry a period from an unrelated earlier note across the whole source.
    period = _nearest_period(
        start_line,
        end_line,
        period_markers,
        lower_bound=max(1, section_start_line - 3),
    )
    return {
        "schema": "note_source_context_v1",
        "source_line_start": start_line,
        "source_line_end": end_line,
        "pages": pages,
        "page_start": pages[0] if pages else None,
        "page_end": pages[-1] if pages else None,
        "period": dict(period) if period else None,
        "preservation": {
            "mode": "raw_tree",
            "raw_cells_preserved": True,
            "raw_source_lines_preserved": True,
            "raw_values_unchanged": True,
            "period_inherited_from_explicit_marker": True,
        },
    }


def annotate_source_context(
    sections: list[NoteSection],
    text: str,
    *,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> dict[str, Any]:
    """Annotate Notes blocks/rows with page and nearest period evidence.

    The function preserves raw cells/source lines and only fills missing
    period fields from an explicit single fiscal-year marker. It never changes
    an existing period assignment or creates a synthetic current/prior pair.
    The returned summary is suitable for ``document.diagnostics``.
    """

    lines = text.splitlines()
    page_markers = _page_markers(lines)
    page_marker_lines = [line for line, _ in page_markers]
    period_markers = _period_markers(
        lines,
        current_year=current_year,
        previous_year=previous_year,
    )

    block_count = 0
    row_count = 0
    unresolved_period_blocks = 0
    periods: set[tuple[Any, Any]] = set()

    for section in sections:
        section_periods: list[dict[str, Any]] = []
        for block in section.blocks:
            block_context = _context(
                block.source_start_line,
                block.source_end_line,
                section_start_line=section.source_start_line,
                page_markers=page_markers,
                page_marker_lines=page_marker_lines,
                period_markers=period_markers,
            )
            block.metadata = dict(block.metadata or {})
            block.metadata["source_context"] = block_context
            block_count += 1
            if block_context["period"] is None:
                unresolved_period_blocks += 1
            else:
                period = block_context["period"]
                key = (period.get("role"), period.get("fiscal_year"))
                periods.add(key)
                if key not in {
                    (item.get("role"), item.get("fiscal_year"))
                    for item in section_periods
                }:
                    section_periods.append(period)

            for row in block.rows:
                row_line = row.source_line or block.source_start_line
                row_context = _context(
                    row_line,
                    row_line,
                    section_start_line=section.source_start_line,
                    page_markers=page_markers,
                    page_marker_lines=page_marker_lines,
                    period_markers=period_markers,
                )
                row.metadata = dict(row.metadata or {})
                row.metadata["source_context"] = row_context
                period = row_context.get("period") or {}
                values_without_period = bool(row.values) and all(
                    not value.period_role for value in row.values
                )
                if (
                    values_without_period
                    and period.get("period_kind") == "fiscal_year"
                    and period.get("role") in {"current", "previous"}
                ):
                    for value in row.values:
                        value.period_label = period.get("label")
                        value.period_role = period.get("role")
                    row.metadata["period_assignment"] = {
                        "method": "inherited_explicit_fiscal_marker",
                        "label": period.get("label"),
                        "role": period.get("role"),
                        "fiscal_year": period.get("fiscal_year"),
                        "evidence_line": period.get("line"),
                    }
                row_count += 1

        section.metadata = dict(section.metadata or {})
        section.metadata["source_context"] = {
            "schema": "note_source_context_v1",
            "pages": list(section.pages),
            "periods": section_periods,
            "preservation": "raw_tree",
        }

    return {
        "schema": "note_source_context_v1",
        "block_count": block_count,
        "row_count": row_count,
        "unresolved_period_blocks": unresolved_period_blocks,
        "periods": [
            {"role": role, "fiscal_year": year}
            for role, year in sorted(periods, key=lambda item: (str(item[0]), item[1] or 0))
        ],
        "page_marker_count": len(page_markers),
        "period_marker_count": len(period_markers),
    }
