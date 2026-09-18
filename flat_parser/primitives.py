from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .guide import UniversalGuide
from .models import PrimitivePeriod, PrimitiveValue
from .textnorm import fold


DASHES = {"-", "–", "—", "−"}

# Regex fallback rộng bổ sung cho nhóm regex trong guide nguồn.
DATE_PATTERNS = [
    re.compile(r"(?i)(?:Tại ngày\s+)?\d{1,2}[./]\d{1,2}[./]\d{4}"),
    re.compile(r"(?i)(?:Ngày\s+)?\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+20\d{2}"),
    re.compile(r"(?i)(?:Cho\s+)?Năm tài chính kết thúc ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+20\d{2}"),
]
RELATIVE_PERIOD_RE = re.compile(
    r"(?i)\b(?:"
    r"Số cuối năm|Số đầu năm|"
    r"Năm nay|Năm trước|"
    r"Cuối năm|Đầu năm|"
    r"Dư nợ cuối năm|Dư nợ đầu năm|"
    r"Năm\s+20\d{2}"
    r")\b"
)
YEAR_RE = re.compile(r"\b20\d{2}\b")
UNIT_FALLBACK_RE = re.compile(
    r"(?i)(?:"
    r"triệu\s+(?:đồng|VND)|"
    r"tỷ\s+(?:đồng|VND)|"
    r"nghìn\s+(?:đồng|VND)|"
    r"VND/cổ\s*phiếu|đồng/cổ\s*phiếu|"
    r"%/năm|%|"
    r"\bVND\b|\bVNĐ\b|\bUSD\b|\bEUR\b|"
    r"\bđồng\b|\bcổ\s+phiếu\b|\bcổ\s+phần\b"
    r")"
)
RANGE_TOKEN_RE = re.compile(
    r"(?<![\w./])\d+(?:,\d+)?\s*-\s*\d+(?:,\d+)?(?![\w./])"
)

VALUE_TOKEN_RE = re.compile(
    r"(?<![\w./])"
    r"(\(?-?\d{1,3}(?:\.\d{3})+(?:,\d+)?\)?"
    r"|\(?-?\d+(?:,\d+)?\)?"
    r"|[-–—])"
    r"(?![\w./])"
)


def extract_unit(text: str, guide: UniversalGuide) -> str | None:
    for _, rx in guide.unit_regexes:
        m = rx.search(text)
        if m:
            return m.group(0)
    m = UNIT_FALLBACK_RE.search(text)
    return m.group(0) if m else None


def _normalize_number(raw: str) -> Decimal | None:
    s = raw.strip().replace("−", "-")
    if s in DASHES:
        return None

    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1].strip()

    s = s.replace(" ", "")
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) >= 2 and all(p.isdigit() for p in parts if p != ""):
            if all(len(p) == 3 for p in parts[1:]):
                s = "".join(parts)
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            s = s.replace(",", ".")
        elif len(parts) >= 2 and all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)

    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    if negative and value > 0:
        value = -value
    return value


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(max(0, a), min(len(chars), b)):
            chars[i] = " "
    return "".join(chars)


def extract_periods(text: str, line_no: int, guide: UniversalGuide) -> list[PrimitivePeriod]:
    matches = []

    for _, rx in guide.period_regexes:
        for m in rx.finditer(text):
            matches.append((m.start(), m.end(), m.group(0)))

    for rx in DATE_PATTERNS:
        for m in rx.finditer(text):
            matches.append((m.start(), m.end(), m.group(0)))

    for m in RELATIVE_PERIOD_RE.finditer(text):
        matches.append((m.start(), m.end(), m.group(0)))

    # Loại các span gần trùng bị chồng lấn, ưu tiên span dài hơn.
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    kept = []
    for item in matches:
        if any(not (item[1] <= k[0] or item[0] >= k[1]) for k in kept):
            continue
        kept.append(item)

    result = []
    for _, _, raw in kept:
        f = fold(raw)
        role = None
        if any(x in f for x in ("so cuoi nam", "cuoi nam", "du no cuoi nam", "nam nay")):
            role = "current"
        elif any(x in f for x in ("so dau nam", "dau nam", "du no dau nam", "nam truoc")):
            role = "previous"

        result.append(
            PrimitivePeriod(
                raw_period=raw,
                normalized=f,
                role=role,
                line_no=line_no,
            )
        )
    return result


