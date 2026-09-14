from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
import csv
import json
import re
import unicodedata

BULLET_RE = re.compile(r"^(?P<indent>[^\S\r\n]*)\*\s+(?P<body>.*)$")
BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
NUMBER_PREFIX_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)")
ROMAN_PREFIX_RE = re.compile(r"^\s*(?:[IVXLCDM]+)\.\s+", re.I)
NOTE_CHILD_RE = re.compile(r"^(?:Số\s+liệu\s+)?Thuyết\s*minh\s*:\s*(?P<note>.+?)\s*$", re.I)
CODE_CHILD_RE = re.compile(r"^Mã\s+số\s*:\s*(?P<code>.+?)\s*$", re.I)
INDICATOR_CODE_RE = re.compile(r"^Chỉ\s*tiêu\s*:\s*(?P<code>\d+(?:\.\d+)*)\s*$", re.I)
END_YEAR_RE = re.compile(
    r"^Số\s+cuối\s+năm(?:\s*\((?P<unit_hint>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
START_YEAR_RE = re.compile(
    r"^Số\s+đầu\s+năm(?:\s*\((?P<unit_hint>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
CURRENT_YEAR_CHILD_RE = re.compile(r"^Năm\s+nay\s*:\s*(?P<value>.+?)\s*$", re.I)
PREVIOUS_YEAR_CHILD_RE = re.compile(r"^Năm\s+trước\s*:\s*(?P<value>.+?)\s*$", re.I)
DATE_BALANCE_RE = re.compile(
    r"^Số\s+dư\s+tại\s+ngày\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
PERIOD_CONTAINER_RE = re.compile(r"^Ngày\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*:??\s*$", re.I)
INLINE_PERIOD_RE = re.compile(
    r"^(?P<label>.+?)\s*:\s*(?P<current>[^|]+?)\s*\(\s*Cuối\s+năm\s*\)\s*\|\s*(?P<previous>.+?)\s*\(\s*Đầu\s+năm\s*\)\s*$",
    re.I,
)
INLINE_EXPLICIT_YEAR_RE = re.compile(
    r"^(?P<label>.+?)\s*:\s*"
    r"(?P<value1>.+?)\s*\(\s*Năm\s+(?P<year1>20\d{2})\s*\)\s*[,;|]\s*"
    r"(?P<value2>.+?)\s*\(\s*Năm\s+(?P<year2>20\d{2})\s*\)"
    r"(?:\s*[-–—]\s*\*?\*?Thuyết\s*minh\s*:?\s*(?P<note>[^*]+?)\*?\*?)?\s*$",
    re.I,
)

INLINE_EXPLICIT_DATE_RE = re.compile(
    r"^(?P<label>.+?)\s*:\s*"
    r"(?P<value1>.+?)\s*\(\s*(?P<date1>\d{1,2}/\d{1,2}/20\d{2})\s*\)\s*[,;|]\s*"
    r"(?P<value2>.+?)\s*\(\s*(?P<date2>\d{1,2}/\d{1,2}/20\d{2})\s*\)\s*$",
    re.I,
)
INLINE_YEAR_RE = re.compile(
    r"^(?P<label>.+?)\s*:\s*"
    r"(?P<current>.+?)\s*\(\s*Năm\s+nay\s*\)\s*[,;|]\s*"
    r"(?P<previous>.+?)\s*\(\s*Năm\s+trước\s*\)"
    r"(?:\s*[-–—]\s*\*?\*?Thuyết\s*minh\s*:\s*(?P<note>[^*]+?)\*?\*?)?\s*$",
    re.I,
)
NAMED_INDICATOR_RE = re.compile(r"^Chỉ\s*tiêu\s*:\s*(?P<label>.+?)\s*$", re.I)
NOTE_SUFFIX_RE = re.compile(r"^(?P<label>.*?)(?:\s*\(\s*Thuyết\s*minh\s*:?\s*(?P<note>[^)]+?)\s*\))\s*:?\s*$", re.I)
GENERIC_PERIOD_VALUE_RE = re.compile(
    r"^(?:(?:Năm\s+)?(?P<year>20\d{2})|(?:Số\s+dư\s+tại\s+)?(?:ngày\s+)?(?P<date>\d{1,2}/\d{1,2}/20\d{2}))\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
KEY_VALUE_RE = re.compile(r"^(?P<label>.+?)\s*:\s*(?P<value>.+?)\s*$")
UNIT_RE = re.compile(
    r"\b(?P<unit>(?:nghìn|ngàn|triệu|tỷ)\s+(?:đồng|vnd)|(?:đồng|vnd|usd|eur))\b",
    re.I,
)
NUM_RE = re.compile(r"^\(?\s*[-+]?\d[\d.,\s]*\)?$")

CODE_FIRST_RE = re.compile(r"^Mã\s+số\s*:\s*(?P<code>[^:]+?)\s*$", re.I)
INLINE_CODE_LABEL_RE = re.compile(
    r"^Mã\s+số\s+(?P<code>[0-9A-Za-z.]+)\s*[-–—]\s*(?P<label>.+?)\s*:?\s*$",
    re.I,
)
EMBEDDED_CODE_RE = re.compile(
    r"\s*\(\s*Mã\s+số\s*:?\s*(?P<code>[0-9A-Za-z.]+)\s*\)\s*$",
    re.I,
)
VALUE_YEAR_RE = re.compile(
    r"^Giá\s+trị\s+(?P<year>20\d{2})(?:\s*\((?P<qualifier>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
FISCAL_YEAR_DATE_RE = re.compile(
    r"^(?:Năm\s+tài\s+chính\s+kết\s+thúc\s+ngày|Cho\s+năm\s+kết\s+thúc\s+ngày)\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/20\d{2})(?:\s*\((?P<qualifier>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
CURRENT_YEAR_QUALIFIED_RE = re.compile(
    r"^Năm\s+nay(?:\s*\((?P<qualifier>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
PREVIOUS_YEAR_QUALIFIED_RE = re.compile(
    r"^Năm\s+trước(?:\s*\((?P<qualifier>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
INLINE_PAIR_IN_TEXT_RE = re.compile(
    r"^(?P<v1>.+?)\s*\(\s*Năm\s+nay\s*\)\s*[/|;,]\s*"
    r"(?P<v2>.+?)\s*\(\s*Năm\s+trước\s*\)\s*$",
    re.I,
)
YEAR_ONLY_VALUE_RE = re.compile(r"^(?P<year>20\d{2})(?:\s*\((?P<qualifier>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$", re.I)
INLINE_LABEL_DUP_VALUE_RE = re.compile(r"^(?P<label>.+?)\s*:\s*(?P<value>\(?[-\d][\d.,\s]*\)?(?:\s+(?:nghìn|ngàn|triệu|tỷ)?\s*(?:đồng|VND|USD|EUR))?)\s*$", re.I)
COLUMN_CODE_LABEL_RE = re.compile(r"^(?P<code>\d+[A-Za-z]?)\s*:\s*(?P<label>.+?)\s*$")
COLUMN_SECTION_RE = re.compile(r"^(?P<name>Mã\s+số|Thuyết\s*minh|Năm\s+nay|Năm\s+trước)\s*:\s*$", re.I)
ROW_HEADER_YEAR_RE = re.compile(r"^Năm\s+(?P<year>20\d{2})\s*$", re.I)
ROW_DATA_LABEL_RE = re.compile(r"^(?P<ord>(?:\d+|[IVXLCDM]+))\.\s*(?P<label>.+?)\s*$", re.I)
DATE_HEADER_RE = re.compile(r"^(?P<date>\d{1,2}/\d{1,2}/\d{4})(?:\s*\((?P<unit>[^)]+)\))?\s*$", re.I)
ROW_CODE_LABEL_NO_DOT_RE = re.compile(r"^(?P<code>\d{2,3}[A-Za-z]?)\s+(?P<label>.+?)\s*$")
REPORT_YEAR_RE = re.compile(r"^Năm\s+báo\s+cáo\s*:\s*(?P<year>20\d{2})(?:\s*\((?P<unit>[^)]+)\))?\s*$", re.I)
DATA_ONLY_RE = re.compile(r"^Số\s+liệu\s*:\s*(?P<value>.+?)\s*$", re.I)
CODE_NOTE_WRAPPER_RE = re.compile(r"^Mã\s+Thuyết\s+số\s+minh\s*:\s*(?P<code>.+?)\s*$", re.I)
SINGLE_DATE_INLINE_RE = re.compile(
    r"^(?P<label>.+?)\s*:\s*(?P<value>.+?)\s*\(\s*tại\s+ngày\s+(?P<date>\d{1,2}/\d{1,2}/20\d{2})\s*\)\s*$",
    re.I,
)



INLINE_FLEX_DATE_PAIR_RE = re.compile(
    r"^(?P<label>.+?)\s*:\s*"
    r"(?P<v1>.+?)\s*\(\s*(?P<d1>\d{1,2}[./-]\d{1,2}[./-]20\d{2})\s*\)\s*[,;|]\s*"
    r"(?P<v2>.+?)\s*\(\s*(?P<d2>\d{1,2}[./-]\d{1,2}[./-]20\d{2})\s*\)\s*$",
    re.I,
)
INLINE_NOTE_END_START_RE = re.compile(
    r"^(?P<label>.+?)\s*:\s*(?P<note>[^|]+?)\s*\|\s*"
    r"(?P<current>.+?)\s*\(\s*cuối\s+năm\s*\)\s*\|\s*"
    r"(?P<previous>.+?)\s*\(\s*đầu\s+năm\s*\)\s*$",
    re.I,
)
INLINE_IMPLICIT_TWO_VALUES_RE = re.compile(
    r"^(?P<label>(?:\d{2,3}[A-Za-z]?\.\s*)?.+?)\s*:\s*"
    r"(?P<v1>\(?[-+]?\d[\d.,\s]*\)?|-|—)\s*(?:\((?P<u1>[^)]*(?:đồng|VND)[^)]*)\))?\s*,\s*"
    r"(?P<v2>\(?[-+]?\d[\d.,\s]*\)?|-|—)\s*(?:\((?P<u2>[^)]*(?:đồng|VND)[^)]*)\))?\s*$",
    re.I,
)
DATA_RESTATED_RE = re.compile(
    r"^Số\s+liệu(?:\s*\((?P<qualifier>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
PERIOD_VALUE_LABEL_CHILD_RE = re.compile(
    r"^Năm\s+(?P<role>nay|trước)(?:\s*\((?P<meta>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
INLINE_PARENT_CURRENT_RE = re.compile(
    r"^(?P<label>.+?)\s*(?P<code>\(\s*Mã\s+số\s*[^)]+\))\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("đ", "d")
    return re.sub(r"\s+", " ", s).strip()


def _strip_md(text: str) -> str:
    text = text.strip()
    text = BOLD_RE.sub(lambda m: m.group(1), text)
    text = text.replace("__", "").strip()
    return text



def _clean_indicator_and_code(text: str) -> tuple[str, str]:
    """Return semantic label and embedded accounting code, if present."""
    raw = _strip_md(text).strip().rstrip(":").strip()
    code = ""
    m = EMBEDDED_CODE_RE.search(raw)
    if m:
        code = m.group("code").strip()
        raw = raw[:m.start()].rstrip()
    return _clean_label(raw), code


def _clean_label(text: str) -> str:
    text = _strip_md(text).strip()
    text = text.rstrip(":").strip()
    text = NUMBER_PREFIX_RE.sub("", text).strip()
    text = ROMAN_PREFIX_RE.sub("", text).strip()
    return text


def _indent_width(raw: str) -> int:
    width = 0
    for ch in raw:
        width += 4 if ch == "\t" else 1
    return width


def _parse_date(text: str):
    from datetime import datetime
    return datetime.strptime(text.strip(), "%d/%m/%Y").date()


def _split_value_unit(raw: str) -> tuple[str, str]:
    s = _strip_md(raw).strip()
    m = UNIT_RE.search(s)
    unit = m.group("unit").strip() if m else ""
    if m:
        s = (s[:m.start()] + s[m.end():]).strip()
    s = re.sub(r"\s+", " ", s).strip().rstrip(".;")
    # Normalize OCR/serialization artifact such as `(791.924) )`.
    m_extra = re.match(r"^(?P<value>\(\s*[-+]?\d[\d.,\s]*\))\s*\)+$", s)
    if m_extra:
        s = m_extra.group("value")
    return s, unit


def _clean_prefixed_numeric_value(value: str) -> str:
    """Recover numeric payload from compact code/note/value text.

    Example: `35 (Số liệu khác) 163.213.792` -> `163.213.792`.
    This is deliberately narrow and does not use source hierarchy.
    """
    s = _strip_md(value or "").strip()
    m = re.match(r"^\d{1,3}[A-Za-z]?\s+\([^)]{1,80}\)\s+(?P<value>\(?[-+]?\d[\d.,]*\)?)$", s)
    return m.group("value") if m else s


def _year(date_text: str) -> Optional[int]:
    m = re.search(r"(20\d{2})", date_text)
    return int(m.group(1)) if m else None

def _parse_period_value_line(body: str):
    raw = _strip_md(body).strip()

    m = CURRENT_YEAR_QUALIFIED_RE.match(raw)
    if m:
        v,u=_split_value_unit(m.group("value")); return {"role":"current","value":v,"unit":u,"qualifier":m.groupdict().get("qualifier") or ""}
    m = PREVIOUS_YEAR_QUALIFIED_RE.match(raw)
    if m:
        v,u=_split_value_unit(m.group("value")); return {"role":"previous","value":v,"unit":u,"qualifier":m.groupdict().get("qualifier") or ""}
    m = END_YEAR_RE.match(raw)
    if m:
        v,u=_split_value_unit(m.group("value")); u=u or (m.groupdict().get("unit_hint") or "").strip(); return {"role":"current","value":v,"unit":u}
    m = START_YEAR_RE.match(raw)
    if m:
        v,u=_split_value_unit(m.group("value")); u=u or (m.groupdict().get("unit_hint") or "").strip(); return {"role":"previous","value":v,"unit":u}
    m = VALUE_YEAR_RE.match(raw)
    if m:
        y=int(m.group("year")); v,u=_split_value_unit(m.group("value")); return {"role":"dated","date":(y,12,31),"value":v,"unit":u}
    m = re.match(r"^(?:Năm(?:/Year)?|Year)\s*(?P<year>20\d{2})(?:\s*\((?P<qualifier>[^)]+)\))?\s*:\s*(?P<value>.+?)\s*$", raw, re.I)
    if m:
        y=int(m.group("year")); v,u=_split_value_unit(m.group("value")); return {"role":"dated","date":(y,12,31),"value":v,"unit":u}
    m = re.match(r"^(?:Năm\s+tài\s+chính\s+kết\s+thúc\s+ngày|Cho\s+năm\s+kết\s+thúc\s+ngày)\s+(?P<date>.+?)\s*:\s*(?P<value>.+?)\s*$", raw, re.I)
    if m:
        d = _parse_any_date(m.group("date"))
        if d:
            v,u=_split_value_unit(m.group("value")); return {"role":"dated","date":d,"value":v,"unit":u}
    m = YEAR_ONLY_VALUE_RE.match(raw)
    if m:
        y=int(m.group("year")); v,u=_split_value_unit(m.group("value")); return {"role":"dated","date":(y,12,31),"value":v,"unit":u}
    m = re.match(r"^(?:Ngày\s+|Số\s+dư\s+tại\s+ngày\s+)?(?P<date>.+?)\s*:\s*(?P<value>.+?)\s*$", raw, re.I)
    if m:
        d=_parse_any_date(m.group("date"))
        if d:
            v,u=_split_value_unit(m.group("value")); return {"role":"dated","date":d,"value":v,"unit":u}
    return None


def _parse_any_date(text: str):
    m=re.search(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})", text)
    if m:
        d,mo,y=map(int,m.groups()); return (y,mo,d)
    m=re.search(r"(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(20\d{2})", text, re.I)
    if m:
        d,mo,y=map(int,m.groups()); return (y,mo,d)
    m=re.search(r"\b(20\d{2})\b", text)
    if m:
        return (int(m.group(1)),12,31)
    return None


def _resolve_period_obs(obs):
    prev=cur=unit=""; dated=[]
    for o in obs:
        if not o: continue
        unit=unit or o.get("unit","")
        if o.get("role")=="current": cur=o.get("value","")
        elif o.get("role")=="previous": prev=o.get("value","")
        elif o.get("role")=="dated" and o.get("date"): dated.append((o["date"],o.get("value",""),o.get("unit","")))
    if dated:
        dated.sort(key=lambda x:x[0])
        if not prev and len(dated)>=2: prev=dated[0][1]
        if not cur: cur=dated[-1][1]
        unit=unit or dated[-1][2] or dated[0][2]
    return prev,cur,unit


@dataclass
class Line:
    line_no: int
    raw: str
    body: str
    indent: int
    is_bullet: bool


@dataclass
class DebugRow:
    indicator: str
    note: str = ""
    previous: str = ""
    current: str = ""
    unit: str = ""
    pattern_id: str = ""
    source_start_line: int = 0
    source_end_line: int = 0
    confidence: float = 1.0
    raw_lines: list[str] | None = None

    def csv_dict(self) -> dict[str, str]:
        return {
            "Chỉ tiêu": self.indicator,
            "Thuyết minh": self.note,
            "Số năm trước": self.previous,
            "Số năm nay": self.current,
            "Đơn vị": self.unit,
        }

    def debug_dict(self) -> dict:
        return asdict(self)


class BulletDebugFlow:
    """Debug-only extractor for four known star-bullet structural patterns.

    It deliberately does not invoke canonical aliases. Existing alias files remain untouched.
    """

    PATTERN_1 = "P1_LABEL_CHILD_ATTRIBUTES"
    PATTERN_2 = "P2_LABEL_INLINE_PERIOD_VALUES"
    PATTERN_3 = "P3_NAMED_INDICATOR_DATE_CHILDREN"
    PATTERN_4 = "P4_PERIOD_CONTAINER_TREE"
    PATTERN_5 = "P5_LABEL_INLINE_YEAR_VALUES"
    PATTERN_6 = "P6_LABEL_GENERIC_PERIOD_CHILDREN"
    PATTERN_7 = "P7_LABEL_INLINE_EXPLICIT_YEARS"
    PATTERN_8 = "P8_HEADING_ATTRIBUTE_BLOCK"
    PATTERN_9 = "P9_BULLET_COLUMN_MAJOR"
    PATTERN_10 = "P10_FIELD_MAJOR_YEAR_CHILDREN"
    PATTERN_11 = "P11_DATE_HEADER_PAIRED_VALUES"
    PATTERN_12 = "P12_LABEL_INLINE_EXPLICIT_DATES"
    PATTERN_13 = "P13_ROW_MAJOR_HEADER_YEARS"
    PATTERN_14 = "P14_CODE_FIRST_ROW_WRAPPER"
    PATTERN_15 = "P15_CODE_LABEL_INLINE_PERIOD_PAIR"
    PATTERN_16 = "P16_PERIOD_MAJOR_NAM_NAY_NAM_TRUOC"
    PATTERN_17 = "P17_SEMANTIC_PERIOD_WRAPPER"
    PATTERN_18 = "P18_PLAIN_TEXT_INLINE_PERIOD_PAIR"
    PATTERN_19 = "P19_CODE_WRAPPER_MULTI_DESCRIPTION"
    PATTERN_20 = "P20_WRAPPER_MULTI_NAMED_INDICATORS"
    PATTERN_21 = "P21_ROW_MAJOR_IMPLICIT_COLUMNS"
    PATTERN_22 = "P22_REPORT_YEAR_SINGLE_VALUE"
    PATTERN_23 = "P23_CODE_WRAPPER_CHILD_INLINE_PAIR"
    PATTERN_24 = "P24_SINGLE_DATE_INLINE"
    PATTERN_25 = "P25_DATE_HEADER_IMPLICIT_ROWS"
    PATTERN_26 = "P26_LABEL_INLINE_FLEX_DATES"
    PATTERN_27 = "P27_ROW_MAJOR_END_START_HEADER"
    PATTERN_28 = "P28_NESTED_PERIOD_SUBROWS"
    PATTERN_29 = "P29_HEADER_DRIVEN_DATA_PAIR"
    PATTERN_30 = "P30_INLINE_NOTE_END_START"
    PATTERN_31 = "P31_HEADER_INLINE_IMPLICIT_PAIR"
    PATTERN_32 = "P32_PERIOD_VALUE_LABEL_CHILD"
    PATTERN_33 = "P33_LABEL_CHILD_INLINE_PAIR"
    PATTERN_34 = "P34_INLINE_CURRENT_CHILD_PREVIOUS"

    def tokenize(self, text: str) -> list[Line]:
        out: list[Line] = []
        for idx, raw in enumerate(text.splitlines(), start=1):
            m = BULLET_RE.match(raw)
            if m:
                out.append(Line(idx, raw, _strip_md(m.group("body")), _indent_width(m.group("indent")), True))
            else:
                indent = re.match(r"^[^\S\r\n]*", raw).group(0)
                out.append(Line(idx, raw, _strip_md(raw.strip()), _indent_width(indent), False))
        return out

    def extract(self, text: str) -> tuple[list[DebugRow], dict]:
        lines = self.tokenize(text)
        rows: list[DebugRow] = []
        consumed: set[int] = set()
        matches: list[dict] = []


        # P26: inline pair with explicit dates using slash, dot, or dash separators.
        # Example: Label: 1.000 (31.12.2025), 900 (31.12.2024)
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            m = INLINE_FLEX_DATE_PAIR_RE.match(ln.body)
            if not m:
                continue
            d1 = _parse_any_date(m.group("d1")); d2 = _parse_any_date(m.group("d2"))
            if not d1 or not d2:
                continue
            v1,u1 = _split_value_unit(m.group("v1")); v2,u2 = _split_value_unit(m.group("v2"))
            if d1 >= d2:
                cur,prev = v1,v2
            else:
                cur,prev = v2,v1
            row = DebugRow(indicator=_clean_indicator_and_code(m.group("label"))[0],
                           previous=prev,current=cur,unit=u1 or u2,
                           pattern_id=self.PATTERN_26,source_start_line=ln.line_no,
                           source_end_line=ln.line_no,raw_lines=[ln.raw])
            rows.append(row); matches.append(row.debug_dict()); consumed.add(i)

        # P30: optional note/reference is serialized before the explicit end/start values.
        # Example: Chứng khoán kinh doanh: 6.1 | 1.583.614 (cuối năm) | 3.628.250 (đầu năm)
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            m = INLINE_NOTE_END_START_RE.match(ln.body)
            if not m:
                continue
            cur,u1 = _split_value_unit(m.group("current")); prev,u2 = _split_value_unit(m.group("previous"))
            row = DebugRow(indicator=_clean_indicator_and_code(m.group("label"))[0],
                           note=_strip_md(m.group("note")),previous=prev,current=cur,unit=u1 or u2,
                           pattern_id=self.PATTERN_30,source_start_line=ln.line_no,
                           source_end_line=ln.line_no,raw_lines=[ln.raw])
            rows.append(row); matches.append(row.debug_dict()); consumed.add(i)

        # P31: header declares Số cuối năm/Số đầu năm, but each row serializes only two
        # comma-separated values and optionally a code prefix.
        has_end_start_header = (
            any("so cuoi nam" in _norm(x.body) for x in lines if x.body)
            and any("so dau nam" in _norm(x.body) for x in lines if x.body)
        )
        if has_end_start_header:
            for i, ln in enumerate(lines):
                if i in consumed or not ln.is_bullet or not ln.body:
                    continue
                m = INLINE_IMPLICIT_TWO_VALUES_RE.match(ln.body)
                if not m:
                    continue
                v1,u1 = _split_value_unit(m.group("v1")); v2,u2 = _split_value_unit(m.group("v2"))
                label = re.sub(r"^\s*\d{2,3}[A-Za-z]?\.\s*", "", m.group("label")).strip()
                row = DebugRow(indicator=_clean_indicator_and_code(label)[0],
                               previous=v2,current=v1,unit=(m.group("u1") or m.group("u2") or u1 or u2 or "").strip(),
                               pattern_id=self.PATTERN_31,source_start_line=ln.line_no,
                               source_end_line=ln.line_no,raw_lines=[ln.raw])
                rows.append(row); matches.append(row.debug_dict()); consumed.add(i)

        # P27: row-major table governed by STT/CHỈ TIÊU + Thuyết minh +
        # Số cuối năm + Số đầu năm. Empty note cells may disappear.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            header_norm = _norm(ln.body)
            if header_norm not in {"chi tieu", "stt chi tieu"}:
                continue
            j=i+1; cols=[]
            while j < len(lines):
                c=lines[j]
                if c.is_bullet and c.indent <= ln.indent:
                    break
                if c.is_bullet:
                    n=_norm(c.body)
                    if n.startswith("thuyet minh"): cols.append("note")
                    elif n.startswith("so cuoi nam") or n.startswith("nam nay"): cols.append("current")
                    elif n.startswith("so dau nam") or n.startswith("nam truoc"): cols.append("previous")
                j+=1
            if not ("current" in cols and "previous" in cols):
                continue
            consumed.add(i)
            for z in range(i+1,j):
                if lines[z].is_bullet: consumed.add(z)
            r=j
            while r < len(lines):
                rowln=lines[r]
                if not rowln.is_bullet:
                    r+=1; continue
                if rowln.indent < ln.indent:
                    break
                if rowln.indent != ln.indent:
                    r+=1; continue
                if _norm(rowln.body) in {"chi tieu","stt chi tieu"}:
                    break
                k=r+1; desc=[]
                while k<len(lines):
                    x=lines[k]
                    if x.is_bullet and x.indent<=rowln.indent: break
                    if x.is_bullet and x.body: desc.append((k,x))
                    k+=1
                if not desc:
                    r+=1; continue
                mind=min(x.indent for _,x in desc)
                direct=[(idx,x) for idx,x in desc if x.indent==mind]
                cells=[(_strip_md(x.body).strip(),idx) for idx,x in direct]
                note=""; cur=prev=unit=""; used=[]
                # Two cells => current, previous. Three+ => note,current,previous.
                if len(cells)>=2:
                    selected=cells[:3] if len(cells)>=3 else cells[:2]
                    if len(selected)==3:
                        note=selected[0][0]; value_cells=selected[1:3]
                    else:
                        value_cells=selected[:2]
                    v1,u1=_split_value_unit(value_cells[0][0]); v2,u2=_split_value_unit(value_cells[1][0])
                    if (NUM_RE.match(v1) or v1 in {"-","—"}) and (NUM_RE.match(v2) or v2 in {"-","—"}):
                        cur,prev=v1,v2; unit=u1 or u2
                        used=[x[1] for x in selected]
                if cur or prev:
                    row=DebugRow(indicator=_clean_indicator_and_code(rowln.body)[0],note=note,
                                 previous=prev,current=cur,unit=unit,pattern_id=self.PATTERN_27,
                                 source_start_line=rowln.line_no,source_end_line=max(lines[z].line_no for z in used),
                                 raw_lines=[rowln.raw]+[lines[z].raw for z in used])
                    rows.append(row); matches.append(row.debug_dict()); consumed.add(r); consumed.update(used)
                r=k

        # P28: a semantic row contains two dated period nodes, and each period node
        # contains the same sub-row labels. Pivot nested sub-rows by label.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            po1=_parse_period_value_line(ln.body)
            if not po1 or po1.get("role") != "dated":
                continue
            # period node must own at least one direct key:value child
            j=i+1; children1={}
            while j<len(lines):
                c=lines[j]
                if c.is_bullet and c.indent<=ln.indent: break
                if c.is_bullet and c.body:
                    kv=KEY_VALUE_RE.match(c.body)
                    if kv:
                        vv,uu=_split_value_unit(kv.group("value"))
                        if NUM_RE.match(vv) or vv in {"-","—"}:
                            children1[_clean_indicator_and_code(kv.group("label"))[0]]=(vv,uu,j)
                j+=1
            if not children1:
                continue
            # find next sibling period node
            k=j
            while k<len(lines) and not (lines[k].is_bullet and lines[k].indent==ln.indent):
                k+=1
            if k>=len(lines): continue
            po2=_parse_period_value_line(lines[k].body)
            if not po2 or po2.get("role") != "dated":
                continue
            q=k+1; children2={}
            while q<len(lines):
                c=lines[q]
                if c.is_bullet and c.indent<=lines[k].indent: break
                if c.is_bullet and c.body:
                    kv=KEY_VALUE_RE.match(c.body)
                    if kv:
                        vv,uu=_split_value_unit(kv.group("value"))
                        if NUM_RE.match(vv) or vv in {"-","—"}:
                            children2[_clean_indicator_and_code(kv.group("label"))[0]]=(vv,uu,q)
                q+=1
            common=[lab for lab in children1 if lab in children2]
            if not common:
                continue
            first_is_current = po1["date"] >= po2["date"]
            for lab in common:
                v1,u1,z1=children1[lab]; v2,u2,z2=children2[lab]
                cur,prev=(v1,v2) if first_is_current else (v2,v1)
                row=DebugRow(indicator=lab,previous=prev,current=cur,unit=u1 or u2,
                             pattern_id=self.PATTERN_28,source_start_line=ln.line_no,
                             source_end_line=max(lines[z1].line_no,lines[z2].line_no),
                             raw_lines=[ln.raw,lines[z1].raw,lines[k].raw,lines[z2].raw])
                rows.append(row); matches.append(row.debug_dict()); consumed.update({z1,z2})
            # Leave period total nodes themselves available for parent-row patterns.

        # P29: report date headers are outside the row; children are serialized only as
        # "Số liệu:" and "Số liệu (Trình bày lại):".
        has_data_pair_header = (
            re.search(r"Ngày\s+31\s+tháng\s+12\s+năm\s+20\d{2}", text, re.I) is not None
            and "Số liệu" in text and "Trình bày lại" in text
        )
        if has_data_pair_header:
            for i, ln in enumerate(lines):
                if i in consumed or not ln.is_bullet or not ln.body:
                    continue
                if DATA_RESTATED_RE.match(ln.body) or NOTE_CHILD_RE.match(ln.body):
                    continue
                j=i+1; attrs=[]; mind=None
                while j<len(lines):
                    c=lines[j]
                    if c.is_bullet and c.indent<=ln.indent: break
                    if c.is_bullet and c.body:
                        if mind is None: mind=c.indent
                        if c.indent==mind: attrs.append((j,c))
                    j+=1
                note=""; cur=prev=unit=""; used=[]
                data_cells=[]
                for idx,c in attrs:
                    nm=NOTE_CHILD_RE.match(c.body)
                    dm=DATA_RESTATED_RE.match(c.body)
                    if nm:
                        note=_strip_md(nm.group("note")); used.append(idx)
                    elif dm:
                        vv,uu=_split_value_unit(dm.group("value"))
                        if NUM_RE.match(vv) or vv in {"-","—"}:
                            data_cells.append((vv,uu,dm.groupdict().get("qualifier") or "",idx))
                if len(data_cells)>=2:
                    # Unqualified cell is current; qualified/restated cell is previous.
                    for vv,uu,qq,idx in data_cells:
                        if qq:
                            prev=vv
                        elif not cur:
                            cur=vv
                        unit=unit or uu; used.append(idx)
                    if not prev and len(data_cells)>=2: prev=data_cells[1][0]
                    if not cur: cur=data_cells[0][0]
                if cur or prev:
                    row=DebugRow(indicator=_clean_indicator_and_code(ln.body)[0],note=note,
                                 previous=prev,current=cur,unit=unit,pattern_id=self.PATTERN_29,
                                 source_start_line=ln.line_no,source_end_line=max(lines[z].line_no for z in used),
                                 raw_lines=[ln.raw]+[lines[z].raw for z in used])
                    rows.append(row); matches.append(row.debug_dict()); consumed.add(i); consumed.update(used)

        # P32: wrapper note -> period:value -> child semantic label. Pair by repeated label.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            nm=NOTE_CHILD_RE.match(ln.body)
            if not nm:
                continue
            note=_strip_md(nm.group("note"))
            j=i+1; period_nodes=[]
            while j<len(lines):
                p=lines[j]
                if p.is_bullet and p.indent<=ln.indent: break
                if p.is_bullet and p.body:
                    pm=PERIOD_VALUE_LABEL_CHILD_RE.match(p.body)
                    if pm:
                        label_child=None; k=j+1
                        while k<len(lines):
                            c=lines[k]
                            if c.is_bullet and c.indent<=p.indent: break
                            if c.is_bullet and c.body and label_child is None:
                                label_child=(k,_clean_indicator_and_code(c.body)[0])
                            k+=1
                        if label_child:
                            vv,uu=_split_value_unit(pm.group("value"))
                            period_nodes.append((pm.group("role").lower(),vv,uu,j,label_child[0],label_child[1]))
                j+=1
            bylabel={}
            for role,v,u,pidx,lidx,label in period_nodes:
                bylabel.setdefault(label,{})[role]=(v,u,pidx,lidx)
            emitted=False
            for label,d in bylabel.items():
                if "nay" not in d or "trước" not in d:
                    continue
                cv,cu,cp,cl=d["nay"]; pv,pu,pp,pl=d["trước"]
                row=DebugRow(indicator=label,note=note,previous=pv,current=cv,unit=cu or pu,
                             pattern_id=self.PATTERN_32,source_start_line=ln.line_no,
                             source_end_line=max(lines[cl].line_no,lines[pl].line_no),
                             raw_lines=[ln.raw,lines[cp].raw,lines[cl].raw,lines[pp].raw,lines[pl].raw])
                rows.append(row); matches.append(row.debug_dict()); consumed.update({cp,cl,pp,pl}); emitted=True
            if emitted: consumed.add(i)

        # P33: wrapper + child-owned explicit year pair.
        # Flat-flow policy: when the child contains its own semantic label, emit
        # that child label. Do not assign child values to a generic wrapper.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            if NOTE_CHILD_RE.match(ln.body) or CODE_CHILD_RE.match(ln.body):
                continue
            note=""
            ms=re.search(r"\(\s*Thuyết\s*minh\s*:\s*([^)]+)\)",ln.body,re.I)
            label_text=ln.body
            if ms:
                note=ms.group(1).strip()
                label_text=(ln.body[:ms.start()]+ln.body[ms.end():]).strip()
            j=i+1; match_child=None; child_owned_label=False
            while j<len(lines):
                c=lines[j]
                if c.is_bullet and c.indent<=ln.indent: break
                if c.is_bullet and c.body:
                    m=INLINE_EXPLICIT_YEAR_RE.match(c.body)
                    if m:
                        match_child=(j,m); child_owned_label=True; break
                    m=INLINE_EXPLICIT_YEAR_RE.match("X: "+c.body)
                    if m:
                        match_child=(j,m); child_owned_label=False; break
                    if c.indent>ln.indent and not re.match(r"^[\d(+-]",c.body):
                        break
                j+=1
            if not match_child:
                continue
            idx,m=match_child
            v1,u1=_split_value_unit(m.group("value1")); v2,u2=_split_value_unit(m.group("value2"))
            v1=_clean_prefixed_numeric_value(v1); v2=_clean_prefixed_numeric_value(v2)
            y1=int(m.group("year1")); y2=int(m.group("year2"))
            cur,prev=(v1,v2) if y1>=y2 else (v2,v1)
            if child_owned_label:
                child_label=m.group("label").strip()
                child_label=re.sub(r"^\s*\d{1,3}[A-Za-z]?[.)]?\s*","",child_label).strip()
                final_label=_clean_indicator_and_code(child_label)[0]
            else:
                final_label=_clean_indicator_and_code(label_text)[0]
            if not final_label or _norm(final_label) in {"thuyet minh","ma so","chi tieu"}:
                continue
            row=DebugRow(indicator=final_label,note=note,
                         previous=prev,current=cur,unit=u1 or u2,pattern_id=self.PATTERN_33,
                         source_start_line=ln.line_no,source_end_line=lines[idx].line_no,
                         raw_lines=[ln.raw,lines[idx].raw])
            rows.append(row); matches.append(row.debug_dict()); consumed.update({i,idx})

        # P34: current value is inline in the semantic parent; previous period is a child.
        # Example: Tiền thu từ đi vay (Mã số 33): 5.802... / child Năm trước: 4.633...
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            m=INLINE_PARENT_CURRENT_RE.match(ln.body)
            if not m:
                continue
            cur,u1=_split_value_unit(m.group("value"))
            if not (NUM_RE.match(cur) or cur in {"-","—"}):
                continue
            prev=""; u2=""; used=[i]
            j=i+1
            while j<len(lines):
                c=lines[j]
                if c.is_bullet and c.indent<=ln.indent: break
                if c.is_bullet and c.body:
                    pm=PREVIOUS_YEAR_QUALIFIED_RE.match(c.body)
                    if pm:
                        prev,u2=_split_value_unit(pm.group("value")); used.append(j); break
                    # new semantic descendant means stop
                    if c.indent>ln.indent: break
                j+=1
            # Current-only is accepted only immediately under a cash-flow section heading.
            allow_current_only=False
            if not prev:
                for z in range(i-1,max(-1,i-6),-1):
                    if lines[z].is_bullet and lines[z].indent < ln.indent and "luu chuyen tien" in _norm(lines[z].body):
                        allow_current_only=True; break
            if not prev and not allow_current_only:
                continue
            label=(m.group("label")+" "+m.group("code")).strip()
            row=DebugRow(indicator=_clean_indicator_and_code(label)[0],previous=prev,current=cur,unit=u1 or u2,
                         pattern_id=self.PATTERN_34,source_start_line=ln.line_no,
                         source_end_line=max(lines[z].line_no for z in used),raw_lines=[lines[z].raw for z in used])
            rows.append(row); matches.append(row.debug_dict()); consumed.update(used)

        # P2: single-line label + current/previous values.
        for i, ln in enumerate(lines):
            if not ln.is_bullet or not ln.body:
                continue
            m = INLINE_PERIOD_RE.match(ln.body)
            if not m:
                continue
            current, u1 = _split_value_unit(m.group("current"))
            previous, u2 = _split_value_unit(m.group("previous"))
            unit = u1 or u2
            row = DebugRow(
                indicator=_clean_label(m.group("label")),
                previous=previous,
                current=current,
                unit=unit,
                pattern_id=self.PATTERN_2,
                source_start_line=ln.line_no,
                source_end_line=ln.line_no,
                raw_lines=[ln.raw],
            )
            rows.append(row); consumed.add(i)
            matches.append(row.debug_dict())

        # P7: single-line label + explicit reporting years, e.g.
        # `Label: value (Năm 2025) | value (Năm 2024)`.
        # Years are resolved chronologically rather than by left/right position.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.body:
                continue
            # P7 also accepts heading-style inline rows without a leading `*`.
            # The explicit two reporting-year values make the row structurally
            # self-contained, so bullet ownership is not required here.
            m = INLINE_EXPLICIT_YEAR_RE.match(ln.body)
            if not m:
                continue
            v1, u1 = _split_value_unit(m.group("value1"))
            v2, u2 = _split_value_unit(m.group("value2"))
            v1 = _clean_prefixed_numeric_value(v1)
            v2 = _clean_prefixed_numeric_value(v2)
            y1, y2 = int(m.group("year1")), int(m.group("year2"))
            values = sorted([(y1, v1, u1), (y2, v2, u2)], key=lambda x: x[0])
            previous = values[0][1]
            current = values[-1][1]
            unit = values[-1][2] or values[0][2]
            note = _strip_md((m.group("note") or "").strip())
            row = DebugRow(
                indicator=_clean_label(m.group("label")),
                note=note,
                previous=previous,
                current=current,
                unit=unit,
                pattern_id=self.PATTERN_7,
                source_start_line=ln.line_no,
                source_end_line=ln.line_no,
                raw_lines=[ln.raw],
            )
            rows.append(row); consumed.add(i)
            matches.append(row.debug_dict())

        # P5: single-line label + (Năm nay)/(Năm trước), optional trailing note.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            m = INLINE_YEAR_RE.match(ln.body)
            if not m:
                continue
            current, u1 = _split_value_unit(m.group("current"))
            previous, u2 = _split_value_unit(m.group("previous"))
            unit = u1 or u2
            note = _strip_md((m.group("note") or "").strip())
            row = DebugRow(
                indicator=_clean_label(m.group("label")),
                note=note,
                previous=previous,
                current=current,
                unit=unit,
                pattern_id=self.PATTERN_5,
                source_start_line=ln.line_no,
                source_end_line=ln.line_no,
                raw_lines=[ln.raw],
            )
            rows.append(row); consumed.add(i)
            matches.append(row.debug_dict())

        # P9: bullet column-major serialization.
        #
        # Example:
        # * CHỈ TIÊU
        #   * Mã số:
        #     * 01: Doanh thu...
        #     * 22: Chi phí tài chính
        #       * Trong đó: chi phí lãi vay
        #   * Thuyết minh:
        #     * VI.1
        #     * VI.2
        #   * Năm nay:
        #     * ...
        #   * Năm trước:
        #     * ...
        #
        # Values are aligned by row position only when label/current/previous
        # vectors have compatible lengths. A shortened note vector is NOT
        # blindly zipped because blank note cells may have disappeared during
        # serialization; in that case notes remain blank and debug records the
        # ambiguity.
        column_major_warnings: list[dict] = []
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or _norm(ln.body) not in {"chi tieu", "chỉ tiêu"}:
                continue

            # Find named column sections that are descendants of the CHỈ TIÊU root.
            sections: dict[str, tuple[int, int]] = {}
            j = i + 1
            while j < len(lines):
                cur = lines[j]
                if cur.is_bullet and cur.indent <= ln.indent:
                    break
                if cur.is_bullet:
                    sm = COLUMN_SECTION_RE.match(cur.body)
                    if sm:
                        name = _norm(sm.group("name"))
                        # section ends at next sibling section or root boundary
                        k = j + 1
                        while k < len(lines):
                            nxt = lines[k]
                            if nxt.is_bullet and nxt.indent <= ln.indent:
                                break
                            if nxt.is_bullet and nxt.indent == cur.indent and COLUMN_SECTION_RE.match(nxt.body):
                                break
                            k += 1
                        sections[name] = (j, k)
                j += 1

            code_key = next((k for k in sections if k in {"ma so", "mã số"}), None)
            current_key = next((k for k in sections if k in {"nam nay", "năm nay"}), None)
            previous_key = next((k for k in sections if k in {"nam truoc", "năm trước"}), None)
            note_key = next((k for k in sections if k in {"thuyet minh", "thuyết minh"}), None)

            if not code_key or not current_key or not previous_key:
                continue

            # Extract semantic rows from the Mã số subtree. Coded rows and
            # nested uncoded semantic rows (e.g. "Trong đó: chi phí lãi vay")
            # both occupy row positions.
            labels: list[tuple[str, int]] = []
            cs, ce = sections[code_key]
            code_indent = lines[cs].indent
            for k in range(cs + 1, ce):
                item = lines[k]
                if not item.is_bullet or item.indent <= code_indent or not item.body:
                    continue
                mcl = COLUMN_CODE_LABEL_RE.match(item.body)
                if mcl:
                    labels.append((_clean_label(mcl.group("label")), k))
                    continue
                # Nested descriptive row without a code. Exclude numeric/note-like
                # payloads and structural column labels.
                body = item.body.strip()
                if (COLUMN_SECTION_RE.match(body) or NOTE_CHILD_RE.match(body) or
                        END_YEAR_RE.match(body) or START_YEAR_RE.match(body)):
                    continue
                value_candidate, _ = _split_value_unit(body)
                if NUM_RE.match(value_candidate) or value_candidate in {"-", "—"}:
                    continue
                labels.append((_clean_label(body), k))

            def _column_values(section_key: str) -> list[tuple[str, str, int]]:
                ss, se = sections[section_key]
                base_indent = lines[ss].indent
                vals: list[tuple[str, str, int]] = []
                for kk in range(ss + 1, se):
                    item = lines[kk]
                    if not item.is_bullet or item.indent <= base_indent or not item.body:
                        continue
                    value, unit = _split_value_unit(item.body)
                    if NUM_RE.match(value) or value in {"-", "—"}:
                        vals.append((value, unit, kk))
                return vals

            currents = _column_values(current_key)
            previouses = _column_values(previous_key)

            notes: list[tuple[str, int]] = []
            if note_key:
                ns, ne = sections[note_key]
                base_indent = lines[ns].indent
                for kk in range(ns + 1, ne):
                    item = lines[kk]
                    if item.is_bullet and item.indent > base_indent and item.body:
                        notes.append((_strip_md(item.body).strip(), kk))

            if not labels:
                continue

            if len(currents) != len(labels) or len(previouses) != len(labels):
                column_major_warnings.append({
                    "line_no": ln.line_no,
                    "reason": "column_length_mismatch",
                    "label_count": len(labels),
                    "current_count": len(currents),
                    "previous_count": len(previouses),
                    "note_count": len(notes),
                })
                continue

            notes_aligned = len(notes) == len(labels)
            if notes and not notes_aligned:
                column_major_warnings.append({
                    "line_no": ln.line_no,
                    "reason": "note_column_sparse_or_unaligned",
                    "label_count": len(labels),
                    "note_count": len(notes),
                    "action": "notes_left_blank_to_avoid_false_binding",
                })
                # Sparse note columns lose blank-cell positions during bullet
                # serialization. Consume them structurally so they do not pollute
                # unmatched_bullets, but never guess which row owns which note.
                consumed.update(idx for _, idx in notes)

            for pos, ((label, label_idx), (cur_val, cur_unit, cur_idx), (prev_val, prev_unit, prev_idx)) in enumerate(
                zip(labels, currents, previouses)
            ):
                note = notes[pos][0] if notes_aligned else ""
                unit = cur_unit or prev_unit
                source_indices = [label_idx, cur_idx, prev_idx]
                if notes_aligned:
                    source_indices.append(notes[pos][1])
                row = DebugRow(
                    indicator=label,
                    note=note,
                    previous=prev_val,
                    current=cur_val,
                    unit=unit,
                    pattern_id=self.PATTERN_9,
                    source_start_line=min(lines[x].line_no for x in source_indices),
                    source_end_line=max(lines[x].line_no for x in source_indices),
                    raw_lines=[lines[x].raw for x in source_indices],
                )
                rows.append(row)
                matches.append(row.debug_dict())
                consumed.update(source_indices)

            # Consume root and column headers so they do not leak to unmatched.
            consumed.add(i)
            for ss, _ in sections.values():
                consumed.add(ss)

        # P16: period-major blocks: Năm nay / Năm trước -> label:value children.
        current_blocks=[]; previous_blocks=[]
        for i,ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body: continue
            role=None
            if re.match(r"^Năm\s+nay\s*:??\s*$", ln.body, re.I): role="current"
            elif re.match(r"^Năm\s+trước(?:\s*\([^)]+\))?\s*:??\s*$", ln.body, re.I): role="previous"
            if not role: continue
            vals=[]; j=i+1
            while j<len(lines):
                c=lines[j]
                if c.is_bullet and c.indent<=ln.indent: break
                if c.is_bullet and c.body:
                    kv=KEY_VALUE_RE.match(c.body)
                    if kv:
                        label=_clean_indicator_and_code(kv.group("label"))[0]
                        value,unit=_split_value_unit(kv.group("value"))
                        if label and (NUM_RE.match(value) or value in {"-","—"}): vals.append((label,value,unit,j))
                j+=1
            if vals:
                (current_blocks if role=="current" else previous_blocks).append((i,vals))
        for (ci,cvals),(pi,pvals) in zip(current_blocks,previous_blocks):
            pm={x[0]:x for x in pvals}
            for label,cv,cu,cidx in cvals:
                if label not in pm: continue
                _,pv,pu,pidx=pm[label]
                row=DebugRow(indicator=label,previous=pv,current=cv,unit=cu or pu,pattern_id=self.PATTERN_16,source_start_line=min(lines[cidx].line_no,lines[pidx].line_no),source_end_line=max(lines[cidx].line_no,lines[pidx].line_no),raw_lines=[lines[cidx].raw,lines[pidx].raw])
                rows.append(row); matches.append(row.debug_dict()); consumed.update({cidx,pidx})
            consumed.update({ci,pi})

        # P17: semantic -> period wrapper -> YYYY:value children.
        for i,ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body: continue
            if CODE_CHILD_RE.match(ln.body) or NOTE_CHILD_RE.match(ln.body) or _parse_period_value_line(ln.body): continue
            note=""; obs=[]; owned=[]; j=i+1
            while j<len(lines):
                c=lines[j]
                if c.is_bullet and c.indent<=ln.indent: break
                if not c.is_bullet or not c.body: j+=1; continue
                nm=NOTE_CHILD_RE.match(c.body)
                if nm:
                    note=_strip_md(nm.group("note")); owned.append(j); j+=1; continue
                wrapper=bool(re.match(r"^(?:Tại\s+ngày|Tại\s+thời\s+điểm|Số\s+dư\s+tại\s+ngày).*(?:năm)?\s*:??\s*$", c.body,re.I))
                if wrapper:
                    owned.append(j); k=j+1
                    while k<len(lines):
                        sub=lines[k]
                        if sub.is_bullet and sub.indent<=c.indent: break
                        if sub.is_bullet and sub.body:
                            po=_parse_period_value_line(sub.body)
                            if po: obs.append(po); owned.append(k)
                        k+=1
                    j=k; continue
                break
            prev,cur,unit=_resolve_period_obs(obs)
            if cur or prev:
                row=DebugRow(indicator=_clean_indicator_and_code(ln.body)[0],note=note,previous=prev,current=cur,unit=unit,pattern_id=self.PATTERN_17,source_start_line=ln.line_no,source_end_line=max([ln.line_no]+[lines[x].line_no for x in owned]),raw_lines=[ln.raw]+[lines[x].raw for x in owned])
                rows.append(row); matches.append(row.debug_dict()); consumed.add(i); consumed.update(owned)

        # P18: plain-text inline pair (non-bullet).
        for i,ln in enumerate(lines):
            if i in consumed or ln.is_bullet or not ln.body: continue
            m=re.match(r"^(?P<label>.+?)\s*:\s*(?P<payload>.+)$",ln.body)
            if not m: continue
            pm=INLINE_PAIR_IN_TEXT_RE.match(m.group("payload"))
            if not pm: continue
            cur,u1=_split_value_unit(pm.group("v1")); prev,u2=_split_value_unit(pm.group("v2"))
            if not ((NUM_RE.match(cur) or cur in {"-","—"}) and (NUM_RE.match(prev) or prev in {"-","—"})): continue
            row=DebugRow(indicator=_clean_indicator_and_code(m.group("label"))[0],previous=prev,current=cur,unit=u1 or u2,pattern_id=self.PATTERN_18,source_start_line=ln.line_no,source_end_line=ln.line_no,raw_lines=[ln.raw])
            rows.append(row); matches.append(row.debug_dict()); consumed.add(i)

        # P20: one structural wrapper carries multiple sibling CHỈ TIÊU nodes.
        # Seen in MWG where "Mã số: III..." is a section wrapper, not a row code.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            if not CODE_CHILD_RE.match(ln.body):
                continue
            # require at least two direct/nested named-indicator children
            j=i+1; candidates=[]
            while j < len(lines):
                c=lines[j]
                if c.is_bullet and c.indent <= ln.indent: break
                if c.is_bullet and c.body:
                    nm=NAMED_INDICATOR_RE.match(c.body)
                    if nm: candidates.append(j)
                j+=1
            if len(candidates) < 2:
                continue
            for cidx in candidates:
                c=lines[cidx]
                label=NAMED_INDICATOR_RE.match(c.body).group('label')
                note=''; obs=[]; owned=[cidx]
                k=cidx+1
                while k < len(lines):
                    x=lines[k]
                    if x.is_bullet and x.indent <= c.indent: break
                    if x.is_bullet and x.body:
                        nm=NOTE_CHILD_RE.match(x.body)
                        po=_parse_period_value_line(x.body)
                        if nm:
                            note=_strip_md(nm.group('note')); owned.append(k)
                        elif po:
                            obs.append(po); owned.append(k)
                        elif x.indent > c.indent:
                            break
                    k+=1
                prev,cur,unit=_resolve_period_obs(obs)
                if cur or prev:
                    row=DebugRow(indicator=_clean_label(label),note=note,previous=prev,current=cur,unit=unit,
                                 pattern_id=self.PATTERN_20,source_start_line=c.line_no,
                                 source_end_line=max(lines[z].line_no for z in owned),raw_lines=[lines[z].raw for z in owned])
                    rows.append(row); matches.append(row.debug_dict()); consumed.update(owned)
            consumed.add(i)

        # P21: implicit row-major columns after a header Mã số > Chỉ tiêu > Thuyết minh/Năm nay/Năm trước.
        # Conservative: emit only rows whose direct payload count is exactly 2 (values) or 3 (note+values).
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or _norm(ln.body) != 'ma so':
                continue
            # detect nested header signature
            j=i+1; sig=[]
            while j < len(lines):
                c=lines[j]
                if c.is_bullet and c.indent <= ln.indent: break
                if c.is_bullet: sig.append(_norm(c.body))
                j+=1
            if not ({'chi tieu','thuyet minh','nam nay','nam truoc'} <= set(sig)):
                continue
            consumed.add(i)
            for z in range(i+1,j):
                if lines[z].is_bullet: consumed.add(z)
            r=j
            while r < len(lines):
                rowln=lines[r]
                if not rowln.is_bullet: r+=1; continue
                if rowln.indent < ln.indent: break
                m=ROW_CODE_LABEL_NO_DOT_RE.match(rowln.body)
                if not m: r+=1; continue
                # collect direct child payloads only using minimum descendant indent
                k=r+1; desc=[]
                while k < len(lines):
                    x=lines[k]
                    if x.is_bullet and x.indent <= rowln.indent: break
                    if x.is_bullet and x.body: desc.append((k,x))
                    k+=1
                if desc:
                    mind=min(x.indent for _,x in desc)
                    direct=[(idx,x) for idx,x in desc if x.indent==mind]
                else: direct=[]
                payload=[]
                for idx,x in direct:
                    body=x.body.strip(); val,u=_split_value_unit(body)
                    if NUM_RE.match(val) or val in {'-','—'}:
                        payload.append((idx,val,u))
                    else:
                        # note-like cell e.g. 27 or 14, 15; accept only if followed by >=2 numeric direct cells
                        payload.append((idx,body,''))
                note=''; cur=prev=unit=''; used=[]
                if len(payload)==2:
                    a,b=payload
                    va,ua=_split_value_unit(a[1]); vb,ub=_split_value_unit(b[1])
                    if (NUM_RE.match(va) or va in {'-','—'}) and (NUM_RE.match(vb) or vb in {'-','—'}):
                        cur,prev=va,vb; unit=ua or ub; used=[a[0],b[0]]
                elif len(payload)==3:
                    n,a,b=payload
                    va,ua=_split_value_unit(a[1]); vb,ub=_split_value_unit(b[1])
                    if (NUM_RE.match(va) or va in {'-','—'}) and (NUM_RE.match(vb) or vb in {'-','—'}):
                        note=_strip_md(n[1]); cur,prev=va,vb; unit=ua or ub; used=[n[0],a[0],b[0]]
                if cur or prev:
                    row=DebugRow(indicator=_clean_label(m.group('label')),note=note,previous=prev,current=cur,unit=unit,
                                 pattern_id=self.PATTERN_21,source_start_line=rowln.line_no,
                                 source_end_line=max(lines[z].line_no for z in used),raw_lines=[rowln.raw]+[lines[z].raw for z in used])
                    rows.append(row); matches.append(row.debug_dict()); consumed.add(r); consumed.update(used)
                r=k

        # P22: report-year header + semantic row with child "Số liệu:" only.
        report_year=None; report_unit=''
        for i,ln in enumerate(lines):
            if not ln.body: continue
            ry=REPORT_YEAR_RE.match(ln.body)
            if ry:
                report_year=int(ry.group('year')); report_unit=(ry.group('unit') or '').strip(); continue
            if report_year is None or i in consumed or not ln.is_bullet: continue
            if DATA_ONLY_RE.match(ln.body) or CODE_CHILD_RE.match(ln.body) or NOTE_CHILD_RE.match(ln.body): continue
            j=i+1; note=''; val=''; unit=''; owned=[]
            while j < len(lines):
                c=lines[j]
                if c.is_bullet and c.indent <= ln.indent: break
                if c.is_bullet and c.body:
                    dm=DATA_ONLY_RE.match(c.body); nm=NOTE_CHILD_RE.match(c.body)
                    if dm:
                        val,unit=_split_value_unit(dm.group('value')); owned.append(j)
                    elif nm:
                        note=_strip_md(nm.group('note')); owned.append(j)
                    elif CODE_CHILD_RE.match(c.body):
                        owned.append(j)
                    elif c.indent > ln.indent:
                        break
                j+=1
            if val:
                row=DebugRow(indicator=_clean_indicator_and_code(ln.body)[0],note=note,previous='',current=val,unit=unit or report_unit,
                             pattern_id=self.PATTERN_22,source_start_line=ln.line_no,source_end_line=max([ln.line_no]+[lines[z].line_no for z in owned]),
                             raw_lines=[ln.raw]+[lines[z].raw for z in owned])
                rows.append(row); matches.append(row.debug_dict()); consumed.add(i); consumed.update(owned)

        # P23: malformed wrapper "Mã Thuyết số minh: NN" with child label carrying inline year pair.
        for i,ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not CODE_NOTE_WRAPPER_RE.match(ln.body): continue
            j=i+1; emitted=False
            while j < len(lines):
                c=lines[j]
                if c.is_bullet and c.indent <= ln.indent: break
                if c.is_bullet and c.body:
                    m=INLINE_EXPLICIT_YEAR_RE.match(c.body) or INLINE_YEAR_RE.match(c.body)
                    if m:
                        if 'year1' in m.groupdict():
                            v1,u1=_split_value_unit(m.group('value1')); v2,u2=_split_value_unit(m.group('value2'))
                            y1=int(m.group('year1')); y2=int(m.group('year2'))
                            if y1>=y2: cur,prev=v1,v2
                            else: cur,prev=v2,v1
                            label=m.group('label'); unit=u1 or u2; note=''
                        else:
                            cur,u1=_split_value_unit(m.group('current')); prev,u2=_split_value_unit(m.group('previous'))
                            label=m.group('label'); unit=u1 or u2; note=m.groupdict().get('note') or ''
                        row=DebugRow(indicator=_clean_label(label),note=note,previous=prev,current=cur,unit=unit,
                                     pattern_id=self.PATTERN_23,source_start_line=ln.line_no,source_end_line=c.line_no,raw_lines=[ln.raw,c.raw])
                        rows.append(row); matches.append(row.debug_dict()); consumed.update({i,j}); emitted=True
                j+=1

        # P24: one-period inline balance row: label: value unit (tại ngày dd/mm/yyyy).
        for i,ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body: continue
            m=SINGLE_DATE_INLINE_RE.match(ln.body)
            if not m: continue
            val,unit=_split_value_unit(m.group('value'))
            if not (NUM_RE.match(val) or val in {'-','—'}): continue
            row=DebugRow(indicator=_clean_indicator_and_code(m.group('label'))[0],note='',previous='',current=val,unit=unit,
                         pattern_id=self.PATTERN_24,source_start_line=ln.line_no,source_end_line=ln.line_no,raw_lines=[ln.raw])
            rows.append(row); matches.append(row.debug_dict()); consumed.add(i)

        # P25: date headers nested under "Thuyết minh" followed by implicit row payloads (NAB quarterly style).
        for i,ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not _norm(ln.body).rstrip(':').strip()=='thuyet minh': continue
            # detect two descendant date headers before next sibling
            j=i+1; dates=[]
            while j < len(lines):
                c=lines[j]
                if c.is_bullet and c.indent <= ln.indent: break
                if c.is_bullet:
                    dm=DATE_HEADER_RE.match(c.body)
                    if dm: dates.append((j,_parse_date(dm.group('date')),dm.group('unit') or ''))
                j+=1
            if len(dates)<2: continue
            dates=sorted(dates,key=lambda x:x[1],reverse=True)[:2]
            unit_hdr=dates[0][2] or dates[1][2]
            consumed.add(i); consumed.update(x[0] for x in dates)
            r=j
            while r < len(lines):
                rowln=lines[r]
                if not rowln.is_bullet: r+=1; continue
                if rowln.indent < ln.indent: break
                # structural section headings without descendants numeric will naturally skip
                k=r+1; desc=[]
                while k < len(lines):
                    x=lines[k]
                    if x.is_bullet and x.indent <= rowln.indent: break
                    if x.is_bullet and x.body: desc.append((k,x))
                    k+=1
                if not desc: r+=1; continue
                mind=min(x.indent for _,x in desc); direct=[(idx,x) for idx,x in desc if x.indent==mind]
                vals=[]; note=''; used=[]
                for idx,x in direct:
                    kv=KEY_VALUE_RE.match(x.body)
                    if kv:
                        vv,uu=_split_value_unit(kv.group('value'))
                        if NUM_RE.match(vv) or vv in {'-','—'}:
                            # note:value compact cell e.g. V.2: 197.607.593
                            if not vals and not re.match(r'^\d{4}$',kv.group('label')):
                                note=_strip_md(kv.group('label')); vals.append((vv,uu)); used.append(idx); continue
                    vv,uu=_split_value_unit(x.body)
                    if NUM_RE.match(vv) or vv in {'-','—'}:
                        vals.append((vv,uu)); used.append(idx)
                if len(vals)>=2:
                    cur,prev=vals[0][0],vals[1][0]; unit=vals[0][1] or vals[1][1] or unit_hdr
                    row=DebugRow(indicator=_clean_indicator_and_code(rowln.body)[0],note=note,previous=prev,current=cur,unit=unit,
                                 pattern_id=self.PATTERN_25,source_start_line=rowln.line_no,source_end_line=max(lines[z].line_no for z in used),
                                 raw_lines=[rowln.raw]+[lines[z].raw for z in used])
                    rows.append(row); matches.append(row.debug_dict()); consumed.add(r); consumed.update(used)
                r=k

        # P19: code wrapper with multiple independent Diễn giải rows.
        for i,ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body: continue
            m=INLINE_CODE_LABEL_RE.match(ln.body)
            if not m: continue
            wrapper_label=_clean_label(m.group("label")); note=""; owned=[i]; desc=[]; j=i+1
            while j<len(lines):
                c=lines[j]
                if c.is_bullet and c.indent<=ln.indent: break
                if not c.is_bullet or not c.body: j+=1; continue
                nm=NOTE_CHILD_RE.match(c.body)
                if nm: note=_strip_md(nm.group("note")); owned.append(j); j+=1; continue
                dm=re.match(r"^Diễn\s+giải\s*:\s*(?P<payload>.+)$",c.body,re.I)
                if dm:
                    payload=dm.group("payload").strip(); label=wrapper_label; pm=None
                    m2=re.match(r"^(?P<desc>.+?)\s*:\s*(?P<pair>.+)$",payload)
                    if m2:
                        candidate=INLINE_PAIR_IN_TEXT_RE.match(m2.group("pair"))
                        if candidate:
                            pm=candidate; label=_clean_label(m2.group("desc"))
                    if pm is None:
                        pm=INLINE_PAIR_IN_TEXT_RE.match(payload)
                    if pm:
                        cur,u1=_split_value_unit(pm.group("v1")); prev,u2=_split_value_unit(pm.group("v2")); desc.append((label,prev,cur,u1 or u2,j)); owned.append(j)
                    j+=1; continue
                break
            if len(desc)>=2:
                for label,prev,cur,unit,didx in desc:
                    row=DebugRow(indicator=label,note=note,previous=prev,current=cur,unit=unit,pattern_id=self.PATTERN_19,source_start_line=ln.line_no,source_end_line=lines[didx].line_no,raw_lines=[ln.raw,lines[didx].raw])
                    rows.append(row); matches.append(row.debug_dict())
                consumed.update(owned)

        # P14: "Mã số" wrapper whose semantic label is carried by a child "Chỉ tiêu".
        #
        # * Mã số: 22
        #   * Chỉ tiêu: Chi phí tài chính
        #     * Thuyết minh: 27
        #     * Năm nay: ...
        #     * Năm trước: ...
        #
        # Also supports explicit year/date carriers such as:
        #   Giá trị 2025:
        #   Năm tài chính kết thúc ngày 31/12/2025:
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            cm = CODE_FIRST_RE.match(ln.body)
            if not cm:
                continue

            code_value = _strip_md(cm.group("code")).strip()
            label = ""
            note = ""
            current = ""
            previous = ""
            unit = ""
            year_values: dict[int, tuple[str, str]] = {}
            dated_values: list[tuple[tuple[int, int, int], str, str]] = []
            owned = [i]

            j = i + 1
            label_indent = None
            while j < len(lines):
                child = lines[j]
                if child.is_bullet and child.indent <= ln.indent:
                    break
                if not child.is_bullet or not child.body:
                    j += 1
                    continue

                # Find the semantic label child.
                nim = NAMED_INDICATOR_RE.match(child.body)
                if nim and not label:
                    label = _clean_label(nim.group("label"))
                    label_indent = child.indent
                    owned.append(j)
                    j += 1
                    continue

                if not label:
                    j += 1
                    continue

                # Stop if a new semantic branch appears under the wrapper.
                if label_indent is not None and child.indent <= label_indent and not (
                    NOTE_CHILD_RE.match(child.body)
                    or CURRENT_YEAR_QUALIFIED_RE.match(child.body)
                    or PREVIOUS_YEAR_QUALIFIED_RE.match(child.body)
                    or VALUE_YEAR_RE.match(child.body)
                    or FISCAL_YEAR_DATE_RE.match(child.body)
                ):
                    break

                nm = NOTE_CHILD_RE.match(child.body)
                cy = CURRENT_YEAR_QUALIFIED_RE.match(child.body)
                py = PREVIOUS_YEAR_QUALIFIED_RE.match(child.body)
                vy = VALUE_YEAR_RE.match(child.body)
                fy = FISCAL_YEAR_DATE_RE.match(child.body)

                if nm:
                    note = _strip_md(nm.group("note"))
                    owned.append(j)
                elif cy:
                    current, u = _split_value_unit(cy.group("value"))
                    unit = unit or u
                    owned.append(j)
                elif py:
                    previous, u = _split_value_unit(py.group("value"))
                    unit = unit or u
                    owned.append(j)
                elif vy:
                    value, u = _split_value_unit(vy.group("value"))
                    year_values[int(vy.group("year"))] = (value, u)
                    unit = unit or u
                    owned.append(j)
                elif fy:
                    d, mo, y = (int(x) for x in fy.group("date").split("/"))
                    value, u = _split_value_unit(fy.group("value"))
                    dated_values.append(((y, mo, d), value, u))
                    unit = unit or u
                    owned.append(j)
                j += 1

            if not label:
                continue

            if year_values and not (current or previous):
                ys = sorted(year_values)
                if len(ys) >= 1:
                    previous = year_values[ys[0]][0] if len(ys) > 1 else ""
                    current = year_values[ys[-1]][0]
                    unit = unit or year_values[ys[-1]][1] or year_values[ys[0]][1]
            elif dated_values and not (current or previous):
                dated_values.sort(key=lambda x: x[0])
                previous = dated_values[0][1] if len(dated_values) > 1 else ""
                current = dated_values[-1][1]
                unit = unit or dated_values[-1][2] or dated_values[0][2]

            if current or previous:
                row = DebugRow(
                    indicator=label,
                    note=note,
                    previous=previous,
                    current=current,
                    unit=unit,
                    pattern_id=self.PATTERN_14,
                    source_start_line=ln.line_no,
                    source_end_line=max(lines[x].line_no for x in owned),
                    raw_lines=[lines[x].raw for x in owned],
                )
                rows.append(row)
                matches.append(row.debug_dict())
                consumed.update(owned)

        # P15: accounting code + label on the same semantic row, with an inline
        # period pair either on that row or in a child "Diễn giải" line.
        #
        # * Mã số 05 - Chi phí lãi vay:
        #   * Thuyết minh: 30
        #   * Diễn giải: 142... (Năm nay) / 91... (Năm trước)
        #
        # or:
        # * Mã số 08 - Lợi nhuận ...: 480... (Năm nay) / 589... (Năm trước)
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue

            raw_body = ln.body.strip()
            code = ""
            label = ""
            inline_payload = ""

            # Variant A: "Mã số NN - Label: payload"
            m = re.match(
                r"^Mã\s+số\s+(?P<code>[0-9A-Za-z.]+)\s*[-–—]\s*(?P<label>.+?)\s*:\s*(?P<payload>.+)$",
                raw_body,
                re.I,
            )
            if m:
                code = m.group("code").strip()
                label = _clean_label(m.group("label"))
                inline_payload = m.group("payload").strip()
            else:
                # Variant B: "Mã số NN - Label:" then child Diễn giải.
                m2 = INLINE_CODE_LABEL_RE.match(raw_body)
                if not m2:
                    continue
                code = m2.group("code").strip()
                label = _clean_label(m2.group("label"))

            note = ""
            current = ""
            previous = ""
            unit = ""
            owned = [i]

            if inline_payload:
                pm = INLINE_PAIR_IN_TEXT_RE.match(inline_payload)
                if pm:
                    current, u1 = _split_value_unit(pm.group("v1"))
                    previous, u2 = _split_value_unit(pm.group("v2"))
                    unit = u1 or u2

            j = i + 1
            while j < len(lines):
                child = lines[j]
                if child.is_bullet and child.indent <= ln.indent:
                    break
                if not child.is_bullet or not child.body:
                    j += 1
                    continue

                nm = NOTE_CHILD_RE.match(child.body)
                if nm:
                    note = _strip_md(nm.group("note"))
                    owned.append(j)
                    j += 1
                    continue

                dm = re.match(r"^Diễn\s+giải\s*:\s*(?P<payload>.+?)\s*$", child.body, re.I)
                if dm:
                    pm = INLINE_PAIR_IN_TEXT_RE.match(dm.group("payload"))
                    if pm:
                        current, u1 = _split_value_unit(pm.group("v1"))
                        previous, u2 = _split_value_unit(pm.group("v2"))
                        unit = unit or u1 or u2
                        owned.append(j)
                    j += 1
                    continue

                # Do not descend into a new semantic branch.
                if child.indent > ln.indent:
                    break
                j += 1

            if current or previous:
                row = DebugRow(
                    indicator=label,
                    note=note,
                    previous=previous,
                    current=current,
                    unit=unit,
                    pattern_id=self.PATTERN_15,
                    source_start_line=ln.line_no,
                    source_end_line=max(lines[x].line_no for x in owned),
                    raw_lines=[lines[x].raw for x in owned],
                )
                rows.append(row)
                matches.append(row.debug_dict())
                consumed.update(owned)

        # P13: row-major rows governed by a preceding column header.
        #
        # Example:
        # * Chỉ tiêu
        #   * Thuyết minh
        #   * Năm 2025
        #     * Triệu VND
        #   * Năm 2024
        #     * Triệu VND
        #
        # * 1. Thu nhập ...
        #   * 6.1
        #   * 13.556.729
        #   * 11.812.113
        #
        # Column meaning comes from the header. Year order is dynamic.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or _norm(ln.body) not in {"chi tieu", "chỉ tiêu"}:
                continue

            header_cols: list[tuple[str, int | None]] = []
            header_unit_by_year: dict[int, str] = {}
            j = i + 1

            while j < len(lines):
                cur = lines[j]
                if cur.is_bullet and cur.indent <= ln.indent:
                    break
                if cur.is_bullet and cur.body:
                    bnorm = _norm(cur.body)
                    if bnorm in {"thuyet minh", "thuyết minh"}:
                        header_cols.append(("note", None))
                    else:
                        ym = ROW_HEADER_YEAR_RE.match(cur.body)
                        if ym:
                            year = int(ym.group("year"))
                            header_cols.append(("year", year))

                            # Unit can be nested directly beneath the year header.
                            k = j + 1
                            while k < len(lines):
                                nxt = lines[k]
                                if nxt.is_bullet and nxt.indent <= cur.indent:
                                    break
                                if nxt.is_bullet and nxt.body:
                                    candidate = _strip_md(nxt.body).strip()
                                    val, embedded_unit = _split_value_unit(candidate)
                                    if not NUM_RE.match(val) and candidate not in {"-", "—"}:
                                        header_unit_by_year[year] = embedded_unit or candidate
                                        break
                                k += 1
                j += 1

            years = [v for kind, v in header_cols if kind == "year" and v is not None]
            if len(years) < 2:
                continue

            newer_year = max(years)
            older_year = min(years)

            # Claim header block so generic patterns do not reinterpret it.
            # STT is often a sibling immediately before Chỉ tiêu; it is structural only.
            if i > 0 and lines[i - 1].is_bullet and lines[i - 1].indent == ln.indent and _norm(lines[i - 1].body) == "stt":
                consumed.add(i - 1)
            consumed.add(i)
            for k in range(i + 1, j):
                if lines[k].is_bullet:
                    consumed.add(k)

            r = j
            while r < len(lines):
                rowln = lines[r]

                if not rowln.is_bullet:
                    r += 1
                    continue
                if rowln.indent < ln.indent:
                    break
                if rowln.indent != ln.indent:
                    r += 1
                    continue

                lm = ROW_DATA_LABEL_RE.match(rowln.body)
                if not lm:
                    r += 1
                    continue

                child_items: list[tuple[int, Line]] = []
                k = r + 1
                while k < len(lines):
                    c = lines[k]
                    if c.is_bullet and c.indent <= rowln.indent:
                        break
                    if c.is_bullet and c.indent > rowln.indent and c.body:
                        child_items.append((k, c))
                    k += 1

                # P13 supports sparse optional note cells:
                #   3 children -> note + value(newer year) + value(older year)
                #   2 children -> value(newer year) + value(older year)
                #
                # This is necessary because Markdown/LLM serialization usually omits
                # empty table cells rather than emitting a placeholder for Thuyết minh.
                year_cols = [(kind, year) for kind, year in header_cols if kind == "year" and year is not None]
                has_note_col = any(kind == "note" for kind, _ in header_cols)
                min_payload = len(year_cols)

                if len(child_items) < min_payload:
                    r = k
                    continue

                note = ""
                values_by_year: dict[int, str] = {}
                unit = ""
                ok = True

                # Decide whether this particular row contains a note cell.
                # With two year columns:
                #   [6.1, 13.556.729, 11.812.113] -> note present
                #   [3.446.898, 3.321.210]        -> note absent
                payload = child_items
                note_present = has_note_col and len(payload) >= len(year_cols) + 1

                value_start = 0
                used_count = len(year_cols)

                if note_present:
                    note_body = _strip_md(payload[0][1].body).strip()
                    # A note can itself look numeric (e.g. 6.1), so presence is decided
                    # structurally by child count rather than NUM_RE.
                    note = note_body
                    value_start = 1
                    used_count += 1

                # Use only the next N cells matching the year columns.
                if len(payload) < value_start + len(year_cols):
                    r = k
                    continue

                for pos, (_, year) in enumerate(year_cols):
                    idxc, child = payload[value_start + pos]
                    body = _strip_md(child.body).strip()
                    value, child_unit = _split_value_unit(body)

                    if not (NUM_RE.match(value) or value in {"-", "—"}):
                        ok = False
                        break

                    values_by_year[year] = value
                    unit = unit or child_unit or header_unit_by_year.get(year, "")

                if ok and newer_year in values_by_year and older_year in values_by_year:
                    used = payload[:used_count]
                    row = DebugRow(
                        indicator=_clean_label(lm.group("label")),
                        note=note,
                        previous=values_by_year[older_year],
                        current=values_by_year[newer_year],
                        unit=unit or header_unit_by_year.get(newer_year, "") or header_unit_by_year.get(older_year, ""),
                        pattern_id=self.PATTERN_13,
                        source_start_line=rowln.line_no,
                        source_end_line=used[-1][1].line_no,
                        raw_lines=[rowln.raw] + [x[1].raw for x in used],
                    )
                    rows.append(row)
                    matches.append(row.debug_dict())
                    consumed.add(r)
                    consumed.update(x[0] for x in used)

                r = k

        # P11: global date headers + paired values under each semantic row.
        date_headers: list[tuple[object, str, str, int]] = []
        for hi, hln in enumerate(lines):
            if not hln.is_bullet or not hln.body:
                continue
            hm = DATE_HEADER_RE.match(hln.body)
            if not hm:
                continue
            try:
                hd = _parse_date(hm.group("date"))
            except Exception:
                continue
            date_headers.append((hd, hm.group("date"), (hm.group("unit") or "").strip(), hi))

        header_pair = None
        for hp in range(len(date_headers) - 1):
            a, b = date_headers[hp], date_headers[hp + 1]
            if abs(a[3] - b[3]) <= 3:
                header_pair = (a, b)
                break

        if header_pair:
            h1, h2 = header_pair
            header_unit = h1[2] or h2[2]
            newer_first = h1[0] >= h2[0]
            consumed.update({h1[3], h2[3]})

            header_norms = {"stt", "chi tieu", "thuyet minh"}
            for hi, hln in enumerate(lines):
                if hln.is_bullet and _norm(hln.body.rstrip(":")) in header_norms:
                    consumed.add(hi)

            for i, ln in enumerate(lines):
                if i in consumed or not ln.is_bullet or not ln.body:
                    continue
                if i <= max(h1[3], h2[3]):
                    continue
                if (DATE_HEADER_RE.match(ln.body) or CODE_CHILD_RE.match(ln.body) or
                        NOTE_CHILD_RE.match(ln.body) or END_YEAR_RE.match(ln.body) or
                        START_YEAR_RE.match(ln.body) or CURRENT_YEAR_CHILD_RE.match(ln.body) or
                        PREVIOUS_YEAR_CHILD_RE.match(ln.body) or COLUMN_SECTION_RE.match(ln.body)):
                    continue

                direct: list[int] = []
                j = i + 1
                while j < len(lines):
                    child = lines[j]
                    if child.is_bullet and child.indent <= ln.indent:
                        break
                    if child.is_bullet and child.indent > ln.indent and child.body:
                        direct.append(j)
                    j += 1
                if not direct:
                    continue

                min_indent = min(lines[x].indent for x in direct)
                direct = [x for x in direct if lines[x].indent == min_indent]

                kv_payloads: list[tuple[str, str, str, int]] = []
                inline_semantic: list[tuple[str, str, str, int]] = []
                for x in direct:
                    body = lines[x].body
                    km = KEY_VALUE_RE.match(body)
                    if not km:
                        continue
                    key = _strip_md(km.group("label")).strip()
                    val, val_unit = _split_value_unit(km.group("value"))
                    if not (NUM_RE.match(val) or val in {"-", "—"}):
                        continue
                    if re.match(r"^\d+(?:\.\d+)*[.)]?\s+\S", key):
                        inline_semantic.append((_clean_label(key), val, val_unit, x))
                    else:
                        kv_payloads.append((key, val, val_unit, x))

                if len(kv_payloads) >= 2:
                    k1, v1, u1, x1 = kv_payloads[0]
                    k2, v2, u2, x2 = kv_payloads[1]
                    if _norm(k1) == _norm(k2):
                        current = v1 if newer_first else v2
                        previous = v2 if newer_first else v1
                        row = DebugRow(
                            indicator=_clean_label(ln.body), note=k1,
                            previous=previous, current=current,
                            unit=u1 or u2 or header_unit,
                            pattern_id=self.PATTERN_11,
                            source_start_line=ln.line_no,
                            source_end_line=max(lines[x1].line_no, lines[x2].line_no),
                            raw_lines=[ln.raw, lines[x1].raw, lines[x2].raw],
                        )
                        rows.append(row)
                        matches.append(row.debug_dict())
                        consumed.update({i, x1, x2})

                groups: dict[str, list[tuple[str, str, str, int]]] = {}
                order: list[str] = []
                for item in inline_semantic:
                    key = _norm(item[0])
                    if key not in groups:
                        groups[key] = []
                        order.append(key)
                    groups[key].append(item)
                for key in order:
                    items = groups[key]
                    if len(items) < 2:
                        continue
                    a, b = items[0], items[1]
                    current = a[1] if newer_first else b[1]
                    previous = b[1] if newer_first else a[1]
                    row = DebugRow(
                        indicator=a[0], previous=previous, current=current,
                        unit=a[2] or b[2] or header_unit,
                        pattern_id=self.PATTERN_11,
                        source_start_line=lines[a[3]].line_no,
                        source_end_line=lines[b[3]].line_no,
                        raw_lines=[lines[a[3]].raw, lines[b[3]].raw],
                    )
                    rows.append(row)
                    matches.append(row.debug_dict())
                    consumed.update({a[3], b[3]})

        # P10: field-major semantic rows with direct Năm nay/Năm trước children.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            if (CODE_CHILD_RE.match(ln.body) or NOTE_CHILD_RE.match(ln.body) or
                    END_YEAR_RE.match(ln.body) or START_YEAR_RE.match(ln.body) or
                    CURRENT_YEAR_CHILD_RE.match(ln.body) or PREVIOUS_YEAR_CHILD_RE.match(ln.body) or
                    COLUMN_SECTION_RE.match(ln.body)):
                continue

            note = ""
            current = ""
            previous = ""
            unit = ""
            owned_indices = []
            j = i + 1
            while j < len(lines):
                child = lines[j]
                if child.is_bullet and child.indent <= ln.indent:
                    break
                if not child.is_bullet or not child.body:
                    j += 1
                    continue

                nm = NOTE_CHILD_RE.match(child.body)
                cm = CODE_CHILD_RE.match(child.body)
                cy = CURRENT_YEAR_CHILD_RE.match(child.body)
                py = PREVIOUS_YEAR_CHILD_RE.match(child.body)

                if nm or cm or cy or py:
                    if nm:
                        note = _strip_md(nm.group("note"))
                    elif cy:
                        current, u = _split_value_unit(cy.group("value"))
                        unit = unit or u
                    elif py:
                        previous, u = _split_value_unit(py.group("value"))
                        unit = unit or u
                    owned_indices.append(j)
                    j += 1
                    continue

                # First semantic descendant starts a new branch; do not steal from it.
                break

            if current or previous:
                row = DebugRow(
                    indicator=_clean_indicator_and_code((INLINE_LABEL_DUP_VALUE_RE.match(ln.body).group("label") if INLINE_LABEL_DUP_VALUE_RE.match(ln.body) else ln.body.rstrip(":")))[0],
                    note=note,
                    previous=previous,
                    current=current,
                    unit=unit,
                    pattern_id=self.PATTERN_10,
                    source_start_line=ln.line_no,
                    source_end_line=max([ln.line_no] + [lines[x].line_no for x in owned_indices]),
                    raw_lines=[ln.raw] + [lines[x].raw for x in owned_indices],
                )
                rows.append(row)
                matches.append(row.debug_dict())
                consumed.add(i)
                consumed.update(owned_indices)

        # P12: single-line semantic row with explicit dates on both values.
        # Example:
        # * 1. Tiền gửi ...: 1.022.424 triệu đồng (31/12/2025);
        #   7.504 triệu đồng (31/12/2024)
        #
        # Dates are resolved chronologically; the newer date becomes Số năm nay.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            m = INLINE_EXPLICIT_DATE_RE.match(ln.body)
            if not m:
                continue

            v1, u1 = _split_value_unit(m.group("value1"))
            v2, u2 = _split_value_unit(m.group("value2"))

            def _date_key(raw: str) -> tuple[int, int, int]:
                d, mo, y = (int(x) for x in raw.split("/"))
                return (y, mo, d)

            pairs = sorted([
                (_date_key(m.group("date1")), v1, u1),
                (_date_key(m.group("date2")), v2, u2),
            ], key=lambda x: x[0])

            previous = pairs[0][1]
            current = pairs[-1][1]
            unit = pairs[-1][2] or pairs[0][2]

            row = DebugRow(
                indicator=_clean_label(m.group("label")),
                previous=previous,
                current=current,
                unit=unit,
                pattern_id=self.PATTERN_12,
                source_start_line=ln.line_no,
                source_end_line=ln.line_no,
                raw_lines=[ln.raw],
            )
            rows.append(row)
            consumed.add(i)
            matches.append(row.debug_dict())

        # P3: * **Chỉ tiêu:** X, then dated balance children.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet:
                continue
            m = NAMED_INDICATOR_RE.match(ln.body)
            if not m:
                continue
            vals: list[tuple[int, str, str, int]] = []
            unit = ""
            j = i + 1
            while j < len(lines):
                child = lines[j]
                if child.raw.strip() and child.is_bullet and child.indent <= ln.indent:
                    break
                dm = DATE_BALANCE_RE.match(child.body) if child.is_bullet else None
                if dm:
                    y = _year(dm.group("date"))
                    value, u = _split_value_unit(dm.group("value"))
                    if y:
                        vals.append((y, value, u, child.line_no)); consumed.add(j)
                        unit = unit or u
                j += 1
            if vals:
                vals.sort(key=lambda x: x[0])
                row = DebugRow(
                    indicator=_clean_label(m.group("label")),
                    previous=vals[0][1] if len(vals) > 1 else "",
                    current=vals[-1][1],
                    unit=unit,
                    pattern_id=self.PATTERN_3,
                    source_start_line=ln.line_no,
                    source_end_line=max(v[3] for v in vals),
                    raw_lines=[x.raw for x in lines[i:j]],
                )
                rows.append(row); consumed.add(i)
                matches.append(row.debug_dict())


        # P6: semantic label (optional inline note) + generic period children.
        # Supports both `Năm 2025: ...` and dated children such as
        # `31/12/2025: ...` / `Ngày 31/12/2025: ...`.  Reporting periods are
        # resolved chronologically: latest -> current, immediately previous -> previous.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            if (
                NOTE_CHILD_RE.match(ln.body)
                or CODE_CHILD_RE.match(ln.body)
                or INDICATOR_CODE_RE.match(ln.body)
                or END_YEAR_RE.match(ln.body)
                or START_YEAR_RE.match(ln.body)
                or DATE_BALANCE_RE.match(ln.body)
            ):
                continue

            label_text = ln.body
            note = ""
            sm = NOTE_SUFFIX_RE.match(label_text)
            if sm:
                label_text = sm.group("label").strip()
                note = _strip_md((sm.group("note") or "").strip())
            else:
                label_text = label_text.rstrip(":").strip()

            vals: list[tuple[tuple[int, int, int], str, str, int]] = []
            j = i + 1
            while j < len(lines):
                child = lines[j]
                if child.raw.strip() and child.is_bullet and child.indent <= ln.indent:
                    break
                if child.is_bullet and child.body:
                    gm = GENERIC_PERIOD_VALUE_RE.match(child.body)
                    if gm:
                        if gm.group("date"):
                            d, m, y = [int(x) for x in gm.group("date").split("/")]
                            period_key = (y, m, d)
                        else:
                            y = int(gm.group("year"))
                            period_key = (y, 12, 31)
                        value, u = _split_value_unit(gm.group("value"))
                        vals.append((period_key, value, u, child.line_no))
                        consumed.add(j)
                    elif child.indent > ln.indent:
                        # Another semantic child starts a nested branch.  Its own
                        # period descendants are not owned by this parent.
                        # Stop once such a sibling-level semantic child appears.
                        break
                j += 1

            if vals:
                vals.sort(key=lambda x: x[0])
                current = vals[-1][1]
                previous = vals[-2][1] if len(vals) >= 2 else ""
                unit = vals[-1][2] or (vals[-2][2] if len(vals) >= 2 else "")
                row = DebugRow(
                    indicator=_clean_indicator_and_code(label_text)[0], note=note, previous=previous, current=current, unit=unit,
                    pattern_id=self.PATTERN_6, source_start_line=ln.line_no, source_end_line=max(v[3] for v in vals),
                    raw_lines=[x.raw for x in lines[i:j]],
                )
                rows.append(row); consumed.add(i)
                matches.append(row.debug_dict())

        # P1: semantic label parent + note/current/previous descendants owned by
        # the NEAREST semantic ancestor.  This is intentionally more tolerant than
        # requiring an exact direct-child indent: LLM/OCR Markdown often shifts
        # sibling attribute rows by a few spaces.  At the same time, once a nested
        # semantic label is encountered, attributes inside that nested branch belong
        # to the nested label and must never overwrite the parent.
        for i, ln in enumerate(lines):
            if i in consumed or not ln.is_bullet or not ln.body:
                continue
            # P1 parent must not itself be an attribute/value line.
            if (
                NOTE_CHILD_RE.match(ln.body)
                or CODE_CHILD_RE.match(ln.body)
                or INDICATOR_CODE_RE.match(ln.body)
                or END_YEAR_RE.match(ln.body)
                or START_YEAR_RE.match(ln.body)
                or DATE_BALANCE_RE.match(ln.body)
            ):
                continue
            note = previous = current = unit = ""
            p1_period_obs = []
            end = ln.line_no
            j = i + 1

            # Stack of nested semantic labels seen inside this parent's subtree.
            # Each entry is (indent, line_index).  Attribute rows are assigned only
            # when the nearest semantic ancestor is the current parent (i).
            semantic_stack: list[tuple[int, int]] = []

            while j < len(lines):
                child = lines[j]
                if child.raw.strip() and child.is_bullet and child.indent <= ln.indent:
                    break

                if not child.is_bullet or not child.body:
                    j += 1
                    continue

                nm = NOTE_CHILD_RE.match(child.body)
                em = END_YEAR_RE.match(child.body)
                sm = START_YEAR_RE.match(child.body)
                dm = DATE_BALANCE_RE.match(child.body)
                cm = CODE_CHILD_RE.match(child.body)
                icm = INDICATOR_CODE_RE.match(child.body)
                gp = _parse_period_value_line(child.body)
                is_attribute = bool(nm or em or sm or dm or cm or icm or gp)

                # Close nested semantic branches when indentation returns to their
                # level or above.  Attribute indentation itself is allowed to vary.
                while semantic_stack and semantic_stack[-1][0] >= child.indent:
                    semantic_stack.pop()

                if is_attribute:
                    # If another semantic label is currently open between the
                    # current parent and this attribute, that nested label owns it.
                    if not semantic_stack:
                        if nm:
                            note = _strip_md(nm.group("note")); consumed.add(j)
                        elif em:
                            current, u = _split_value_unit(em.group("value"))
                            u = u or (em.groupdict().get("unit_hint") or "").strip()
                            unit = unit or u
                            consumed.add(j)
                        elif sm:
                            previous, u = _split_value_unit(sm.group("value"))
                            u = u or (sm.groupdict().get("unit_hint") or "").strip()
                            unit = unit or u
                            consumed.add(j)
                        elif cm or icm:
                            # Structural code attribute only; consume it so it does
                            # not appear as an unmatched semantic row.
                            consumed.add(j)
                        elif gp:
                            p1_period_obs.append(gp)
                            consumed.add(j)
                        # DATE_BALANCE_RE belongs to P3 and is intentionally not
                        # consumed here.
                        if nm or em or sm or cm or icm:
                            end = child.line_no
                else:
                    # A non-attribute bullet is a nested semantic/container branch.
                    # Its descendants must not be attributed to this parent.
                    semantic_stack.append((child.indent, j))

                j += 1

            if p1_period_obs:
                gp_prev, gp_cur, gp_unit = _resolve_period_obs(p1_period_obs)
                previous = previous or gp_prev
                current = current or gp_cur
                unit = unit or gp_unit

            # P1 may legitimately contain only one reporting-period value.
            if current or previous:
                row = DebugRow(
                    indicator=_clean_label(ln.body), note=note, previous=previous, current=current, unit=unit,
                    pattern_id=self.PATTERN_1, source_start_line=ln.line_no, source_end_line=end,
                    raw_lines=[x.raw for x in lines[i:j]],
                )
                rows.append(row); consumed.add(i)
                matches.append(row.debug_dict())

        # P8: non-bullet semantic heading followed by bullet attributes.
        # Heading owns only its direct attribute block; nested semantic headings/bullets
        # start new records. Mã số is consumed for structure/debug but is not emitted
        # because the requested CSV has only 5 columns.
        for i, ln in enumerate(lines):
            if i in consumed or ln.is_bullet or not ln.body:
                continue
            if INLINE_EXPLICIT_YEAR_RE.match(ln.body) or INLINE_YEAR_RE.match(ln.body):
                continue

            label_text = ln.body.rstrip(":").strip()
            if not label_text:
                continue

            note = previous = current = unit = ""
            end = ln.line_no
            j = i + 1

            while j < len(lines):
                child = lines[j]

                # A new non-bullet heading at same/shallower indent closes this block.
                if child.raw.strip() and not child.is_bullet and child.body:
                    break

                if not child.is_bullet or not child.body:
                    j += 1
                    continue

                nm = NOTE_CHILD_RE.match(child.body)
                em = END_YEAR_RE.match(child.body)
                sm = START_YEAR_RE.match(child.body)
                cm = CODE_CHILD_RE.match(child.body)
                icm = INDICATOR_CODE_RE.match(child.body)

                if nm or em or sm or cm or icm:
                    if nm:
                        note = _strip_md(nm.group("note"))
                    elif em:
                        current, u = _split_value_unit(em.group("value"))
                        u = u or (em.groupdict().get("unit_hint") or "").strip()
                        unit = unit or u
                    elif sm:
                        previous, u = _split_value_unit(sm.group("value"))
                        u = u or (sm.groupdict().get("unit_hint") or "").strip()
                        unit = unit or u
                    # Mã số / Chỉ tiêu numeric are structural account codes only;
                    # they are intentionally not written to the requested CSV.
                    consumed.add(j)
                    end = child.line_no
                    j += 1
                    continue

                # First non-attribute bullet is a semantic/container node and
                # belongs to its own record, regardless of its exact indentation.
                # This prevents the heading from stealing note/value attributes
                # from deeper semantic descendants.
                break

            if current or previous:
                row = DebugRow(
                    indicator=_clean_indicator_and_code(label_text)[0],
                    note=note, previous=previous, current=current, unit=unit,
                    pattern_id=self.PATTERN_8,
                    source_start_line=ln.line_no, source_end_line=end,
                    raw_lines=[x.raw for x in lines[i:j]],
                )
                rows.append(row)
                consumed.add(i)
                matches.append(row.debug_dict())

        # P4: period containers. Collect same semantic labels across period blocks.
        period_blocks: list[tuple[int, int, int, int]] = []  # (index, year, indent, end_index)
        for i, ln in enumerate(lines):
            if not ln.is_bullet:
                continue
            pm = PERIOD_CONTAINER_RE.match(ln.body)
            if not pm:
                continue
            y = _year(pm.group("date"))
            if not y:
                continue
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.is_bullet and nxt.indent <= ln.indent and PERIOD_CONTAINER_RE.match(nxt.body):
                    break
                # stop at clear non-bullet heading after block
                if j > i + 1 and nxt.body and not nxt.is_bullet and nxt.indent <= ln.indent and nxt.raw.strip().startswith("#"):
                    break
                j += 1
            period_blocks.append((i, y, ln.indent, j))

        if len({y for _, y, _, _ in period_blocks}) >= 2:
            bucket: dict[tuple[str, tuple[str, ...]], dict] = {}
            for i, y, base_indent, j in period_blocks:
                stack: list[tuple[int, str]] = []
                for k in range(i + 1, j):
                    child = lines[k]
                    if not child.is_bullet or child.indent <= base_indent:
                        continue
                    kv = KEY_VALUE_RE.match(child.body)
                    if not kv:
                        continue
                    label = _clean_label(kv.group("label"))
                    value, u = _split_value_unit(kv.group("value"))
                    # Only accept value-like right-hand sides.
                    if not NUM_RE.match(value.replace("-", "0")) and value not in {"-", "—"}:
                        continue
                    while stack and stack[-1][0] >= child.indent:
                        stack.pop()
                    path = tuple(x[1] for x in stack)
                    key = (_norm(label), path)
                    rec = bucket.setdefault(key, {"label": label, "values": {}, "unit": "", "lines": [], "first": child.line_no, "last": child.line_no})
                    rec["values"][y] = value
                    rec["unit"] = rec["unit"] or u
                    rec["lines"].append(child.raw)
                    rec["last"] = child.line_no
                    stack.append((child.indent, label))
                    consumed.add(k)
            years = sorted({y for _, y, _, _ in period_blocks})
            prev_y, curr_y = years[0], years[-1]
            for rec in bucket.values():
                if curr_y not in rec["values"] and prev_y not in rec["values"]:
                    continue
                row = DebugRow(
                    indicator=rec["label"], previous=rec["values"].get(prev_y, ""), current=rec["values"].get(curr_y, ""),
                    unit=rec["unit"], pattern_id=self.PATTERN_4, source_start_line=rec["first"], source_end_line=rec["last"],
                    raw_lines=rec["lines"],
                )
                rows.append(row); matches.append(row.debug_dict())

        # Stable source order, then pattern. Deduplicate exact extracted payloads.
        unique: list[DebugRow] = []
        seen = set()
        for row in sorted(rows, key=lambda r: (r.source_start_line, r.pattern_id, r.indicator)):
            key = (row.indicator, row.note, row.previous, row.current, row.unit)
            if key in seen:
                continue
            seen.add(key); unique.append(row)

        unmatched = []
        for i, ln in enumerate(lines):
            if ln.is_bullet and ln.body and i not in consumed:
                unmatched.append({"line_no": ln.line_no, "indent": ln.indent, "body": ln.body, "raw": ln.raw})

        debug = {
            "flow_version": "bullet-debug-0.5.2-flat-row",
            "supported_patterns": [self.PATTERN_1, self.PATTERN_2, self.PATTERN_3, self.PATTERN_4, self.PATTERN_5, self.PATTERN_6, self.PATTERN_7, self.PATTERN_8, self.PATTERN_9, self.PATTERN_10, self.PATTERN_11, self.PATTERN_12, self.PATTERN_13, self.PATTERN_14, self.PATTERN_15, self.PATTERN_16, self.PATTERN_17, self.PATTERN_18, self.PATTERN_19, self.PATTERN_20, self.PATTERN_21, self.PATTERN_22, self.PATTERN_23, self.PATTERN_24, self.PATTERN_25, self.PATTERN_26, self.PATTERN_27, self.PATTERN_28, self.PATTERN_29, self.PATTERN_30, self.PATTERN_31, self.PATTERN_32, self.PATTERN_33, self.PATTERN_34],
            "row_count": len(unique),
            "pattern_counts": {p: sum(1 for r in unique if r.pattern_id == p) for p in [self.PATTERN_1, self.PATTERN_2, self.PATTERN_3, self.PATTERN_4, self.PATTERN_5, self.PATTERN_6, self.PATTERN_7, self.PATTERN_8, self.PATTERN_9, self.PATTERN_10, self.PATTERN_11, self.PATTERN_12, self.PATTERN_13, self.PATTERN_14, self.PATTERN_15, self.PATTERN_16, self.PATTERN_17, self.PATTERN_18, self.PATTERN_19, self.PATTERN_20, self.PATTERN_21, self.PATTERN_22, self.PATTERN_23, self.PATTERN_24, self.PATTERN_25, self.PATTERN_26, self.PATTERN_27, self.PATTERN_28, self.PATTERN_29, self.PATTERN_30, self.PATTERN_31, self.PATTERN_32, self.PATTERN_33, self.PATTERN_34]},
            "matches": [r.debug_dict() for r in unique],
            "unmatched_bullets": unmatched,
            "column_major_warnings": column_major_warnings,
        }
        return unique, debug

    def run_file(self, input_path: str | Path, output_csv: str | Path, debug_json: str | Path | None = None) -> tuple[list[DebugRow], dict]:
        input_path = Path(input_path)
        text = input_path.read_text(encoding="utf-8-sig", errors="replace")
        rows, debug = self.extract(text)
        output_csv = Path(output_csv)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Chỉ tiêu", "Thuyết minh", "Số năm trước", "Số năm nay", "Đơn vị"])
            writer.writeheader()
            for row in rows:
                writer.writerow(row.csv_dict())
        if debug_json:
            dp = Path(debug_json); dp.parent.mkdir(parents=True, exist_ok=True)
            dp.write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
        return rows, debug
