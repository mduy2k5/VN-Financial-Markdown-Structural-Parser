"""Reusable quality rules for source-grounded statement baselines.

The persisted baselines are useful evidence, but they are not automatically a
gold standard.  This module classifies individual observations without knowing
the report ticker or filename.  It deliberately separates:

* observations eligible for a primary current/prior-period comparison; and
* observations that need adjudication because their period, label, scope, or
  source evidence is ambiguous.

The rules are structural and year-agnostic.  A caller may pass the report's
years explicitly, otherwise they are inferred from the baseline evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable


UNKNOWN_PERIODS = {"", "unknown", "unk", "n/a", "na", "none", "null"}
CURRENT_CUES = (
    "current",
    "closing",
    "ending",
    "so cuoi nam",
    "cuoi nam",
    "nam nay",
    "ky nay",
)
PREVIOUS_CUES = (
    "prior",
    "previous",
    "opening",
    "beginning",
    "so dau nam",
    "dau nam",
    "nam truoc",
    "ky truoc",
)
QUARTER_CUES = ("quy i", "quy ii", "quy iii", "quy iv", "quarter")
NON_PRIMARY_WINDOW_CUES = (
    "luy ke",
    "cumulative",
    "year to date",
    "ytd",
)
PLACEHOLDER_LABELS = {
    "chi tieu",
    "ma so",
    "ma",
    "stt",
    "thuyet minh",
    "dien giai",
    "noi dung",
    "nam nay",
    "nam truoc",
    "ky nay",
    "ky truoc",
}


def fold_text(value: Any) -> str:
    text = str(value or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.lower())
    return " ".join(text.split())


def normalize_label(value: Any) -> str:
    """Normalize a statement label consistently for baseline/current comparison.

    Numbered/lettered bullet prefixes and statement form-code suffixes are
    presentation structure, not label identity.  Baselines produced from OCR
    frequently preserve ``C NỢ PHẢI TRẢ 300 310 330`` while the canonical parser
    keeps only ``NỢ PHẢI TRẢ``.  Period markers are intentionally handled
    elsewhere, so this function only removes structural label noise.
    """
    label = fold_text(value)
    if re.search(r"[a-z]", label):
        label = re.sub(r"^(?:\d+(?:\.\d+)*\s+)+", "", label).strip()
        # Form sections such as ``A. Tài sản`` / ``C. Nợ phải trả`` and roman
        # section markers are not semantic row identity.
        label = re.sub(r"^(?:[a-z]|[ivxlcdm]{1,4})\s+(?=[a-z])", "", label).strip()
        # Explicit form-code/note markers are unambiguous structural suffixes.
        label = re.sub(r"\s+(?:ma so|ma tham chieu|thuyet minh)\b.*$", "", label).strip()
        # Many OCR baselines detach one or more numeric form codes from the
        # label.  Strip only a trailing numeric run after a textual label.
        label = re.sub(r"\s+(?:\d+[a-z]?)(?:\s+\d+[a-z]?)*$", "", label).strip()
        # Note references often survive as ``261 13 b`` / ``8 c`` after
        # punctuation is folded away.  They are not part of the statement row.
        label = re.sub(r"\s+\d+(?:\s+\d+)?\s+[a-z]$", "", label).strip()
        label = re.sub(r"\s+(?:chuyen sang trang sau|continued|tiep theo)\b.*$", "", label).strip()
    return label


def parse_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text or text in {"-", "—", "–", "..."}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif "," in text:
        head, tail = text.rsplit(",", 1)
        if len(tail) <= 2:
            text = head.replace(",", "") + "." + tail
        else:
            text = text.replace(",", "")
    try:
        result: int | float = float(text) if "." in text else int(text)
    except ValueError:
        return None
    return -result if negative and result > 0 else result


def infer_year_pair(
    document: dict[str, Any],
    *,
    source_text: str | None = None,
) -> tuple[int | None, int | None]:
    """Infer reporting years from statement-period evidence, not audit metadata.

    The old implementation scanned every `raw_text`/`value_raw` field and then
    selected the numerically largest year.  A publication date such as 2026 could
    therefore override a statement whose reporting periods were 2025/2024.  This
    implementation only scores observation period fields, skips administrative
    rows, and uses the source filename only as a low-priority fallback.
    """

    # Current-run canonical artifacts and newly built baselines carry the
    # document resolver's decision.  Reuse it before scanning labels or the
    # filename; otherwise the evaluator can apply a different policy than the
    # runtime (notably for a March year-end whose filename says the prior year).
    def explicit_period_pair(obj: dict[str, Any]) -> tuple[int | None, int | None] | None:
        containers = [
            obj.get("period_context"),
            obj.get("year_resolution"),
            obj.get("period"),
            obj.get("periods"),
            obj.get("provenance"),
        ]
        for container in containers:
            if not isinstance(container, dict):
                continue
            nested = container.get("year_resolution")
            if isinstance(nested, dict):
                containers.insert(0, nested)
            current = container.get("current_year", container.get("current"))
            previous = container.get("previous_year", container.get("previous"))
            try:
                current = int(current) if current is not None else None
                previous = int(previous) if previous is not None else None
            except (TypeError, ValueError):
                continue
            if current is not None:
                return current, previous if previous is not None else current - 1
        return None

    if isinstance(document, dict):
        explicit = explicit_period_pair(document)
        if explicit is not None:
            return explicit
        if source_text:
            try:
                from .report_period import infer_report_year_pair

                resolved = infer_report_year_pair(
                    source_text,
                    source_name=str(document.get("source_file") or ""),
                    allow_unknown=True,
                )
                if resolved.get("current_year") is not None:
                    return resolved.get("current_year"), resolved.get("previous_year")
            except (ImportError, ValueError):
                # Keep the structural baseline fallback below available for
                # callers that do not have a complete source document.
                pass

    years: Counter[int] = Counter()
    statement_years: set[int] = set()
    metadata_labels = {
        "ngay", "ngay lap", "ngay tao", "ngay cap", "date", "created at",
        "updated at", "page", "so trang", "dia diem", "noi lap", "noi dung",
    }

    def is_metadata_label(value: Any) -> bool:
        label = fold_text(value)
        return (
            label in metadata_labels
            or label.startswith("created at ")
            or label.startswith("updated at ")
            or label.startswith("page ")
            or label.startswith("so trang ")
        )

    def add_period_years(value: Any, weight: int) -> None:
        text = str(value or "")
        if not text:
            return
        # Only count years attached to a reporting-period/date marker.  This
        # avoids treating a free-text publication/audit date as a report year.
        marker = re.search(
            r"(?i)(?:năm|nam|31\s*[./-]\s*12\s*[./-]|01\s*[./-]\s*01\s*[./-]|"
            r"ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm|20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2})",
            text,
        )
        if not marker:
            return
        for match in re.findall(r"\b(20\d{2})\b", text):
            year = int(match)
            years[year] += weight
            statement_years.add(year)

    def visit_statement(statement: dict[str, Any]) -> None:
        for row in statement.get("rows") or []:
            if is_metadata_label(row.get("label")):
                continue
            for observation in row.get("observations") or []:
                period_key = str(observation.get("period_key") or "").strip()
                if re.fullmatch(r"20\d{2}(?:[-/.]\d{1,2}[-/.]\d{1,2})?", period_key):
                    year = int(period_key[:4])
                    years[year] += 10
                    statement_years.add(year)
                add_period_years(observation.get("period_raw"), 5)
                add_period_years(observation.get("raw_text"), 2)

    statements = document.get("statements") if isinstance(document, dict) else None
    if isinstance(statements, dict):
        for statement in statements.values():
            if isinstance(statement, dict):
                visit_statement(statement)
    elif isinstance(document, dict) and isinstance(document.get("rows"), list):
        visit_statement(document)

    # The source filename is a document-level reporting-year anchor.  Prefer it
    # when present, but derive the comparative year from statement evidence so a
    # filename-only report still follows the normal current/prior convention.
    filename_years: list[int] = []
    if isinstance(document, dict):
        source_file = str(document.get("source_file") or "")
        filename_years = [int(match) for match in re.findall(r"(?<!\d)(20\d{2})(?!\d)", source_file)]
    if filename_years:
        current_year = max(filename_years)
        # Legal/template references can contain much older years (for example
        # a circular issued in 2014).  A comparative financial period should be
        # close to the document year; otherwise fall back to the normal prior
        # year instead of treating a legal reference as the comparison period.
        prior_candidates = [
            year for year in statement_years
            if current_year - 2 <= year < current_year
        ]
        previous_year = max(prior_candidates) if prior_candidates else current_year - 1
        return current_year, previous_year

    ordered = sorted(years, key=lambda year: (years[year], year), reverse=True)
    if not ordered:
        return None, None
    return ordered[0], ordered[1] if len(ordered) > 1 else ordered[0] - 1


def period_role(value: Any, current_year: int | None = None, previous_year: int | None = None) -> str:
    """Normalize a period marker to current, previous, quarter, or unknown."""

    role = fold_text(value)
    if role in UNKNOWN_PERIODS:
        return "unknown"
    # A quarterly statement can expose both the quarter window and a cumulative
    # year-to-date window.  The latter is not interchangeable with the primary
    # current/prior pair used by the canonical schema, even when its period key
    # was flattened to `current`/`prior` by an upstream parser.
    if any(cue in role for cue in NON_PRIMARY_WINDOW_CUES):
        return "quarter"
    years = [int(item) for item in re.findall(r"\b(20\d{2})\b", role)]
    # 01/01/current_year is the opening balance and therefore the prior
    # comparative period.  Check the date before the generic year test.
    if re.search(r"\b01\s+01\b", role):
        return "previous"
    if re.search(r"\b31\s+12\b|\b12\s+31\b", role):
        return "current" if current_year and str(current_year) in role else "previous"
    if current_year is not None and current_year in years:
        return "current"
    if previous_year is not None and previous_year in years:
        return "previous"
    if any(cue in role for cue in CURRENT_CUES):
        return "current"
    if any(cue in role for cue in PREVIOUS_CUES):
        return "previous"
    if any(cue in role for cue in QUARTER_CUES):
        return "quarter"
    return "unknown"


def observation_period(
    observation: dict[str, Any],
    current_year: int | None = None,
    previous_year: int | None = None,
) -> str:
    """Resolve period_key first, then raw evidence when key is unknown."""

    candidates = (
        observation.get("period_key"),
        observation.get("period_role"),
        observation.get("role"),
        observation.get("period_raw"),
        observation.get("raw_text"),
    )
    fallback = "unknown"
    primary_role: str | None = None
    saw_non_primary = False
    for candidate in candidates:
        role = period_role(candidate, current_year, previous_year)
        if role == "quarter":
            saw_non_primary = True
            continue
        if role in {"current", "previous"}:
            primary_role = primary_role or role
            continue
        if role != "unknown":
            fallback = role
    if saw_non_primary:
        return "quarter"
    if primary_role is not None:
        return primary_role
    return fallback


def period_evidence_conflict(
    observation: dict[str, Any],
    current_year: int | None = None,
    previous_year: int | None = None,
) -> bool:
    """Return whether explicit key and raw period evidence disagree."""

    key_role = period_role(observation.get("period_key"), current_year, previous_year)
    if key_role not in {"current", "previous"}:
        return False
    for candidate in (observation.get("period_raw"), observation.get("raw_text")):
        raw_role = period_role(candidate, current_year, previous_year)
        if raw_role in {"current", "previous"} and raw_role != key_role:
            return True
    return False


def is_placeholder_label(value: Any) -> bool:
    label = fold_text(value)
    if not label or label in PLACEHOLDER_LABELS:
        return True
    if re.fullmatch(r"(?:20\d{2})(?:\s+(?:vnd|dong|trieu))?", label):
        return True
    if re.fullmatch(r"(?:nam|ky|quy)\s+20\d{2}(?:\s+.*)?", label):
        return True
    if re.fullmatch(r"[0-9]+(?:\s+[0-9]+)*", label):
        return True
    if label in {
        "vnd", "trieu vnd", "trieu dong", "ma thuyet so minh",
        "nam hien tai", "nam truoc", "nam nay", "ky nay", "ky truoc",
    }:
        return True
    if label.startswith((
        "nam bao cao", "nam nay", "nam truoc", "ky nay", "ky truoc",
        "quy i", "quy ii", "quy iii", "quy iv", "luy ke tu dau nam",
        "so cuoi nam", "so dau nam", "ngay 01 thang", "ngay 31 thang",
        "stt chi tieu", "chi tieu ",
    )):
        return True
    if label.startswith("nam ket thuc ") or label.startswith("ky ket thuc "):
        return True
    return False


def source_period_hint(
    source_lines: list[str] | None,
    source_line: int,
    current_year: int | None,
    previous_year: int | None,
    *,
    lookback: int = 90,
) -> str | None:
    """Infer a row's section year from the nearest explicit source heading."""

    if not source_lines or source_line <= 0 or source_line > len(source_lines):
        return None
    start = max(0, source_line - 1 - lookback)
    for raw in reversed(source_lines[start:source_line - 1]):
        folded = fold_text(raw)
        match = re.search(r"\bnam bao cao\s*:?[ ]*(20\d{2})\b", folded)
        if match:
            return period_role(match.group(1), current_year, previous_year)
        if re.search(r"\bnam nay\b", folded) and len(folded.split()) <= 5:
            return "current"
        if re.search(r"\bnam truoc\b", folded) and len(folded.split()) <= 5:
            return "previous"
    return None


