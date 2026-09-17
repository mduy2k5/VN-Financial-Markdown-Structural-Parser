"""Reporting-period inference for source-first pipeline runs.

The low-level statement parsers still accept explicit years because they are
also useful as standalone libraries.  The batch pipeline, however, must not
silently apply one hard-coded year pair to every Markdown report.  This module
provides the document-level resolver used at that boundary.
"""

from __future__ import annotations

from datetime import date, timedelta
import re
import unicodedata
from collections import Counter
from typing import Any


YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
REPORT_CUE_RE = re.compile(
    r"(?i)(?:"
    r"năm\s+(?:tài\s+chính|báo\s+cáo)|nam\s+(?:tai\s+chinh|bao\s+cao)|"
    r"cho\s+năm\s+tài\s+chính|cho\s+nam\s+tai\s+chinh|"
    r"kết\s+thúc|ket\s+thuc|"
    r"31\s*[./-]\s*12|31\s+tháng\s+12|31\s+thang\s+12|"
    r"tại\s+ngày|tai\s+ngay|"
    r"số\s+cuối\s+năm|so\s+cuoi\s+nam|"
    r"năm\s+nay|nam\s+nay"
    r")"
)
ADMIN_CUE_RE = re.compile(
    r"(?i)(?:ngày\s+lập|ngay\s+lap|ngày\s+tạo|ngay\s+tao|"
    r"ngày\s+phát\s+hành|ngay\s+phat\s+hanh|"
    r"created|updated|audit|kiểm toán|kiem toan|"
    r"giấy phép|giay phep|thông tư|thong tu|circular)"
)


def _fold(value: Any) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("đ", "d").replace("Đ", "D").casefold()
    return " ".join(re.sub(r"[^a-z0-9./:-]+", " ", text).split())


def _score_text_years(text: str) -> Counter[int]:
    """Score years by nearby reporting cues, while down-weighting metadata."""

    scores: Counter[int] = Counter()
    lines = text.splitlines()
    for line in lines:
        folded = _fold(line)
        years = [int(match) for match in YEAR_RE.findall(line)]
        if not years:
            continue
        has_report_cue = bool(REPORT_CUE_RE.search(folded))
        has_admin_cue = bool(ADMIN_CUE_RE.search(folded))
        for year in years:
            # A reporting cue is strong evidence.  A bare year in a statement
            # heading is useful but weaker; administrative dates are retained
            # only as a low-weight fallback and cannot outrank report cues.
            if has_report_cue and not has_admin_cue:
                scores[year] += 12
            elif has_report_cue:
                scores[year] += 4
            elif not has_admin_cue:
                scores[year] += 2
            else:
                scores[year] += 0.25
    return scores


# ---------------------------------------------------------------------------
# Fiscal-period enrichment
# ---------------------------------------------------------------------------

FISCAL_END_CUE_RE = re.compile(
    r"(?i)(?:năm\s+(?:tài\s+chính|báo\s+cáo)|nam\s+(?:tai\s+chinh|bao\s+cao)|"
    r"cho\s+năm\s+(?:tài\s+chính|báo\s+cáo)|cho\s+nam\s+(?:tai\s+chinh|bao\s+cao))"
    r".{0,80}(?:kết\s+thúc|ket\s+thuc|cuối\s+năm|cuoi\s+nam)",
)
END_CUE_RE = re.compile(
    r"(?i)(?:kết\s+thúc|ket\s+thuc|cuối\s+năm|cuoi\s+nam|cuối\s+kỳ|cuoi\s+ky|"
    r"số\s+cuối\s+năm|so\s+cuoi\s+nam|tại\s+ngày|tai\s+ngay)"
)
OPENING_CUE_RE = re.compile(
    r"(?i)(?:đầu\s+năm|dau\s+nam|đầu\s+kỳ|dau\s+ky|số\s+đầu\s+năm|"
    r"so\s+dau\s+nam|bắt\s+đầu|bat\s+dau|opening|beginning)"
)
QUARTER_CUE_RE = re.compile(r"(?i)(?:quý\s+[ivx]+|quy\s+[ivx]+|quarter|q[1-4])")
YTD_CUE_RE = re.compile(r"(?i)(?:lũy\s+kế|luỹ\s+kế|luy\s+ke|cumulative|year\s+to\s+date|\bytd\b)")

