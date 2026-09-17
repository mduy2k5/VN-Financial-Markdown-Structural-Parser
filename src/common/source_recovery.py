from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

try:
    from .value_semantics import detect_statement_unit, row_unit_override, is_note_reference
    from .period_resolver import period_role_for_date
    from .report_period import resolve_report_years
except ImportError:
    from value_semantics import detect_statement_unit, row_unit_override, is_note_reference
    from period_resolver import period_role_for_date
    from report_period import resolve_report_years


def clean(s: Any) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"[*_`#]+", "", s)
    return re.sub(r"\s+", " ", s).strip(" |:\t\r\n")


def fold(s: Any) -> str:
    s = unicodedata.normalize("NFD", clean(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def parse_number(v: Any):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = clean(v).replace("−", "-")
    if not s:
        return None
    # Source-fidelity rule: a dash is an unreported / no-occurrence marker, not a
    # reported numeric zero. Formula validation may treat None as 0 in a separate view.
    if s in {"-", "–", "—"}:
        return None
    neg = s.startswith("(") and ")" in s
    s = s.strip().strip("()")
    # Keep only the leading numeric token; units / year annotations may follow.
    m = re.match(r"-?\d[\d., ]*", s)
    if not m:
        return None
    s = m.group(0).replace(" ", "")
    try:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
            x = int(s.replace(".", ""))
        elif re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", s):
            x = int(s.replace(",", ""))
        elif re.fullmatch(r"-?\d+", s):
            x = int(s)
        elif re.fullmatch(r"-?\d+[.,]\d+", s):
            x = float(s.replace(",", "."))
        else:
            # mixed separators: last separator is decimal only for short tail, otherwise thousands
            if "," in s and "." in s:
                last = max(s.rfind(","), s.rfind("."))
                tail = s[last + 1:]
                if len(tail) <= 2:
                    head = re.sub(r"[.,]", "", s[:last])
                    x = float(head + "." + tail)
                else:
                    x = int(re.sub(r"[.,]", "", s))
            else:
                x = int(re.sub(r"[.,]", "", s))
        return -abs(x) if neg else x
    except Exception:
        return None


@dataclass
class RecoveredRow:
    label: str
    current: Optional[float]
    previous: Optional[float]
    code: Optional[str] = None
    note: Optional[str] = None
    statement_code: Optional[str] = None
    note_ref: Optional[str] = None
    section: Optional[str] = None
    source_line: Optional[int] = None
    pattern: Optional[str] = None
    parent_label: Optional[str] = None
    hierarchy_path: Optional[str] = None
    unit: Optional[str] = None
    unit_source: Optional[str] = None

    def __post_init__(self):
        if self.statement_code is None:
            self.statement_code = self.code
        if self.code is None:
            self.code = self.statement_code
        if self.note_ref is None:
            self.note_ref = self.note
        if self.note is None:
            self.note = self.note_ref


FP_HEADING = re.compile(r"(?i)(?:BẢNG\s+CÂN\s+ĐỐI\s+KẾ\s+TOÁN|BÁO\s+CÁO\s+TÌNH\s+HÌNH\s+TÀI\s+CHÍNH)(?:\s+HỢP\s+NHẤT)?")
NEXT_STATEMENT = re.compile(r"(?i)^(?:BÁO\s+CÁO\s+KẾT\s+QUẢ\s+HOẠT\s+ĐỘNG(?:\s+KINH\s+DOANH)?|BÁO\s+CÁO\s+LƯU\s+CHUYỂN\s+TIỀN\s+TỆ|THUYẾT\s+MINH\s+BÁO\s+CÁO\s+TÀI\s+CHÍNH)")
NOTES_ONLY_FP = re.compile(r"(?i)THÔNG\s+TIN\s+BỔ\s+SUNG.*(?:BẢNG\s+CÂN\s+ĐỐI|TÌNH\s+HÌNH\s+TÀI\s+CHÍNH)")


def _is_fp_heading_line(line: str) -> bool:
    f = fold(line)
    return any(x in f for x in (
        "bang can doi ke toan", "bao cao can doi ke toan",
        "bao cao tinh hinh tai chinh", "bang tinh hinh tai chinh"
    )) and "thong tin bo sung" not in f and "thuyet minh" not in f


def _is_next_statement_line(line: str) -> bool:
    f = fold(line)
    return (
        "bao cao ket qua hoat dong" in f or
        "bao cao ket qua kinh doanh" in f or
        "bao cao luu chuyen tien te" in f or
        f.startswith("thuyet minh bao cao tai chinh")
    )


def choose_financial_position_scope(text: str):
    lines = text.splitlines()
    cand = []
    for i, line in enumerate(lines):
        c = clean(line)
        if _is_fp_heading_line(c) and len(c) <= 160:
            end = len(lines)
            for j in range(i + 1, min(len(lines), i + 1600)):
                if _is_next_statement_line(lines[j]):
                    end = j
                    break
            sample = "\n".join(lines[i:min(end, i + 1200)])
            f = fold(sample)
            score = 0
            score += 80 * sum(k in f for k in ("tai san", "no phai tra", "von chu so huu"))
            score += 80 if "tong cong tai san" in f or "tong tai san" in f else 0
            score += 40 if re.search(r"(?i)B\s*0?2[a-z]?\s*/\s*TCTD|B\s*0?1\s*[-–]?\s*DN", sample[:3000]) else 0
            score += min(260, len(re.findall(r"(?i)(?:(?:Số\s*)?(?:cuối|đầu)\s+năm|31[./-]12[./-]20\d{2})\s*:", sample)) * 4)
            score += min(220, len(re.findall(r"\|[^\n]+\|[^\n]+\|[^\n]+\|", sample)) * 3)
            score += min(220, len(re.findall(r"\(?-?\d{1,3}(?:[.,]\d{3}){1,}\)?", sample)) // 3)
            if "tiep theo" not in fold(c): score += 120
            if i < 120: score -= 80
            cand.append((score, i, end))

    # Fallback when the first page heading was lost by OCR/LLM but the body clearly contains B02/FP anchors.
    if not cand:
        next_stmt = next((i for i,l in enumerate(lines) if _is_next_statement_line(l)), len(lines))
        search_end = min(next_stmt, 1400)
        anchors = []
        for i in range(search_end):
            f = fold(lines[i])
            if ("b02" in f and "tctd" in f) or "tong cong tai san" in f or "tong no phai tra va von chu so huu" in f:
                anchors.append(i)
        if anchors:
            a = min(anchors)
            # Walk back to the beginning of the page/content block rather than taking just the anchor row.
            s0 = max(0, a - 260)
            for j in range(a, max(-1, a-320), -1):
                if fold(lines[j]).startswith("content") or re.match(r"^#\s*Page\s+", clean(lines[j]), re.I):
                    s0 = j + 1; break
            sample = "\n".join(lines[s0:search_end])
            score = 220 + min(240, len(re.findall(r"\(?-?\d{1,3}(?:[.,]\d{3}){1,}\)?", sample)) // 2)
            cand.append((score, s0, search_end))

    if not cand:
        return {"scope_start_line": None, "scope_end_line": None, "scope_score": 0}
    max_score = max(x[0] for x in cand)
    eligible = [x for x in cand if x[0] >= max_score - 180]
    score, s, e = min(eligible, key=lambda x: x[1])
    # Always extend to the first following different statement. This joins continuation pages.
    for j in range(s + 1, min(len(lines), s + 1800)):
        if _is_next_statement_line(lines[j]):
            e = j; break
    return {"scope_start_line": s + 1, "scope_end_line": e, "scope_score": score}


_YEAR_VALUE_PATTERNS = [
    re.compile(r"(?i)^Năm\s+kết\s+thúc\s+31[./-]12[./-](20\d{2})(?:\s*\([^)]*\))*\s*:\s*(.+)$"),
    # `31/12/2025 Triệu VND: 123`, optionally with audited annotation.
    re.compile(r"(?i)^(?:Tại\s+ngày\s+)?31[./-]12[./-](20\d{2})(?:\s+(?:triệu|nghìn)\s*(?:đồng|vnd|vnđ))?(?:\s*\([^)]*\))?\s*:\s*(.+)$"),
    # `Ngày 31 tháng 12 năm 2025 (triệu đồng): 123`
    re.compile(r"(?i)^Ngày\s+31\s+tháng\s+12\s+năm\s+(20\d{2})(?:\s*\([^)]*\))?\s*:\s*(.+)$"),
    re.compile(r"(?i)^(?:Năm\s*)?(20\d{2})(?:\s+(?:triệu|nghìn)\s*(?:đồng|vnd|vnđ))?(?:\s*\([^)]*\))?\s*:\s*(.+)$"),
]


def _explicit_fp_period_value(text: str, current_year: int, previous_year: int):
    """Return (role, value) for explicit FP period children.

    Important accounting identity:
      01/01/current_year == opening balance == previous comparative period.
    """
    c = re.sub(r"^[*+\-]\s+", "", clean(text))

    date_patterns = [
        # Tại ngày 31/12/2025: 123
        re.compile(
            r"(?i)^(?:Tại\s+ngày\s+|Ngày\s+)?"
            r"(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>20\d{2})"
            r"(?:\s*\([^)]*\))?\s*:\s*(?P<value>.+)$"
        ),
        # Ngày 31 tháng 12 năm 2025: 123
        re.compile(
            r"(?i)^(?:Tại\s+)?Ngày\s+"
            r"(?P<day>\d{1,2})\s+tháng\s+(?P<month>\d{1,2})\s+năm\s+(?P<year>20\d{2})"
            r"(?:\s*\([^)]*\))?\s*:\s*(?P<value>.+)$"
        ),
    ]

    for pat in date_patterns:
        m = pat.match(c)
        if not m:
            continue
        day = int(m.group("day"))
        month = int(m.group("month"))
        year = int(m.group("year"))
        value = parse_number(m.group("value"))

        role = period_role_for_date(day, month, year, current_year, previous_year)
        if role:
            return role, value

    m = re.match(r"(?i)^Năm\s+nay\s*:\s*(.+)$", c)
    if m:
        return "current", parse_number(m.group(1))

    m = re.match(r"(?i)^Năm\s+trước\s*:\s*(.+)$", c)
    if m:
        return "previous", parse_number(m.group(1))

    m = re.match(r"(?i)^Năm\s+(20\d{2})\s*:\s*(.+)$", c)
    if m:
        y = int(m.group(1))
        if y == current_year:
            return "current", parse_number(m.group(2))
        if y == previous_year:
            return "previous", parse_number(m.group(2))

    # Some Markdown/OCR layouts omit the `Số` prefix:
    # `Cuối năm: 123` / `Đầu năm: 100`.
    m = re.match(r"(?i)^(?:Số\s*)?Cuối\s+năm(?:\s*\([^)]*\))?\s*:\s*(.+)$", c)
    if m:
        return "current", parse_number(m.group(1))

    m = re.match(r"(?i)^(?:Số\s*)?Đầu\s+năm(?:\s*\([^)]*\))?\s*:\s*(.+)$", c)
    if m:
        return "previous", parse_number(m.group(1))

    return None


def _inline_end_begin_values(line: str):
    s = clean(line)
    cur = prev = None
    # `578.891 triệu đồng (Cuối năm) | 1.209.509 triệu đồng (Đầu năm)`
    mc = re.search(r"(\(?-?\d[\d., ]*\)?|-)\s*(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*\(\s*Cuối\s+năm\s*\)", s, re.I)
    mp = re.search(r"(\(?-?\d[\d., ]*\)?|-)\s*(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*\(\s*Đầu\s+năm\s*\)", s, re.I)
    if mc: cur = parse_number(mc.group(1))
    if mp: prev = parse_number(mp.group(1))
    return cur, prev


def _inline_year_values(line: str, current_year: int, previous_year: int):
    s = clean(line)
    vals = {}
    # value then explicit year/date marker: `123 triệu đồng (năm 31.12.2025)` / `123 (31.12.2025)`
    p = re.compile(
        r"(?P<val>\(?-?\d[\d., ]*\)?|-)\s*(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng)?\s*"
        r"\(\s*(?:năm\s*)?(?:31[./-]12[./-])?(?P<year>20\d{2})\s*\)", re.I)
    for m in p.finditer(s):
        vals[int(m.group("year"))] = parse_number(m.group("val"))
    # Financial-position OCR commonly writes `(31/12/2025)` and `(1/1/2025)`
    # instead of a bare year.  The opening date of the current year is the
    # previous comparative balance.
    p_date = re.compile(
        r"(?P<val>\(?-?\d[\d., ]*\)?|-)\s*"
        r"(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*"
        r"\(\s*(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>20\d{2})\s*\)",
        re.I,
    )
    for m in p_date.finditer(s):
        day = int(m.group("day")); month = int(m.group("month")); year = int(m.group("year"))
        value = parse_number(m.group("val"))
        if value is None:
            continue
        role = period_role_for_date(day, month, year, current_year, previous_year)
        if role == "current":
            vals[current_year] = value
        elif role == "previous":
            vals[previous_year] = value
    # `(Năm 2024: 123 triệu đồng)` annotation after an unlabelled current value.
    p2 = re.compile(r"(?i)\(\s*Năm\s*(20\d{2})\s*:\s*(\(?-?\d[\d., ]*\)?|-)\s*(?:triệu\s*(?:đồng|VND|VNĐ)|VND|VNĐ|đồng)?\s*\)")
    for m in p2.finditer(s):
        vals[int(m.group(1))] = parse_number(m.group(2))
    # If previous was explicit in parentheses, current is usually the value immediately after the label colon.
    if previous_year in vals and current_year not in vals:
        head = s[:p2.search(s).start()] if p2.search(s) else s
        mc = re.search(r":\s*(\(?-?\d[\d., ]*\)?|-)\s*(?:triệu\s*(?:đồng|VND|VNĐ)|VND|VNĐ|đồng)?\s*$", head, re.I)
        if mc:
            vals[current_year] = parse_number(mc.group(1))
    return vals.get(current_year), vals.get(previous_year)


def _inline_row_label(line: str) -> str:
    """Return the semantic label before a value, including embedded Mã số."""

    code_suffix = re.search(r"\(\s*Mã\s*số\s*:.*?\)\s*:\s*", line, re.I)
    if code_suffix:
        return clean(line[:code_suffix.start()])
    return clean(line.split(":", 1)[0])


def _normalize_row_label(label: str):
    s = clean(label)
    s = re.sub(r"(?i)^Chỉ\s*tiêu\s*:\s*", "", s)
    return clean(s)


def _split_code_label(label: str):
    """Split a real form-code prefix from a display ordinal.

    Single-digit/roman prefixes in Vietnamese statements are usually hierarchy markers
    (1., II., III.) rather than statutory form codes.  We strip those from the label but do
    not expose them as ``form_code``.  Two-or-more digit numeric prefixes (01, 100, 311...)
    are retained as form codes.
    """
    label = clean(label)
    m = re.match(r"^([0-9]{1,4}(?:\.[0-9]+)?|[IVXLC]+)[.)-]?\s+(.+)$", label, re.I)
    if not m:
        return None, label
    prefix, rest = m.group(1), clean(m.group(2))
    if re.fullmatch(r"\d{2,4}(?:\.\d+)?", prefix):
        return prefix, rest
    return None, rest



def _extract_trailing_form_code(label: str):
    raw = clean(label)
    m = re.search(r"\(\s*(\d{2,4}(?:\.\d+)?)\s*\)\s*$", raw)
    if not m:
        return raw, None
    return clean(raw[:m.start()]), clean(m.group(1))


def _extract_suffix_meta(label: str):
    """Extract `(Mã số: ..., Thuyết minh: ...)` while preserving the human label."""
    raw = clean(label)
    code = note = None
    m = re.search(r"\(\s*Mã\s*số\s*:\s*([^,;)]+)(?:\s*,\s*Thuyết\s*minh\s*:\s*([^;)]+))?\s*\)", raw, re.I)
    if m:
        code = clean(m.group(1))
        note = clean(m.group(2)) if m.group(2) else None
        raw = clean(raw[:m.start()] + " " + raw[m.end():])
    else:
        m2 = re.search(r"\(\s*Thuyết\s*minh\s*:\s*([^;)]+)\s*\)", raw, re.I)
        if m2:
            note = clean(m2.group(1)); raw = clean(raw[:m2.start()] + " " + raw[m2.end():])
    return raw, code, note

def _valid_label(label: str):
    f = fold(label)
    if not label or len(f) < 2:
        return False
    bad = (
        "metadata", "search folder", "s3 key", "created at", "updated at", "page ocr", "file name",
        "nguoi lap", "ke toan truong", "tong giam doc", "giam doc", "don vi tinh", "mau so",
        "bao cao tai chinh hop nhat", "cho nam tai chinh ket thuc", "cac thuyet minh tu trang",
    )
    return not any(f.startswith(x) or x in f for x in bad)



def _is_period_value_line(text: str) -> bool:
    c = clean(text)
    c = re.sub(r"^[*+\-]\s+", "", c)
    f = fold(c)
    return bool(
        re.match(r"(?i)^(?:Mã\s*số|Thuyết\s*minh|Số\s*thuyết\s*minh|(?:Số\s*)?Cuối\s*năm(?:\s*\([^)]*\))?|(?:Số\s*)?Đầu\s*năm(?:\s*\([^)]*\))?|Số\s*liệu(?:\s*\([^)]*\))?|Tại\s+ngày|Năm\s+kết\s+thúc\s+31[./-]12[./-]20\d{2}(?:\s*\([^)]*\))*|Năm\s*20\d{2}|20\d{2})\s*:", c)
        or re.match(r"^(?:ngay\s+)?31(?:\s+thang\s+12\s+nam\s*|\s+12\s+|[./-]12[./-])20\d{2}", f)
        or re.match(r"^(?:tai\s+ngay\s+|ngay\s+)?0?1(?:\s+thang\s+0?1\s+nam\s*|\s+0?1\s+|[./-]0?1[./-])20\d{2}", f)
    )


def _markdown_indent_and_label(raw: str):
    """Return approximate structural indent and cleaned bullet/heading label."""
    expanded = raw.expandtabs(4)
    leading = len(expanded) - len(expanded.lstrip(" "))
    c = clean(raw)
    c = re.sub(r"^[*+\-]\s+", "", c)
    c = re.sub(r"^\d+[.)]\s+", lambda m: m.group(0), c)
    return leading, clean(c)


def _hierarchy_context(scoped: list[str]):
    """Infer nearest textual parents from Markdown indentation without changing source labels."""
    stack: list[tuple[int, str]] = []
    out: dict[int, tuple[Optional[str], Optional[str]]] = {}
    for idx, raw in enumerate(scoped):
        indent, label = _markdown_indent_and_label(raw)
        if not label or _is_period_value_line(label) or re.fullmatch(r"\(?-?[\d.,]+\)?|-", label):
            continue
        if not _valid_label(label):
            continue
        # metadata/headings are not row parents
        f = fold(label)
        if f in {"tai san", "nguon von", "no phai tra", "von chu so huu", "chi tieu", "ma so", "thuyet minh", "so cuoi nam", "so dau nam"}:
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, label))
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else None
        path = " > ".join(x[1] for x in stack[-3:]) if stack else None
        out[idx] = (parent, path)
        stack.append((indent, label))
    return out


def _extract_explicit_inline_year_pair(line: str, current_year: int, previous_year: int):
    """Parse `123 (2025), 456 (2024)` and similar forms."""
    s = clean(line)
    vals = {}
    p = re.compile(r"(?P<val>\(?-?\d[\d., ]*\)?|-)\s*(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*\(\s*(?P<year>20\d{2})\s*\)", re.I)
    for m in p.finditer(s):
        vals[int(m.group('year'))] = parse_number(m.group('val'))
    return vals.get(current_year), vals.get(previous_year)


def _looks_like_form_code_token(token: str) -> bool:
    t = clean(token)
    if not re.fullmatch(r"\d{2,4}(?:\.\d+)?", t):
        return False
    # statutory statement row codes are generally compact and not thousands-formatted amounts
    return "." not in t or len(t.split('.')[0]) <= 4


def _looks_like_note_token(token: str) -> bool:
    t = clean(token)
    return bool(re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?(?:\s*,\s*\d{1,2}(?:\.\d{1,2})?)*", t))


def _positional_numeric_children(scoped: list[str], s: int, current_year: int, previous_year: int, statement: str, hierarchy):
    """Recover column-major rows where label/code/note/current/previous are emitted as sibling lines.

    This is common in OCR/LLM Markdown where a table row becomes:
      label -> code -> note? -> current -> previous
    and the period values themselves have no `Số cuối năm`/year prefix.
    """
    rows: list[RecoveredRow] = []
    for idx, raw in enumerate(scoped):
        if raw.count("|") >= 3:
            continue
        c = clean(raw)
        if not _valid_label(c) or _is_period_value_line(c):
            continue
        if ":" in c and re.search(r":\s*\(?-?\d", c):
            continue
        # Reject numeric-looking labels, metadata and section-only headings.
        if re.fullmatch(r"\(?-?[\d., ]+\)?|-", c) or fold(c) in {"tai san", "nguon von", "no phai tra", "von chu so huu"}:
            continue
        base_label, suffix_code, suffix_note = _extract_suffix_meta(c.rstrip(':'))
        base_label, trailing_code = _extract_trailing_form_code(base_label)
        suffix_code = suffix_code or trailing_code
        code_from_label, label = _split_code_label(base_label)
        label = _normalize_row_label(label)
        if suffix_code:
            code_from_label = suffix_code
        vals: list[tuple[int, str, Any]] = []
        for j in range(idx + 1, min(len(scoped), idx + 10)):
            cc = clean(scoped[j])
            if not cc:
                continue
            if _is_period_value_line(cc):
                break
            # next textual row starts => no more children
            if re.search(r"[A-Za-zÀ-ỹ]", cc) and not re.fullmatch(r"\(?-?[\d., ]+\)?|-", cc):
                break
            v = parse_number(cc)
            if v is not None:
                vals.append((j, cc, v))
            if len(vals) >= 4:
                break
        if len(vals) < 2:
            continue
        code = code_from_label
        note = suffix_note
        data = list(vals)
        if code is None and data and _looks_like_form_code_token(data[0][1]):
            # do not treat obvious large thousand-separated number as a code
            if not re.search(r"[.,]\d{3}[.,]", data[0][1]) and len(re.sub(r"\D", "", data[0][1])) <= 4:
                code = clean(data.pop(0)[1])
        if len(data) >= 3 and _looks_like_note_token(data[0][1]) and abs(float(data[0][2])) < 100:
            note = clean(data.pop(0)[1])
        if len(data) < 2:
            continue
        cur, prev = data[0][2], data[1][2]
        parent, path = hierarchy.get(idx, (None, None))
        rows.append(RecoveredRow(label=label, current=cur, previous=prev, code=code, note=note,
                                 source_line=s+idx+1, pattern=f"{statement}_RAW_POSITIONAL_COLUMNS",
                                 parent_label=parent, hierarchy_path=path))
    return rows


def _period_header_year(text: str):
    c = re.sub(r"^[*+\-]\s+", "", clean(text))
    pats = [
        r"(?i)^Năm\s+kết\s+thúc\s+31[./-]12[./-](20\d{2})(?:\s*\([^)]*\))*\s*:?\s*$",
        r"(?i)^(?:Năm\s*)?(20\d{2})(?:\s*\([^)]*\))*\s*:?\s*$",
    ]
    for p in pats:
        m = re.match(p, c)
        if m:
            return int(m.group(1))
    return None


def _inline_form_code_child_rows(scoped: list[str], s: int, current_year: int,
                                 previous_year: int, statement: str, hierarchy):
    """Recover rows whose form code is embedded in the label.

    A frequent Markdown/OCR shape is::

        * 1. Phải trả người bán ngắn hạn (Mã số: 311)
            * Số cuối năm: 100
            * Số đầu năm (Trình bày lại): 90

    The generic parent/child walker cannot safely use indentation here because
    the next sibling label is often at the same indentation as the first value
    child.  This pass anchors on the inline form code and only consumes the
    explicit period children immediately below it.
    """
    rows: list[RecoveredRow] = []
    code_label = re.compile(
        r"(?i)^(?P<label>.+?)\s*\(\s*Mã\s*số\s*:\s*"
        r"(?P<code>[0-9]{1,4}[A-Za-z]?(?:\.[0-9]+)?)"
        r"(?:\s*,\s*Thuyết\s*minh\s*:\s*[^;)]+)?\s*\)\s*$"
    )
    current_re = re.compile(
        r"(?i)^(?:Số\s*)?Cuối\s*năm(?:\s*\([^)]*\))?\s*:\s*(.+)$"
    )
    previous_re = re.compile(
        r"(?i)^(?:Số\s*)?Đầu\s*năm(?:\s*\([^)]*\))?\s*:\s*(.+)$"
    )
    restated_re = re.compile(
        r"(?i)^Số\s*liệu\s*\(\s*(?:Trình\s*bày\s*lại|Đầu\s*năm|Năm\s*20\d{2})\s*\)\s*:\s*(.+)$"
    )

    for idx, raw in enumerate(scoped):
        candidate = re.sub(r"^[*+\-]\s+", "", clean(raw))
        match = code_label.match(candidate)
        if not match:
            continue
        label = _normalize_row_label(match.group("label"))
        if not _valid_label(label):
            continue
        code = clean(match.group("code"))
        current = previous = None
        seen_current = seen_previous = False

        # Period children are adjacent in the source.  A small bounded window
        # prevents a malformed row from borrowing values from a later row.
        for j in range(idx + 1, min(len(scoped), idx + 7)):
            child = re.sub(r"^[*+\-]\s+", "", clean(scoped[j]))
            if not child:
                continue
            m = current_re.match(child)
            if m:
                current = parse_number(m.group(1))
                seen_current = True
                if seen_current and seen_previous:
                    break
                continue
            m = previous_re.match(child)
            if m:
                previous = parse_number(m.group(1))
                seen_previous = True
                if seen_current and seen_previous:
                    break
                continue
            m = restated_re.match(child)
            if m:
                previous = parse_number(m.group(1))
                seen_previous = True
                if seen_current and seen_previous:
                    break
                continue
            explicit = _explicit_fp_period_value(child, current_year, previous_year)
            if explicit:
                role, value = explicit
                if role == "current":
                    current = value
                    seen_current = True
                else:
                    previous = value
                    seen_previous = True
                if seen_current and seen_previous:
                    break
                continue
            # A new textual row before an explicit period child means this
            # anchor has no recoverable pair; do not scan through it.
            if re.search(r"[A-Za-zÀ-ỹ]", child) and ":" not in child:
                break
        if current is None and previous is None:
            continue
        parent, path = hierarchy.get(idx, (None, None))
        rows.append(RecoveredRow(
            label=label,
            current=current,
            previous=previous,
            code=code,
            source_line=s + idx + 1,
            pattern=f"{statement}_RAW_INLINE_CODE_CHILDREN",
            parent_label=parent,
            hierarchy_path=path,
        ))
    return rows


def _cashflow_section_by_line(scoped: list[str], absolute_start_zero: int):
    section = "operating"
    out = {}
    for idx, raw in enumerate(scoped):
        f = fold(raw)
        if "luu chuyen tien" in f and "hoat dong dau tu" in f:
            section = "investing"
        elif "luu chuyen tien" in f and "hoat dong tai chinh" in f:
            section = "financing"
        elif "luu chuyen tien" in f and "hoat dong kinh doanh" in f:
            section = "operating"
        elif any(x in f for x in ("luu chuyen tien thuan trong", "tien va tuong duong tien dau", "tien va cac khoan tuong duong tien tai thoi diem dau", "anh huong cua thay doi ty gia", "chenh lech quy doi tien te", "tien va tuong duong tien cuoi", "tien va cac khoan tuong duong tien tai thoi diem cuoi")):
            section = "reconciliation"
        out[absolute_start_zero + idx + 1] = section
    return out




def extract_generic_statement_rows(text: str, start_line: int, end_line: int, current_year=None, previous_year=None,
                                   statement: str = "GENERIC") -> list[RecoveredRow]:
    if current_year is None or previous_year is None:
        period = resolve_report_years(
            text,
            source_name="input",
            current_year=current_year,
            previous_year=previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
    lines = text.splitlines()
    s = max(0, start_line - 1)
    e = min(len(lines), end_line)
    scoped = lines[s:e]
    rows: list[RecoveredRow] = []
    hierarchy = _hierarchy_context(scoped)

    # Pipe tables.  Identify period columns from header when possible; otherwise last two numeric cells.
    for idx, raw in enumerate(scoped):
        if raw.count("|") < 3:
            continue
        cells = [clean(x) for x in raw.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= {"-", ":", " "}:
            continue
        fcells = [fold(c) for c in cells]
        if any(x in {"chi tieu", "ma so", "thuyet minh", "so cuoi nam", "so dau nam"} for x in fcells):
            continue
        # Preserve period column POSITION, including dash/null cells.
        # Numeric-token-only extraction shifts form code/note into a period when a
        # period cell is '-' (e.g. `23 | | - | (3.620...)`).
        # For table-like rows, the final two columns are the two period slots.
        if len(cells) < 3:
            continue
        cur_raw, prev_raw = cells[-2], cells[-1]
        value_token = re.compile(r"^\(?-?[\d][\d., ]*\)?$|^[-–—]$")
        if not (value_token.fullmatch(cur_raw) and value_token.fullmatch(prev_raw)):
            # Fallback only for malformed/non-standard rows; do not consume code as value.
            vals = [(i, parse_number(c)) for i, c in enumerate(cells)]
            numeric = [(i, v) for i, v in vals if v is not None]
            if len(numeric) < 1:
                continue
            cur = numeric[-2][1] if len(numeric) >= 2 else numeric[-1][1]
            prev = numeric[-1][1] if len(numeric) >= 2 else None
        else:
            cur, prev = parse_number(cur_raw), parse_number(prev_raw)

        # Some pages keep the human label in a separate column and emit only
        # `Mã số | Thuyết minh | current | previous` rows.  Exclude a leading
        # form-code token from label detection so codes such as `411a` are not
        # mistaken for display labels.
        leading_code = cells[0] if cells and re.fullmatch(r"(?i)\d{1,4}[a-z]?(?:\.\d+)?", cells[0]) else None
        text_cells = [
            (i, c) for i, c in enumerate(cells[:-2])
            if (i != 0 or leading_code is None)
            and re.search(r"[A-Za-zÀ-ỹ]", c) and _valid_label(c)
        ]
        if not text_cells:
            if leading_code and (cur is not None or prev is not None):
                parent, path = hierarchy.get(idx, (None, None))
                note = cells[-3] if len(cells) >= 4 and clean(cells[-3]) else None
                rows.append(RecoveredRow(
                    label=f"Mã số {clean(leading_code)}",
                    current=cur,
                    previous=prev,
                    code=clean(leading_code),
                    note=note,
                    source_line=s + idx + 1,
                    pattern=f"{statement}_RAW_CODE_PIPE",
                    parent_label=parent,
                    hierarchy_path=path,
                ))
            continue
        li, label = max(text_cells, key=lambda t: len(t[1]))
        # Avoid treating notes/page strings as the label. Form code comes only
        # from non-period columns.
        code = next((c for c in cells[:-2] if re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]+)?|[IVXLC]+", c, re.I)), None)
        parent, path = hierarchy.get(idx, (None, None))
        rows.append(RecoveredRow(label=label, current=cur, previous=prev, code=code,
                                 source_line=s + idx + 1, pattern=f"{statement}_RAW_PIPE",
                                 parent_label=parent, hierarchy_path=path))

    # Inline rows with explicit period annotations.
    for idx, raw in enumerate(scoped):
        c = clean(raw)
        if not _valid_label(c) or ":" not in c:
            continue
        cur, prev = _inline_year_values(c, current_year, previous_year)
        if cur is None and prev is None:
            cur, prev = _extract_explicit_inline_year_pair(c, current_year, previous_year)
        if cur is None and prev is None:
            cur, prev = _inline_end_begin_values(c)
        if cur is None and prev is None:
            continue
        label = _inline_row_label(c)
        flabel = fold(label)
        parent, path = hierarchy.get(idx, (None, None))
        if (re.match(r"^(?:ngay\s+)?31(?:\s+thang\s+12\s+nam\s*|\s+12\s+|[./-]12[./-])20\d{2}", flabel)
                or re.match(r"^(?:nam\s*)?20\d{2}$", flabel)
                or flabel == "chi tiet"):
            continue
        # Some LLM tables encode the actual parent row as `Tổng cộng: current (2025), previous (2024)`.
        if flabel == "tong cong" and parent:
            label = parent
        base_label, suffix_code, suffix_note = _extract_suffix_meta(label)
        base_label, trailing_code = _extract_trailing_form_code(base_label)
        code, label = _split_code_label(base_label)
        label = _normalize_row_label(label)
        suffix_code = suffix_code or trailing_code
        rows.append(RecoveredRow(label=label, current=cur, previous=prev, code=suffix_code or code, note=suffix_note,
                                 source_line=s + idx + 1, pattern=f"{statement}_RAW_INLINE_YEARS",
                                 parent_label=parent, hierarchy_path=path))


    # Continuation pages sometimes flatten a single current-period balance into
    # `Label (253) (8(c)): 362... đồng` without a separate prior child.  Keep the
    # bounded source observation so it can be reconciled with the semantic node;
    # this collector is activated only for rows carrying a form/note reference,
    # which prevents ordinary prose amounts from entering the statement.
    if statement == "FP":
        single_value = re.compile(
            r":\s*(?P<value>\(?-?[\d][\d., ]*\)?|-)\s*"
            r"(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*$",
            re.I,
        )
        for idx, raw in enumerate(scoped):
            c = clean(raw)
            if not c or ":" not in c or _is_period_value_line(c):
                continue
            if _inline_year_values(c, current_year, previous_year) != (None, None):
                continue
            match = single_value.search(c)
            if not match:
                continue
            label = _inline_row_label(c)
            if not re.search(r"\(\s*\d{2,4}[A-Za-z]?\s*\)|\(\s*\d{1,2}\s*\([A-Za-z]\)\s*\)", label):
                continue
            value = parse_number(match.group("value"))
            if value is None:
                continue
            label = re.sub(r"\(\s*\d{2,4}[A-Za-z]?\s*\)", "", label)
            label = re.sub(r"\(\s*\d{1,2}\s*\([A-Za-z]\)\s*\)", "", label)
            base_label, suffix_code, suffix_note = _extract_suffix_meta(label)
            base_label, trailing_code = _extract_trailing_form_code(base_label)
            code, label = _split_code_label(base_label)
            label = _normalize_row_label(label)
            if not _valid_label(label):
                continue
            parent, path = hierarchy.get(idx, (None, None))
            rows.append(RecoveredRow(
                label=label,
                current=value,
                previous=None,
                code=suffix_code or trailing_code or code,
                note=suffix_note,
                source_line=s + idx + 1,
                pattern="FP_RAW_INLINE_CURRENT_ONLY",
                parent_label=parent,
                hierarchy_path=path,
            ))


    # Code-first keyed block:
    #   * Mã số: 135
    #     * Chỉ tiêu: Các khoản phải thu khác
    #     * Năm nay: 180
    #     * Năm trước: 160
    #
    # The semantic identity is the Chỉ tiêu child, NOT the surrounding parent.
    for idx, raw in enumerate(scoped):
        c = re.sub(r"^[*+\-]\s+", "", clean(raw))
        mcode = re.match(r"(?i)^Mã\s*số\s*:\s*(\d{2,4}(?:\.\d+)?)\s*$", c)
        if not mcode:
            continue

        code = clean(mcode.group(1))
        label = None
        note = None
        current = None
        previous = None
        raw_indent = len(raw) - len(raw.lstrip(" \t"))

        for j in range(idx + 1, min(len(scoped), idx + 10)):
            cr = scoped[j]
            cc = re.sub(r"^[*+\-]\s+", "", clean(cr))
            if not cc:
                continue

            child_indent = len(cr) - len(cr.lstrip(" \t"))
            if j > idx + 1 and child_indent < raw_indent:
                break

            ml = re.match(r"(?i)^(?:Chỉ\s*tiêu|Diễn\s*giải)\s*:\s*(.+)$", cc)
            if ml:
                label = _normalize_row_label(ml.group(1))
                continue

            mn = re.match(r"(?i)^(?:Thuyết\s*minh|Số\s*thuyết\s*minh)\s*:\s*(.+)$", cc)
            if mn:
                note = clean(mn.group(1))
                continue

            pv = _explicit_fp_period_value(cc, current_year, previous_year)
            if pv:
                role, value = pv
                if role == "current":
                    current = value
                else:
                    previous = value
                continue

            # A new semantic keyed block starts.
            if re.match(r"(?i)^Mã\s*số\s*:", cc):
                break

        if label and (current is not None or previous is not None):
            parent, path = hierarchy.get(idx, (None, None))
            rows.append(
                RecoveredRow(
                    label=label,
                    current=current,
                    previous=previous,
                    code=code,
                    note=note,
                    source_line=s + idx + 1,
                    pattern=f"{statement}_RAW_CODE_FIRST_KEYED",
                    parent_label=parent,
                    hierarchy_path=path,
                )
            )


    # Inline current value followed by an explicit previous-period child. Common on continuation pages.
    for idx, raw in enumerate(scoped):
        c = clean(raw)
        m = re.match(r"^(.+?):\s*(\(?-?\d[\d., ]*\)?|-)(?:\s*(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ))?\s*$", c, re.I)
        if not m:
            continue
        label_raw, current_raw = clean(m.group(1)), m.group(2)
        if not _valid_label(label_raw):
            continue
        previous = None
        for j in range(idx+1, min(len(scoped), idx+5)):
            cc = re.sub(r"^[*+\-]\s+", "", clean(scoped[j]))
            mp = re.match(
                rf"(?i)^(?:Năm\s*trước|{previous_year}|Năm\s*{previous_year})\s*:\s*(.+)$",
                cc,
            )
            if mp:
                previous = parse_number(mp.group(1)); break
            if re.search(r"[A-Za-zÀ-ỹ]", cc) and ":" in cc:
                break
        if previous is None:
            continue
        parent, path = hierarchy.get(idx, (None, None))
        if fold(label_raw) in {"nam nay", "nam truoc", str(current_year), str(previous_year)}:
            if parent:
                label_raw = parent
            else:
                continue
        label_raw = _normalize_row_label(label_raw)
        base_label, suffix_code, suffix_note = _extract_suffix_meta(label_raw)
        # Code is often a sibling immediately before `Năm nay` in structural Markdown.
        if not suffix_code:
            for k in range(max(0, idx-3), idx):
                mk = re.search(r"(?i)Mã\s*số\s*:?\s*(\d{2,4}(?:\.\d+)?)", clean(scoped[k]))
                if mk:
                    suffix_code = clean(mk.group(1))
        # also accept `(Mã số 33)` without colon
        mm = re.search(r"\(\s*Mã\s*số\s+(\d{2,4}(?:\.\d+)?)\s*\)\s*$", base_label, re.I)
        if mm:
            suffix_code = suffix_code or clean(mm.group(1)); base_label = clean(base_label[:mm.start()])
        base_label, trailing_code = _extract_trailing_form_code(base_label)
        code, label = _split_code_label(base_label); label = _normalize_row_label(label); code = suffix_code or trailing_code or code
        rows.append(RecoveredRow(label=label, current=parse_number(current_raw), previous=previous, code=code, note=suffix_note,
                                 source_line=s+idx+1, pattern=f"{statement}_RAW_CURRENT_PREVIOUS_CHILD",
                                 parent_label=parent, hierarchy_path=path))

    # Parent + metadata/value children.  This handles `Số cuối năm`, `Số đầu năm`, `Tại ngày ...`, and year children.
    for idx, raw in enumerate(scoped):
        c = clean(raw)
        if not _valid_label(c):
            continue
        # Do not choose a value/meta child as its own parent.
        if _is_period_value_line(c):
            continue
        if re.fullmatch(r"\(?-?[\d.,]+\)?|-", c):
            continue
        # Inline label:value rows are observations themselves, not structural parents.
        if re.search(r":\s*\(?-?\d[\d., ]*\)?(?:\s|$)", c):
            continue
        base_label, suffix_code, suffix_note = _extract_suffix_meta(c.rstrip(":"))
        base_label, trailing_code = _extract_trailing_form_code(base_label)
        code, label = _split_code_label(base_label)
        label = _normalize_row_label(label)
        suffix_code = suffix_code or trailing_code
        current = previous = None
        note = suffix_note
        child_code = suffix_code or code
        found = False
        parent_indent = len(raw) - len(raw.lstrip(" \t"))
        for j in range(idx + 1, min(len(scoped), idx + 12)):
            cr = scoped[j]
            cc = clean(cr)
            if not cc:
                continue
            meta_cc = re.sub(r"^[*+\-]\s+", "", cc)
            child_indent = len(cr) - len(cr.lstrip(" \t"))
            # Once a new sibling/parent label appears, stop.  Markdown bullets with equal or shallower indentation are siblings.
            if j > idx + 1 and re.search(r"[A-Za-zÀ-ỹ]", cc) and not _is_period_value_line(cc):
                if child_indent <= parent_indent + 4:
                    break
            m = re.match(r"(?i)^Mã\s*số\s*:\s*(.+)$", meta_cc)
            if m:
                child_code = clean(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.+)$", meta_cc)
            if m:
                note = clean(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Số\s*thuyết\s*minh\s*:\s*(.+)$", meta_cc)
            if m:
                note = clean(m.group(1)); found = True; continue
            m = re.match(r"(?i)^(?:Số\s*)?Cuối\s*năm(?:\s*\([^)]*\))?\s*:\s*(.+)$", meta_cc)
            if m:
                current = parse_number(m.group(1)); found = True; continue
            m = re.match(r"(?i)^(?:Số\s*)?Đầu\s*năm(?:\s*\([^)]*\))?\s*:\s*(.+)$", meta_cc)
            if m:
                previous = parse_number(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Số\s*liệu\s*\(\s*(?:Trình\s*bày\s*lại|Đầu\s*năm|Năm\s*20\d{2})\s*\)\s*:\s*(.+)$", meta_cc)
            if m:
                previous = parse_number(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Số\s*liệu\s*:\s*(.+)$", meta_cc)
            if m:
                current = parse_number(m.group(1)); found = True; continue
            explicit_period = _explicit_fp_period_value(meta_cc, current_year, previous_year)
            if explicit_period:
                role, value = explicit_period
                if role == "current":
                    current = value
                else:
                    previous = value
                found = True
                continue

            icur, iprev = _inline_end_begin_values(meta_cc)
            if (icur is not None or iprev is not None) and child_indent <= parent_indent + 6:
                if icur is not None: current = icur
                if iprev is not None: previous = iprev
                found = True
                continue
            matched = False
            for yp in _YEAR_VALUE_PATTERNS:
                my = yp.match(meta_cc)
                if my:
                    if child_indent > parent_indent + 6:
                        matched = True
                        break
                    y = int(my.group(1)); val = parse_number(my.group(2))
                    if y == current_year: current = val
                    elif y == previous_year: previous = val
                    found = matched = True
                    break
            if matched:
                continue
        if found and (current is not None or previous is not None):
            parent, path = hierarchy.get(idx, (None, None))
            rows.append(RecoveredRow(label=label, current=current, previous=previous, code=child_code, note=note,
                                     source_line=s + idx + 1, pattern=f"{statement}_RAW_CHILDREN",
                                     parent_label=parent, hierarchy_path=path))

    # Inline code labels have a stable identity even when Markdown indentation
    # causes the generic parent walker to stop at the next sibling label.
    rows.extend(_inline_form_code_child_rows(
        scoped, s, current_year, previous_year, statement, hierarchy
    ))

    # Period-section child lists. Example:
    # `31/12/2025 ...: total` followed by nested `Sub-label: value`, then a 2024 block.
    period_children: dict[tuple, RecoveredRow] = {}
    active_year = None
    active_indent = None
    for idx, raw in enumerate(scoped):
        cc = clean(raw)
        indent = len(raw) - len(raw.lstrip(" \t"))
        found_year = _period_header_year(cc)
        if found_year is None:
            section_cc = re.sub(r"^[*+\-]\s+", "", cc)
            for yp in _YEAR_VALUE_PATTERNS:
                my = yp.match(section_cc)
                if my:
                    found_year = int(my.group(1)); break
        if found_year in {current_year, previous_year}:
            active_year, active_indent = found_year, indent
            continue
        if active_year is None or active_indent is None:
            continue
        # leave the period section when a structural sibling at the same/shallower indent appears
        if indent <= active_indent and re.search(r"[A-Za-zÀ-ỹ]", cc):
            active_year = active_indent = None
            continue
        if indent <= active_indent:
            continue
        section_cc = re.sub(r"^[*+\-]\s+", "", cc)
        m = re.match(r"^(.+?):\s*(\(?-?\d[\d., ]*\)?|-)(?:\s|$)", section_cc)
        if not m:
            continue
        label = clean(m.group(1))
        if not _valid_label(label) or fold(label) in {"thuyet minh", "ma so", "trang"}:
            continue
        value = parse_number(m.group(2))
        code, label = _split_code_label(label)
        # Period sections are paired by semantic label and hierarchy.  A
        # statement code can be missing, duplicated, or belong to the Notes
        # layer, so it is never part of this identity.
        parent, path = hierarchy.get(idx, (None, None))
        key = (fold(label), fold(parent or ""), fold(path or ""))
        rr = period_children.get(key)
        if rr is None:
            rr = RecoveredRow(label=label, current=None, previous=None, code=code, source_line=s+idx+1, pattern=f"{statement}_RAW_PERIOD_SECTION", parent_label=parent, hierarchy_path=path)
            period_children[key] = rr
        if active_year == current_year: rr.current = value
        else: rr.previous = value
    rows.extend(period_children.values())

    # Flat/column-major positional layout recovery (code/note/current/previous as separate sibling lines).
    rows.extend(_positional_numeric_children(scoped, s, current_year, previous_year, statement, hierarchy))

    if statement == "CASHFLOW":
        section_map = _cashflow_section_by_line(scoped, s)
        for r in rows:
            r.section = r.section or section_map.get(r.source_line)

    # Deduplicate and merge complementary periods by structural context.  Code
    # and note references remain provenance only.
    merged: dict[tuple, RecoveredRow] = {}
    order = []
    for r in rows:
        key = (
            statement,
            fold(r.section or ""),
            fold(r.label),
            fold(r.parent_label or ""),
            fold(r.hierarchy_path or ""),
        )
        if key not in merged:
            merged[key] = r; order.append(key); continue
        old = merged[key]
        if old.current is None and r.current is not None:
            old.current = r.current
        if old.previous is None and r.previous is not None:
            old.previous = r.previous
        if not old.note and r.note:
            old.note = r.note
        if r.pattern and r.pattern not in (old.pattern or ""):
            old.pattern = (old.pattern or "") + "+" + r.pattern
    return [merged[k] for k in order if merged[k].current is not None or merged[k].previous is not None]



def _split_page_blocks(text: str):
    """Return [(page_no, content_lines, global_start_line)]. YAML page boundaries are retained only as boundaries."""
    lines = text.splitlines()
    blocks = []
    cur_page = None
    cur = []
    cur_start = 1
    in_yaml = False
    yaml_page = None
    for idx, raw in enumerate(lines, start=1):
        if raw.strip() == "---":
            if in_yaml:
                in_yaml = False
                if yaml_page is not None:
                    if cur and cur_page is not None:
                        blocks.append((cur_page, cur, cur_start))
                    cur_page = yaml_page
                    cur = []
                    cur_start = idx + 1
                    yaml_page = None
                continue
            in_yaml = True
            continue
        if in_yaml:
            m = re.match(r"\s*page\s*:\s*(\d+)\s*$", raw, re.I)
            if m:
                yaml_page = int(m.group(1))
            continue
        if cur_page is not None:
            cur.append(raw)
    if cur and cur_page is not None:
        blocks.append((cur_page, cur, cur_start))
    return blocks


def _cross_page_fp_rows(text: str, current_year: int, previous_year: int, *, scope_start_line: int | None = None, scope_end_line: int | None = None):
    """Recover incomplete FP tail rows whose values start the adjacent page.

    Conservative by design: same adjacent page pair, code required, values must appear
    before a new semantic row. This is a generic structural recovery, never ticker/code specific.
    """
    blocks = _split_page_blocks(text)
    # Restrict stitching to the selected primary-statement scope. This prevents
    # similarly shaped fragments in notes/decoy tables from being recovered as B01 rows.
    if scope_start_line is not None or scope_end_line is not None:
        lo = int(scope_start_line or 1)
        hi = int(scope_end_line or 10**18)
        blocks = [b for b in blocks if b[2] <= hi and (b[2] + len(b[1]) + 16) >= lo]
    recovered = []
    note_re = re.compile(r"^(?:\d{1,3}(?:\.\d{1,2})?|[IVXLCDM]+\.\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))?)$", re.I)
    code_re = re.compile(r"^\d{2,4}(?:[a-z])?$", re.I)

    for bi in range(len(blocks)-1):
        page, left, left_start = blocks[bi]
        next_page, right, right_start = blocks[bi+1]
        if next_page != page + 1:
            continue

        # Tail meaningful lines only; metadata has already been removed.
        tail = [(i, clean(x)) for i,x in enumerate(left[-18:]) if clean(x)]
        if not tail:
            continue
        # Find last plausible form code near page tail.
        code_pos = None
        code = None
        for local_i, t in reversed(tail):
            tt = re.sub(r"^[*+\-]\s+", "", t)
            if code_re.fullmatch(tt) and tt not in {str(current_year), str(previous_year)}:
                code_pos = len(left)-18+local_i if len(left)>=18 else local_i
                code = tt
                break
        if code_pos is None:
            continue

        note = None
        after_code = []
        for j in range(code_pos+1, len(left)):
            t=clean(left[j])
            if t:
                after_code.append(t)
        if after_code and is_note_reference(after_code[0]):
            note = after_code[0]
            after_code = after_code[1:]
        # If values already exist on the left, it is not an incomplete tail row.
        if any(parse_number(x) is not None for x in after_code):
            continue

        # Reconstruct label from lines before code until heading/table/noise boundary.
        parts=[]
        for j in range(code_pos-1, max(-1, code_pos-7), -1):
            t=clean(left[j])
            if not t:
                if parts: break
                continue
            if t.startswith('|') or re.match(r"(?i)^(?:Mã\s*số|Thuyết\s*minh|TM)\s*:", t):
                break
            if re.match(r"^#{1,6}\s", left[j].strip()):
                break
            if parse_number(t) is not None or code_re.fullmatch(t):
                break
            if fold(t) in {"content", "tiep theo"}:
                break
            parts.append(_normalize_row_label(t))
        label=" ".join(reversed([p for p in parts if p])).strip()
        if len(label)<4:
            continue

        # Leading values on next page, allowing heading/content noise but no new semantic row.
        vals=[]
        value_lines=[]
        for j,raw in enumerate(right[:12]):
            t=clean(raw)
            if not t or t in {"Content"} or re.match(r"^#{1,6}\s", raw.strip()):
                continue
            v=parse_number(t)
            if v is not None and re.fullmatch(r"\(?-?[\d., ]+\)?", t):
                vals.append(v); value_lines.append(j)
                if len(vals)>=2: break
                continue
            # Dash is a real observed null; retain position if encountered.
            if t in {"-","–","—"}:
                vals.append(None); value_lines.append(j)
                if len(vals)>=2: break
                continue
            # Stop at a new semantic row/table.
            if '|' in raw or re.search(r"[A-Za-zÀ-ỹ]", t):
                break
        if len(vals)<2:
            continue

        recovered.append(RecoveredRow(
            label=label, current=vals[0], previous=vals[1], code=code, note=note,
            source_line=left_start+code_pos,
            pattern="FP_CROSS_PAGE_STITCH",
        ))
    return recovered

def extract_financial_position_source_rows(text: str, current_year=None, previous_year=None, fallback_unit: Optional[str] = None):
    if current_year is None or previous_year is None:
        period = resolve_report_years(
            text,
            source_name="input",
            current_year=current_year,
            previous_year=previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
    scope = choose_financial_position_scope(text)
    if not scope.get("scope_start_line"):
        return {**scope, "rows": []}
    rows = extract_generic_statement_rows(text, scope["scope_start_line"], scope["scope_end_line"], current_year, previous_year, "FP")
    rows += _cross_page_fp_rows(text, current_year, previous_year, scope_start_line=scope.get("scope_start_line"), scope_end_line=scope.get("scope_end_line"))

    # Merge after cross-page recovery using structural label/context identity.
    merged = {}
    order = []
    for r in rows:
        key = (
            fold(r.label),
            fold(r.parent_label or ""),
            fold(r.hierarchy_path or ""),
        )
        if key not in merged:
            merged[key] = r; order.append(key); continue
        old = merged[key]
        if old.current is None and r.current is not None: old.current = r.current
        if old.previous is None and r.previous is not None: old.previous = r.previous
        if not old.note and r.note: old.note = r.note
        if r.pattern and r.pattern not in (old.pattern or ""):
            old.pattern = ((old.pattern or "") + "+" + r.pattern).strip("+")
    rows = [merged[k] for k in order if merged[k].current is not None or merged[k].previous is not None]

    unit_ctx = detect_statement_unit("\n".join(text.splitlines()[scope["scope_start_line"]-1:scope["scope_end_line"]]), fallback_unit=fallback_unit)
    for r in rows:
        u = row_unit_override(r.label, unit_ctx)
        r.unit = u.unit
        r.unit_source = u.source
    return {**scope, "rows": rows, "unit": unit_ctx.unit, "unit_source": unit_ctx.source}


def _is_securities_customer_cashflow_heading(line: str) -> bool:
    f = fold(line)
    return (
        "luu chuyen tien te hoat dong moi gioi" in f
        and "khach hang" in f
        and "bao cao luu chuyen" not in f
    )


def _is_next_securities_statement(line: str) -> bool:
    f = fold(line)
    return any(token in f for token in (
        "bao cao tinh hinh bien dong von chu so huu",
        "bao cao ket qua hoat dong",
        "thuyet minh bao cao tai chinh",
        "b04 ctck",
        "b04 tctd",
    ))


def extract_securities_supplemental_cashflow_rows(
    text: str, current_year=None, previous_year=None
):
    """Recover the customer-broker cash-flow schedule on securities reports.

    B03-CTCK/B03b-CTCK reports may append a separate customer/agency cash-flow
    schedule after the statutory operating, investing and financing sections.
    The normal cash-flow scope intentionally stops before that schedule so it
    does not drift into B04 or the notes.  This bounded pass keeps the schedule
    as source observations without forcing it into the enterprise/bank schema.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _is_securities_customer_cashflow_heading(line)]
    if not starts:
        return {"scope_start_line": None, "scope_end_line": None, "rows": []}
    start = min(starts)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _is_next_securities_statement(lines[j]):
            end = j
            break
    rows = extract_generic_statement_rows(
        text, start + 1, end, current_year, previous_year, "CASHFLOW_SUPPLEMENTAL"
    )
    # The customer/agency schedule is a separate identity domain from the
    # statutory cash-flow sections.  Give every row a bounded section marker so
    # form codes such as `02` cannot collide with statutory B03 rows.
    for row in rows:
        row.section = row.section or "customer_broker_flow"
    # Continuation pages often flatten both period children onto one line:
    # `...: Năm nay: 1; Năm trước: 2`.  Keep this as a separate bounded
    # collector because the statutory cash-flow parser has already stopped at
    # the supplemental heading by design.
    current_token = r"\(?-?[\d., ]+\)?|-"
    current_re = re.compile(rf"(?i)Năm\s*nay\s*:\s*({current_token})")
    previous_re = re.compile(rf"(?i)Năm\s*trước(?:\s*\([^)]*\))?\s*:\s*({current_token})")
    supplemental_section = "customer_broker_flow"
    for idx in range(start + 1, end):
        raw = lines[idx]
        folded = fold(raw)
        if "tien va cac khoan tuong duong tien dau nam" in folded:
            supplemental_section = "customer_broker_opening"
        elif "tien va cac khoan tuong duong tien cuoi nam" in folded:
            supplemental_section = "customer_broker_closing"
        current_match = current_re.search(raw)
        previous_match = previous_re.search(raw)
        if not current_match or not previous_match:
            continue
        label = re.sub(r"^[*+\-]\s+", "", clean(raw[:current_match.start()]))
        label = _normalize_row_label(label.rstrip(" :;"))
        if not _valid_label(label):
            continue
        rows.append(RecoveredRow(
            label=label,
            current=parse_number(current_match.group(1)),
            previous=parse_number(previous_match.group(1)),
            section=supplemental_section,
            source_line=idx + 1,
            pattern="CASHFLOW_SUPPLEMENTAL_RAW_INLINE_CURRENT_PREVIOUS",
        ))
    return {
        "scope_start_line": start + 1,
        "scope_end_line": end,
        "rows": rows,
    }


try:
    from .source_canonical_hydrator import (
        _source_id,
        augment_canonical_with_recovered_rows,
        extract_code_period_table,
        hydrate_canonical_by_form_code,
    )
except ImportError:
    from source_canonical_hydrator import (
        _source_id,
        augment_canonical_with_recovered_rows,
        extract_code_period_table,
        hydrate_canonical_by_form_code,
    )