def extract_inline_period_values(
    raw_text: Any,
    current_year: int | None,
    previous_year: int | None,
    leading_value: Any = None,
) -> list[tuple[str, int | float]]:
    """Recover a compact current/prior pair from one inline source row.

    Example: ``67.231.128 triệu đồng (Năm 2024: 61.748.921)``.  The persisted
    baseline can contain only one observation for this row and occasionally
    assigns the leading value to the parenthesized year.  Recovery is limited
    to explicit year/value syntax and therefore does not guess from arbitrary
    numbers in a label.
    """

    text = str(raw_text or "")
    if not text or current_year is None or previous_year is None:
        return []
    value_token = r"[\-–—(]?\d[\d.,]*(?:\))?"
    pairs: list[tuple[str, int | float]] = []

    def parse_inline_number(token: Any) -> int | float | None:
        text = str(token or "").strip()
        # Vietnamese statement rows use dots/commas as thousands separators;
        # a single three-digit group (``1.934``) is still 1,934, not 1.934.
        if re.fullmatch(r"\(?-?\d{1,3}(?:[.,]\d{3})+\)?", text):
            negative = text.startswith("(") or text.startswith("-")
            digits = re.sub(r"[^0-9]", "", text)
            value = int(digits) if digits else None
            return -value if value is not None and negative else value
        return parse_number(text)

    for match in re.finditer(
        rf"(?i)\b(?:năm|nam)\s*(20\d{{2}})\s*:\s*({value_token})",
        text,
    ):
        year = int(match.group(1))
        value = parse_inline_number(match.group(2))
        if value is None or year not in {current_year, previous_year}:
            continue
        pairs.append(("current" if year == current_year else "previous", value))

    date_pattern = re.compile(
        rf"(?i)({value_token})\s*(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*"
        rf"\(\s*(\d{{1,2}})[./-](\d{{1,2}})[./-](20\d{{2}})\s*\)"
    )
    for match in date_pattern.finditer(text):
        value = parse_inline_number(match.group(1))
        if value is None:
            continue
        day = int(match.group(2)); month = int(match.group(3)); year = int(match.group(4))
        if year == current_year and day == 31 and month == 12:
            pairs.append(("current", value))
        elif year == current_year and day == 1 and month == 1:
            pairs.append(("previous", value))
        elif year == previous_year and day == 31 and month == 12:
            pairs.append(("previous", value))

    if pairs and not any(period == "current" for period, _ in pairs):
        before = text[: next(
            (m.start() for m in re.finditer(r"(?i)\b(?:năm|nam)\s*20\d{2}\s*:", text)),
            len(text),
        )]
        # Use only the first numeric value after the row's first colon.  This
        # avoids treating a form code in the label as the current observation.
        lead_match = re.search(rf":\s*({value_token})", before)
        if lead_match:
            lead = parse_inline_number(leading_value)
            if lead is None:
                lead = parse_inline_number(lead_match.group(1))
            if lead is not None:
                pairs.insert(0, ("current", lead))
    # A date/year pair is authoritative; do not let an erroneous baseline code
    # observation (for example value ``112`` from ``Mã số: 112``) survive.
    unique: list[tuple[str, int | float]] = []
    for item in pairs:
        if item not in unique:
            unique.append(item)
    return unique