DATE_PATTERNS = (
    re.compile(
        r"(?P<day>0?[1-9]|[12]\d|3[01])\s*[./-]\s*"
        r"(?P<month>0?[1-9]|1[0-2])\s*[./-]\s*(?P<year>20\d{2})"
    ),
    re.compile(
        r"(?i)(?:ngày|ngay)\s+(?P<vday>0?[1-9]|[12]\d|3[01])\s+"
        r"(?:tháng|thang)\s+(?P<vmonth>0?[1-9]|1[0-2])\s+"
        r"(?:năm|nam)\s+(?P<vyear>20\d{2})"
    ),
    re.compile(
        r"(?P<iyear>20\d{2})\s*[./-]\s*(?P<imonth>0?[1-9]|1[0-2])"
        r"\s*[./-]\s*(?P<iday>0?[1-9]|[12]\d|3[01])"
    ),
)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _date_from_match(match: re.Match[str]) -> date | None:
    groups = match.groupdict()
    if groups.get("day"):
        day, month, year = int(groups["day"]), int(groups["month"]), int(groups["year"])
    elif groups.get("vday"):
        day, month, year = int(groups["vday"]), int(groups["vmonth"]), int(groups["vyear"])
    else:
        day, month, year = int(groups["iday"]), int(groups["imonth"]), int(groups["iyear"])
    return _safe_date(year, month, day)


def _date_candidates(text: str) -> list[dict[str, Any]]:
    """Collect dated evidence while discounting administrative dates."""

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for line_no, line in enumerate(str(text or "").splitlines(), start=1):
        folded = _fold(line)
        has_admin = bool(ADMIN_CUE_RE.search(folded))
        has_report = bool(REPORT_CUE_RE.search(folded))
        has_fiscal_end = bool(FISCAL_END_CUE_RE.search(folded))
        has_end = bool(END_CUE_RE.search(folded))
        has_opening = bool(OPENING_CUE_RE.search(folded))
        is_table = "|" in line

        for pattern in DATE_PATTERNS:
            for match in pattern.finditer(line):
                parsed = _date_from_match(match)
                if parsed is None:
                    continue
                key = (line_no, match.start(), parsed.isoformat())
                if key in seen:
                    continue
                seen.add(key)

                # Day-one dates are usually opening/start dates.  Explicit
                # beginning text takes precedence over a generic date header.
                opening = has_opening or parsed.day == 1
                end_candidate = not opening and (
                    has_fiscal_end or has_end or is_table or parsed.day >= 28
                )
                if not end_candidate and not opening:
                    continue

                weight = 1.0
                if has_fiscal_end:
                    weight += 100.0
                if has_end:
                    weight += 40.0
                if has_report:
                    weight += 8.0
                if is_table:
                    weight += 12.0
                if parsed.day == 31 and parsed.month == 12:
                    weight += 15.0
                if opening:
                    weight += 6.0
                if has_admin:
                    weight = max(0.25, weight * 0.08)

                candidates.append(
                    {
                        "date": parsed,
                        "role": "opening" if opening else "end",
                        "weight": round(weight, 2),
                        "line": line_no,
                        "text": line.strip(),
                        "admin": has_admin,
                    }
                )
    return candidates