def whole_text_period(text: str, line_no: int, guide: UniversalGuide) -> PrimitivePeriod | None:
    stripped = text.strip()
    periods = extract_periods(stripped, line_no, guide)
    if not periods:
        return None

    unit = extract_unit(stripped, guide)
    cleaned = stripped
    if unit:
        cleaned = cleaned.replace(unit, " ")
    cleaned = cleaned.strip(" ():-")

    for p in periods:
        candidate = cleaned.replace(p.raw_period, " ").strip(" ():-")
        if not candidate:
            return p
    return None


def extract_values(
    text: str,
    line_no: int,
    guide: UniversalGuide,
    *,
    mask_periods: bool = True,
) -> list[PrimitiveValue]:
    # Dấu gạch hiển thị là giá trị nguồn rõ ràng, không phải dữ liệu thiếu.
    # Giữ ở raw_value với normalized_candidate=None.
    stripped = text.strip()
    if stripped in DASHES:
        return [
            PrimitiveValue(
                raw_value=stripped,
                normalized_candidate=None,
                line_no=line_no,
                unit=extract_unit(text, guide),
                is_dash=True,
            )
        ]

    work = text
    if mask_periods:
        # Tag năm inline như "(2025)" / "(2024)" là nhãn kỳ, không phải
        # giá trị tài chính âm.
        year_parens = list(re.finditer(r"\(\s*20\d{2}\s*\)", work))
        if year_parens:
            work = _mask_spans(work, [(m.start(), m.end()) for m in year_parens])

        spans = []
        for p in extract_periods(text, line_no, guide):
            start = work.find(p.raw_period)
            if start >= 0:
                spans.append((start, start + len(p.raw_period)))
        work = _mask_spans(work, spans)

    values = []
    occupied = []

    # Giữ khoảng số dùng dấu phẩy thập phân như "5,20 - 9,60" thành một giá trị cấu trúc.
    for m in RANGE_TOKEN_RE.finditer(work):
        raw = text[m.start():m.end()].strip()
        values.append(
            PrimitiveValue(
                raw_value=raw,
                normalized_candidate=None,
                line_no=line_no,
                unit=extract_unit(text[max(0, m.start()-20):m.end()+40], guide),
            )
        )
        occupied.append((m.start(), m.end()))

    for m in VALUE_TOKEN_RE.finditer(work):
        if any(not (m.end() <= a or m.start() >= b) for a, b in occupied):
            continue
        raw = text[m.start():m.end()].strip()
        if not raw:
            continue

        # Dấu gạch chỉ là giá trị khi toàn bộ field giá trị là dấu gạch.
        # Không xem dấu phân cách hiển thị như "C - NỢ PHẢI TRẢ" là payload số.
        if raw in DASHES:
            continue

        normalized = _normalize_number(raw)
        values.append(
            PrimitiveValue(
                raw_value=raw,
                normalized_candidate=normalized,
                line_no=line_no,
                unit=extract_unit(text[max(0, m.start()-20):m.end()+40], guide),
                is_dash=(raw in DASHES),
            )
        )

    values.sort(key=lambda v: text.find(v.raw_value))
    return values


def explicit_note(text: str, guide: UniversalGuide) -> str | None:
    for _, rx in guide.note_regexes:
        m = rx.search(text)
        if m:
            if m.groups():
                return m.group(1)
            return m.group(0)

    m = re.search(r"(?i)\b(?:Số liệu\s+)?Thuyết\s+minh\s*:\s*([0-9]+(?:\.[0-9]+)*)", text)
    if m:
        return m.group(1)
    m = re.search(r"(?i)\(Thuyết\s+minh\s+([0-9]+(?:\.[0-9]+)*)\)", text)
    return m.group(1) if m else None