@dataclass(frozen=True)
class ObservationDecision:
    eligible: bool
    period: str
    value: int | float | None
    reasons: tuple[str, ...]


def assess_observation(
    row: dict[str, Any],
    observation: dict[str, Any],
    *,
    current_year: int | None = None,
    previous_year: int | None = None,
    source_line_text: str | None = None,
    manual_review_required: bool = False,
) -> ObservationDecision:
    reasons: list[str] = []
    value = parse_number(observation.get("value"))
    if value is None:
        reasons.append("non_numeric_value")

    label = row.get("label")
    if is_placeholder_label(label):
        reasons.append("placeholder_or_shifted_label")

    period = observation_period(observation, current_year, previous_year)
    if period not in {"current", "previous"}:
        reasons.append("non_primary_period")
    elif period_evidence_conflict(observation, current_year, previous_year):
        reasons.append("period_evidence_conflict")

    try:
        source_line = int(observation.get("source_line"))
    except (TypeError, ValueError):
        source_line = 0
    if source_line <= 0:
        reasons.append("missing_source_line")
    if source_line_text is not None:
        raw_text = str(observation.get("raw_text") or "").strip()
        if not raw_text:
            reasons.append("missing_raw_evidence")
        elif source_line_text.strip() != raw_text:
            reasons.append("source_line_mismatch")

    if manual_review_required:
        reasons.append("baseline_manual_review_required")

    return ObservationDecision(
        eligible=not reasons,
        period=period,
        value=value,
        reasons=tuple(sorted(set(reasons))),
    )


def evidence_key(row: dict[str, Any], decision: ObservationDecision) -> tuple[str, str, int | float]:
    return (normalize_label(row.get("label")), decision.period, decision.value)  # type: ignore[arg-type]


def iter_observations(statement: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for row in statement.get("rows") or []:
        for observation in row.get("observations") or []:
            yield row, observation