def _best_date(
    candidates: list[dict[str, Any]],
    *,
    role: str,
    before: date | None = None,
    month_day: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    grouped: dict[date, float] = {}
    for item in candidates:
        if item.get("role") != role:
            continue
        value = item.get("date")
        if not isinstance(value, date):
            continue
        if before is not None and value >= before:
            continue
        if month_day is not None and (value.month, value.day) != month_day:
            continue
        grouped[value] = grouped.get(value, 0.0) + float(item.get("weight") or 0.0)
    if not grouped:
        return None
    # For a comparative period, temporal adjacency is more reliable than
    # repetition count: an old legal/template date may occur many more times
    # than the actual prior-year statement date.  The current end-date choice
    # still uses evidence weight; a `before` query always chooses the latest
    # compatible date.
    if before is not None:
        chosen = max(grouped, key=lambda value: (value, grouped[value]))
    else:
        chosen = max(grouped, key=lambda value: (grouped[value], value))
    evidence = [x for x in candidates if x.get("role") == role and x.get("date") == chosen]
    return {"date": chosen, "weight": round(grouped[chosen], 2), "evidence": evidence[:12]}


def _date_year_back(value: date) -> date:
    return _safe_date(value.year - 1, value.month, value.day) or date(value.year - 1, 2, 28)


def _period_type(text: str) -> str:
    # Only inspect the report header.  Annual notes can mention “lũy kế” in a
    # movement description without being a YTD report.
    folded = _fold("\n".join(str(text or "").splitlines()[:100]))
    if YTD_CUE_RE.search(folded) and QUARTER_CUE_RE.search(folded):
        return "ytd"
    if QUARTER_CUE_RE.search(folded):
        return "quarter"
    return "annual"


def infer_report_period_context(
    text: str,
    *,
    source_name: str = "",
    current_year: int | None = None,
    previous_year: int | None = None,
    allow_unknown: bool = False,
) -> dict[str, Any]:
    """Return years plus normalized dates, confidence, and conflicts.

    Parser roles use the calendar year of the statement end date.  A filename
    year that differs from it is retained as a fiscal-label candidate rather
    than being silently treated as the same concept.
    """

    # Reuse the original year-scoring implementation above, but enrich its
    # result instead of creating a second independent resolver.
    resolved = _infer_year_pair_by_scores(
        text,
        source_name=source_name,
        current_year=current_year,
        previous_year=previous_year,
        allow_unknown=allow_unknown,
    )
    filename_years = resolved["filename_years"]
    explicit_current = bool(resolved.get("explicit_current_year"))
    explicit_previous = bool(resolved.get("explicit_previous_year"))
    candidates = _date_candidates(text)
    best_end = _best_date(candidates, role="end")
    end_date = best_end["date"] if best_end and isinstance(best_end.get("date"), date) else None
    strong_end = bool(best_end and best_end["weight"] >= 60)

    # Strong “financial year ended …” evidence outranks the filename.  A weak
    # table-header date is used only when it agrees with the year score.
    if end_date is not None and not explicit_current and (
        strong_end or resolved["current_year"] == end_date.year
    ):
        resolved["current_year"] = end_date.year
        if not explicit_previous:
            prior_end = _best_date(
                candidates,
                role="end",
                before=end_date,
                month_day=(end_date.month, end_date.day),
            )
            if prior_end and prior_end["date"].year != end_date.year - 1:
                prior_end = None
            resolved["previous_year"] = prior_end["date"].year if prior_end else end_date.year - 1

    current_year = resolved["current_year"]
    previous_year = resolved["previous_year"]
    prior_end = None
    if end_date is not None and current_year == end_date.year:
        prior_end = _best_date(
            candidates,
            role="end",
            before=end_date,
            month_day=(end_date.month, end_date.day),
        )
        if prior_end and prior_end["date"].year != end_date.year - 1:
            prior_end = None
    previous_end_date = prior_end["date"] if prior_end else (_date_year_back(end_date) if end_date else None)
    current_start_date = previous_end_date + timedelta(days=1) if previous_end_date else None
    previous_start_date = _date_year_back(current_start_date) if current_start_date else None

    conflict_reasons: list[str] = []
    if filename_years and current_year is not None and max(filename_years) != current_year:
        conflict_reasons.append("filename_year_differs_from_statement_end_year")
    if explicit_current and end_date is not None and current_year != end_date.year:
        conflict_reasons.append("explicit_year_differs_from_statement_end_year")
    if current_year is not None and previous_year is not None and previous_year != current_year - 1:
        conflict_reasons.append("non_consecutive_year_pair")

    fiscal_year_label = current_year
    fiscal_label_source = "statement_end_year" if end_date else "year_scores"
    if len(set(filename_years)) == 1 and current_year is not None and filename_years[0] != current_year:
        fiscal_year_label = filename_years[0]
        fiscal_label_source = "filename_conflict_candidate"

    evidence = []
    for item in sorted(
        candidates,
        key=lambda x: (float(x.get("weight") or 0), x.get("date")),
        reverse=True,
    )[:20]:
        evidence.append(
            {
                "date": item["date"].isoformat(),
                "role": item["role"],
                "weight": item["weight"],
                "line": item["line"],
                "text": item["text"],
                "administrative": item["admin"],
            }
        )

    if end_date is not None and previous_end_date is not None and strong_end:
        confidence = "high" if not conflict_reasons else "medium"
    elif resolved.get("candidate_scores"):
        confidence = "medium" if not conflict_reasons else "low"
    else:
        confidence = "unknown"

    if (
        strong_end
        and not explicit_current
        and end_date is not None
        and (not filename_years or max(filename_years) != end_date.year)
    ):
        resolved["method"] = "statement_end_date"

    resolved.update(
        {
            "period_type": _period_type(text),
            "current_end_date": end_date.isoformat() if end_date else None,
            "previous_end_date": previous_end_date.isoformat() if previous_end_date else None,
            "current_start_date": current_start_date.isoformat() if current_start_date else None,
            "previous_start_date": previous_start_date.isoformat() if previous_start_date else None,
            "calendar_end_year": end_date.year if end_date else current_year,
            "fiscal_year_label": fiscal_year_label,
            "fiscal_year_label_source": fiscal_label_source,
            "confidence": confidence,
            "conflict": bool(conflict_reasons),
            "conflict_reasons": conflict_reasons,
            "date_evidence": evidence,
        }
    )
    return resolved


def _infer_year_pair_by_scores(
    text: str,
    *,
    source_name: str = "",
    current_year: int | None = None,
    previous_year: int | None = None,
    allow_unknown: bool = False,
) -> dict[str, Any]:
    """Internal year fallback used by the enriched resolver."""

    explicit_current = current_year is not None
    explicit_previous = previous_year is not None
    scores = _score_text_years(text)
    filename_years = [int(match) for match in YEAR_RE.findall(source_name)]
    if filename_years:
        scores[max(filename_years)] += 24

    if current_year is None:
        if previous_year is not None:
            current_year = previous_year + 1
        elif scores:
            current_year = max(scores, key=lambda year: (scores[year], year))
        elif filename_years:
            current_year = max(filename_years)
        elif not allow_unknown:
            raise ValueError(
                f"Cannot infer current reporting year for {source_name or 'document'}; "
                "provide --current-year explicitly."
            )

    if previous_year is None and current_year is not None:
        prior_candidates = [year for year in scores if current_year - 2 <= year < current_year]
        previous_year = max(
            prior_candidates,
            key=lambda year: (scores[year], year),
            default=current_year - 1,
        )

    if current_year is not None and previous_year is not None and previous_year >= current_year:
        raise ValueError(
            f"Invalid reporting period for {source_name or 'document'}: "
            f"current={current_year}, previous={previous_year}."
        )

    if explicit_current and explicit_previous:
        method = "explicit_cli"
    elif explicit_current or explicit_previous:
        method = "mixed_cli_and_derived"
    elif filename_years and max(filename_years) == current_year:
        method = "filename_and_source_cues"
    elif filename_years:
        method = "filename_anchor"
    else:
        method = "source_cues" if scores else "unknown"

    return {
        "current_year": current_year,
        "previous_year": previous_year,
        "method": method,
        "explicit_current_year": explicit_current,
        "explicit_previous_year": explicit_previous,
        "filename_years": sorted(set(filename_years)),
        "candidate_scores": {str(year): scores[year] for year in sorted(scores)},
    }


def infer_report_year_pair(
    text: str,
    *,
    source_name: str = "",
    current_year: int | None = None,
    previous_year: int | None = None,
    allow_unknown: bool = False,
) -> dict[str, Any]:
    """Backward-compatible name for :func:`infer_report_period_context`."""

    return infer_report_period_context(
        text,
        source_name=source_name,
        current_year=current_year,
        previous_year=previous_year,
        allow_unknown=allow_unknown,
    )


def resolve_report_years(
    text: str,
    *,
    source_name: str = "",
    current_year: int | None = None,
    previous_year: int | None = None,
) -> dict[str, Any]:
    """Resolve optional parser arguments without a fixed 2025/2024 fallback."""

    # The document boundary already resolved and persisted the full context.
    # Lower-level parsers receive both years explicitly, so rescanning a large
    # Markdown document in every engine would only add latency and could not
    # improve the supplied decision.
    if current_year is not None and previous_year is not None:
        return {
            "current_year": current_year,
            "previous_year": previous_year,
            "method": "explicit_function_arguments",
            "explicit_current_year": True,
            "explicit_previous_year": True,
            "filename_years": [],
            "candidate_scores": {},
            "period_type": "annual",
            "current_end_date": None,
            "previous_end_date": None,
            "current_start_date": None,
            "previous_start_date": None,
            "calendar_end_year": current_year,
            "fiscal_year_label": current_year,
            "fiscal_year_label_source": "explicit_function_arguments",
            "confidence": "explicit",
            "conflict": False,
            "conflict_reasons": [],
            "date_evidence": [],
        }

    return infer_report_period_context(
        text,
        source_name=source_name,
        current_year=current_year,
        previous_year=previous_year,
        allow_unknown=True,
    )
