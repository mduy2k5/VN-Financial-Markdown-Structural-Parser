from __future__ import annotations

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


def _structural_context_key(value: Any) -> str:
    """Chuẩn hóa context hierarchy mà không giữ payload riêng theo kỳ."""

    if value is None:
        return ""
    parts = re.split(r"\s*>\s*", clean(value))
    normalized = []
    for part in parts:
        # Parent của section kỳ thường mang chính giá trị của nó, ví dụ
        # `A. TÀI SẢN NGẮN HẠN: 32.904.606.406.685 đồng`. Giá trị thay đổi giữa
        # block hiện tại và so sánh, không thuộc identity cấu trúc dùng để ghép.
        part = re.sub(
            r"\s*:\s*\(?-?[\d][\d., ]*\)?\s*(?:triệu|trieu|nghìn|nghin)?\s*"
            r"(?:đồng|dong|vnd|vnđ)?\s*$",
            "",
            part,
            flags=re.I,
        )
        normalized.append(fold(part))
    return " > ".join(x for x in normalized if x)


def parse_number(v: Any):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = clean(v).replace("−", "-")
    if not s:
        return None
    # Quy tắc trung thành nguồn: dấu gạch là marker chưa báo/không phát sinh,
    # không phải số 0 được báo. Kiểm tra công thức có thể xem None là 0 ở view riêng.
    if s in {"-", "–", "—"}:
        return None
    neg = s.startswith("(") and ")" in s
    s = s.strip().strip("()")
    # Chỉ giữ token số đầu; đơn vị/annotation năm có thể theo sau.
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
            # Dấu phân cách trộn: dấu cuối là thập phân nếu phần đuôi ngắn,
            # nếu không thì là phân cách hàng nghìn.
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

    # Fallback khi heading trang đầu mất do OCR/LLM nhưng phần thân có anchor B02/FP rõ.
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
            # Lùi về đầu block trang/content thay vì chỉ lấy dòng anchor.
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
    # Luôn kéo đến báo cáo khác đầu tiên phía sau. Cách này nối được các trang tiếp nối.
    for j in range(s + 1, min(len(lines), s + 1800)):
        if _is_next_statement_line(lines[j]):
            e = j; break
    return {"scope_start_line": s + 1, "scope_end_line": e, "scope_score": score}


_YEAR_VALUE_PATTERNS = [
    re.compile(r"(?i)^Năm\s+kết\s+thúc\s+31[./-]12[./-](20\d{2})(?:\s*\([^)]*\))*\s*:\s*(.+)$"),
    # `31/12/2025 Triệu VND: 123`, có thể kèm chú thích đã kiểm toán.
    re.compile(r"(?i)^(?:Tại\s+ngày\s+)?31[./-]12[./-](20\d{2})(?:\s+(?:triệu|nghìn)\s*(?:đồng|vnd|vnđ))?(?:\s*\([^)]*\))?\s*:\s*(.+)$"),
    # `Ngày 31 tháng 12 năm 2025 (triệu đồng)`.
    re.compile(r"(?i)^Ngày\s+31\s+tháng\s+12\s+năm\s+(20\d{2})(?:\s*\([^)]*\))?\s*:\s*(.+)$"),
    re.compile(r"(?i)^(?:Năm\s*)?(20\d{2})(?:\s+(?:triệu|nghìn)\s*(?:đồng|vnd|vnđ))?(?:\s*\([^)]*\))?\s*:\s*(.+)$"),
]


def _explicit_fp_period_value(text: str, current_year: int, previous_year: int):
    """Trả về (role, value) cho dòng con kỳ FP rõ.

    Identity kế toán quan trọng:
      01/01/current_year == số đầu kỳ == kỳ so sánh trước đây.
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

    # Một số bố cục Markdown/OCR bỏ tiền tố `Số`:
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
    # `578.891 triệu đồng (Cuối năm) | 1.209.509 triệu đồng (Đầu năm)`.
    mc = re.search(r"(\(?-?\d[\d., ]*\)?|-)\s*(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*\(\s*Cuối\s+năm\s*\)", s, re.I)
    mp = re.search(r"(\(?-?\d[\d., ]*\)?|-)\s*(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*\(\s*Đầu\s+năm\s*\)", s, re.I)
    if mc: cur = parse_number(mc.group(1))
    if mp: prev = parse_number(mp.group(1))
    return cur, prev


def _inline_year_values(line: str, current_year: int, previous_year: int):
    s = clean(line)
    vals = {}
    # Giá trị rồi marker năm/ngày rõ: `123 triệu đồng (năm 31.12.2025)` / `123 (31.12.2025)`.
    p = re.compile(
        r"(?P<val>\(?-?\d[\d., ]*\)?|-)\s*(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng)?\s*"
        r"\(\s*(?:năm\s*)?(?:31[./-]12[./-])?(?P<year>20\d{2})\s*\)", re.I)
    for m in p.finditer(s):
        vals[int(m.group("year"))] = parse_number(m.group("val"))
    # OCR báo cáo tình hình tài chính thường viết `(31/12/2025)` và `(1/1/2025)`
    # thay vì chỉ ghi năm. Ngày mở đầu năm hiện tại là số dư so sánh trước đây.
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
    # Annotation `(Năm 2024: 123 triệu đồng)` sau giá trị hiện tại không có nhãn.
    p2 = re.compile(r"(?i)\(\s*Năm\s*(20\d{2})\s*:\s*(\(?-?\d[\d., ]*\)?|-)\s*(?:triệu\s*(?:đồng|VND|VNĐ)|VND|VNĐ|đồng)?\s*\)")
    for m in p2.finditer(s):
        vals[int(m.group(1))] = parse_number(m.group(2))
    # Nếu kỳ trước rõ trong ngoặc, hiện tại thường là giá trị ngay sau dấu hai chấm của nhãn.
    if previous_year in vals and current_year not in vals:
        head = s[:p2.search(s).start()] if p2.search(s) else s
        mc = re.search(r":\s*(\(?-?\d[\d., ]*\)?|-)\s*(?:triệu\s*(?:đồng|VND|VNĐ)|VND|VNĐ|đồng)?\s*$", head, re.I)
        if mc:
            vals[current_year] = parse_number(mc.group(1))
    return vals.get(current_year), vals.get(previous_year)


def _inline_row_label(line: str) -> str:
    """Trả về nhãn semantic trước giá trị, gồm cả mã số nằm trong nhãn."""

    code_suffix = re.search(r"\(\s*Mã\s*số\s*:.*?\)\s*:\s*", line, re.I)
    if code_suffix:
        return clean(line[:code_suffix.start()])
    return clean(line.split(":", 1)[0])


def _normalize_row_label(label: str):
    s = clean(label)
    s = re.sub(r"(?i)^Chỉ\s*tiêu\s*:\s*", "", s)
    return clean(s)


def _split_code_label(label: str):
    """Tách tiền tố mã biểu mẫu thật khỏi số thứ tự hiển thị.

    Tiền tố một chữ số/La Mã trong báo cáo tiếng Việt thường là marker hierarchy
    (1., II., III.) chứ không phải mã biểu mẫu. Bỏ chúng khỏi nhãn nhưng không
    đưa vào ``form_code``. Tiền tố số từ hai chữ số trở lên (01, 100, 311...) được giữ.
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
    """Tách `(Mã số: ..., Thuyết minh: ...)` mà vẫn giữ nhãn người đọc."""
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
    """Trả về thụt lề cấu trúc gần đúng và nhãn bullet/heading đã làm sạch."""
    expanded = raw.expandtabs(4)
    leading = len(expanded) - len(expanded.lstrip(" "))
    c = clean(raw)
    c = re.sub(r"^[*+\-]\s+", "", c)
    c = re.sub(r"^\d+[.)]\s+", lambda m: m.group(0), c)
    return leading, clean(c)


def _hierarchy_context(scoped: list[str]):
    """Suy ra parent text gần nhất từ thụt lề Markdown mà không đổi nhãn nguồn."""
    stack: list[tuple[int, str]] = []
    out: dict[int, tuple[Optional[str], Optional[str]]] = {}
    for idx, raw in enumerate(scoped):
        indent, label = _markdown_indent_and_label(raw)
        if not label or _is_period_value_line(label) or re.fullmatch(r"\(?-?[\d.,]+\)?|-", label):
            continue
        if not _valid_label(label):
            continue
        # metadata/heading không phải parent của dòng.
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
    """Đọc dạng `123 (2025), 456 (2024)` và các dạng tương tự."""
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
    # Mã dòng theo mẫu thường ngắn và không có dạng số hàng nghìn.
    return "." not in t or len(t.split('.')[0]) <= 4


def _looks_like_note_token(token: str) -> bool:
    t = clean(token)
    return bool(re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?(?:\s*,\s*\d{1,2}(?:\.\d{1,2})?)*", t))


def _positional_numeric_children(scoped: list[str], s: int, current_year: int, previous_year: int, statement: str, hierarchy):
    """Khôi phục dòng theo cột khi nhãn/mã/thuyết minh/hiện tại/trước đây phát ra như sibling.

    Dạng này thường gặp trong Markdown OCR/LLM khi dòng bảng thành:
      nhãn -> mã -> thuyết minh? -> hiện tại -> trước đây
    và giá trị kỳ không có tiền tố `Số cuối năm`/năm.
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
        # Loại nhãn có dạng số, metadata và heading chỉ chứa tên section.
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
            # Có dòng text mới => không còn child.
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
            # Không xem số lớn có phân cách hàng nghìn rõ là mã.
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


def _period_header_role(text: str, current_year: int, previous_year: int):
    c = re.sub(r"^[*+\-]\s+", "", clean(text))
    # Báo cáo tình hình tài chính có thể serialize block kỳ thành heading ngày
    # độc lập thay vì cột bảng. `01/01/current_year` là số dư đầu kỳ so sánh,
    # nên phải giải quyết thành `previous`, không phải năm lịch trong ngày.
    date_patterns = [
        r"(?i)^(?:(?:tại|tai|ngày|ngay|số\s+liệu\s+ngày|so\s+lieu\s+ngay)\s+)?"
        r"(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>20\d{2})"
        r"(?:\s+(?:triệu|trieu|nghìn|nghin)\s*(?:đồng|dong|vnd|vnđ))?"
        r"(?:\s*\([^)]*\))*\s*:?\s*$",
        r"(?i)^(?:(?:tại|tai|ngày|ngay|số\s+liệu\s+ngày|so\s+lieu\s+ngay)\s+)?"
        r"(?P<day>\d{1,2})\s+tháng\s+(?P<month>\d{1,2})\s+năm\s+(?P<year>20\d{2})"
        r"(?:\s+(?:triệu|trieu|nghìn|nghin)\s*(?:đồng|dong|vnd|vnđ))?"
        r"(?:\s*\([^)]*\))*\s*:?\s*$",
    ]
    for p in date_patterns:
        m = re.match(p, c)
        if m:
            return period_role_for_date(
                int(m.group("day")),
                int(m.group("month")),
                int(m.group("year")),
                current_year,
                previous_year,
            )

    pats = [
        r"(?i)^Năm\s+kết\s+thúc\s+31[./-]12[./-](20\d{2})(?:\s*\([^)]*\))*\s*:?\s*$",
        r"(?i)^(?:Năm\s*)?(20\d{2})(?:\s*\([^)]*\))*\s*:?\s*$",
    ]
    for p in pats:
        m = re.match(p, c)
        if m:
            year = int(m.group(1))
            if year == current_year:
                return "current"
            if year == previous_year:
                return "previous"
    return None


def _is_period_column_year_header(
    scoped: list[str],
    index: int,
    current_year: int,
    previous_year: int,
) -> bool:
    """Nhận diện nhãn năm mô tả hai cột giá trị, không phải hai block dòng.

    Bố cục trang tiếp nối thường ghi ``Tại ngày ... năm`` rồi metadata và hai
    nhãn cột ``2025 (VND)`` / ``2024 (VND)``. Bộ thu section kỳ không được xem
    các nhãn đó là đầu block kỳ trước; các dòng ``nhãn: hiện tại | trước đây``
    sau đó đã mang cả hai observation trên cùng dòng.
    """

    candidate = clean(scoped[index])
    year_match = re.fullmatch(r"(20\d{2})(?:\s*\([^)]*\))?", candidate)
    if not year_match:
        return False
    year = int(year_match.group(1))
    if year not in {current_year, previous_year}:
        return False

    def previous_nonempty(position: int):
        for cursor in range(position - 1, max(-1, position - 7), -1):
            if clean(scoped[cursor]):
                return cursor
        return None

    def next_nonempty(position: int):
        for cursor in range(position + 1, min(len(scoped), position + 7)):
            if clean(scoped[cursor]):
                return cursor
        return None

    if year == current_year:
        other_index = next_nonempty(index)
        other = clean(scoped[other_index]) if other_index is not None else ""
        if not re.fullmatch(rf"{previous_year}(?:\s*\([^)]*\))?", other):
            return False
        first_year_index = index
    else:
        other_index = previous_nonempty(index)
        other = clean(scoped[other_index]) if other_index is not None else ""
        if not re.fullmatch(rf"{current_year}(?:\s*\([^)]*\))?", other):
            return False
        first_year_index = other_index

    anchor_index = previous_nonempty(first_year_index)
    while anchor_index is not None:
        anchor = fold(scoped[anchor_index])
        if re.search(r"\btai ngay\b.*\bnam\s*$", anchor):
            return True
        # Metadata có thể nằm giữa header ngày và cột năm, nhưng dòng dữ liệu mới
        # nghĩa là đây không còn là chuỗi header cột.
        if ":" in clean(scoped[anchor_index]) and not re.match(
            r"(?i)^(?:Mã\s*số|Thuyết\s*minh|Ma\s*so|Thuyet\s*minh)\s*:",
            clean(scoped[anchor_index]),
        ):
            return False
        anchor_index = previous_nonempty(anchor_index)
    return False


def _inline_form_code_child_rows(scoped: list[str], s: int, current_year: int,
                                 previous_year: int, statement: str, hierarchy):
    """Khôi phục dòng có mã biểu mẫu nằm trong nhãn.

    Một dạng Markdown/OCR thường gặp là::

        * 1. Phải trả người bán ngắn hạn (Mã số: 311)
            * Số cuối năm: 100
            * Số đầu năm (Trình bày lại): 90

    Bộ duyệt parent/child chung không thể dùng thụt lề an toàn ở đây vì nhãn
    sibling kế tiếp thường cùng mức với child giá trị đầu. Lượt này neo vào mã
    biểu mẫu inline và chỉ lấy các child kỳ rõ ngay bên dưới.
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

        # Child kỳ nằm liền nhau trong nguồn. Cửa sổ giới hạn nhỏ ngăn dòng hỏng
        # mượn giá trị của dòng sau.
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
            # Có dòng text mới trước child kỳ rõ nghĩa là anchor không có cặp
            # khôi phục được; không quét xuyên qua dòng đó.
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
    """Khôi phục evidence dạng dòng từ cửa sổ nguồn báo cáo có giới hạn.

    Khôi phục mang tính bổ sung. Nó hỗ trợ bố cục mà parser cấu trúc/dòng chính
    chưa materialize, nhưng không quyết định identity semantic hay ghi đè kỳ
    canonical khác null.
    """
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

    # Trang tiếp nối có thể serialize hai cột kỳ thành một dòng ngăn bằng bar,
    # ví dụ ``300 Nợ phải trả: 180 (đồng) | 90 (đồng)``.
    # Đây là observation cấu trúc hai kỳ, không phải bảng Markdown có từ ba
    # dấu phân cách, nên xử lý trước bộ thu pipe-table thường.
    amount_token = r"\(?-?\d[\d., ]*\)?|-"
    amount_tail = r"(?:\s*(?:\([^)]*\)|triệu\s*(?:đồng|vnd|vnđ)|nghìn\s*đồng|đồng|vnd|vnđ))*"
    inline_bar_left = re.compile(
        rf"^(?P<label>.+?):\s*(?P<current>{amount_token}){amount_tail}\s*$",
        re.I,
    )
    inline_bar_right = re.compile(
        rf"^\s*(?P<previous>{amount_token}){amount_tail}\s*$",
        re.I,
    )
    for idx, raw in enumerate(scoped):
        if raw.count("|") != 1:
            continue
        cells = [clean(cell) for cell in clean(raw).split("|")]
        if len(cells) != 2:
            continue
        left_match = inline_bar_left.match(cells[0])
        right_match = inline_bar_right.match(cells[1])
        if not left_match or not right_match:
            continue
        base_label, suffix_code, suffix_note = _extract_suffix_meta(left_match.group("label"))
        base_label, trailing_code = _extract_trailing_form_code(base_label)
        code, label = _split_code_label(base_label)
        label = _normalize_row_label(label)
        if not _valid_label(label):
            continue
        parent, path = hierarchy.get(idx, (None, None))
        rows.append(RecoveredRow(
            label=label,
            current=parse_number(left_match.group("current")),
            previous=parse_number(right_match.group("previous")),
            code=suffix_code or trailing_code or code,
            note=suffix_note,
            source_line=s + idx + 1,
            pattern=f"{statement}_RAW_INLINE_BAR_PAIR",
            parent_label=parent,
            hierarchy_path=path,
        ))

    # Bảng pipe. Xác định cột kỳ từ header khi có thể; nếu không thì dùng hai ô số cuối.
    for idx, raw in enumerate(scoped):
        if raw.count("|") < 3:
            continue
        cells = [clean(x) for x in raw.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= {"-", ":", " "}:
            continue
        fcells = [fold(c) for c in cells]
        if any(x in {"chi tieu", "ma so", "thuyet minh", "so cuoi nam", "so dau nam"} for x in fcells):
            continue
        # Giữ nguyên VỊ TRÍ cột kỳ, kể cả ô gạch/null.
        # Chỉ lấy token số sẽ đẩy mã biểu mẫu/chú thích vào vị trí kỳ khi
        # ô kỳ là '-' (ví dụ `23 | | - | (3.620...)`).
        # Với dòng có dạng bảng, hai cột cuối là hai vị trí kỳ.
        if len(cells) < 3:
            continue
        cur_raw, prev_raw = cells[-2], cells[-1]
        value_token = re.compile(r"^\(?-?[\d][\d., ]*\)?$|^[-–—]$")
        if not (value_token.fullmatch(cur_raw) and value_token.fullmatch(prev_raw)):
            # Chỉ dùng fallback cho dòng lỗi/không chuẩn; không lấy mã làm giá trị.
            vals = [(i, parse_number(c)) for i, c in enumerate(cells)]
            numeric = [(i, v) for i, v in vals if v is not None]
            if len(numeric) < 1:
                continue
            cur = numeric[-2][1] if len(numeric) >= 2 else numeric[-1][1]
            prev = numeric[-1][1] if len(numeric) >= 2 else None
        else:
            cur, prev = parse_number(cur_raw), parse_number(prev_raw)

        # Một số trang giữ nhãn người đọc ở cột riêng và chỉ phát ra dòng dạng
        # `Mã số | Thuyết minh | hiện tại | trước đây`. Loại token mã biểu mẫu
        # ở đầu khi tìm nhãn để các mã như `411a` không bị xem là nhãn.
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
        # Không xem chuỗi chú thích/số trang là nhãn. Mã biểu mẫu chỉ lấy từ
        # các cột không phải cột kỳ.
        code = next((c for c in cells[:-2] if re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]+)?|[IVXLC]+", c, re.I)), None)
        parent, path = hierarchy.get(idx, (None, None))
        rows.append(RecoveredRow(label=label, current=cur, previous=prev, code=code,
                                 source_line=s + idx + 1, pattern=f"{statement}_RAW_PIPE",
                                 parent_label=parent, hierarchy_path=path))

    # Dòng inline có chú thích kỳ rõ ràng.
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
        # Một số bảng do LLM tạo mã hóa dòng parent thật thành
        # `Tổng cộng: hiện tại (2025), trước đây (2024)`.
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


    # Trang tiếp nối đôi khi dồn một số dư kỳ hiện tại thành
    # `Nhãn (253) (8(c)): 362... đồng` mà không có child kỳ trước riêng. Giữ
    # observation nguồn có giới hạn để reconciler ghép với node semantic;
    # collector này chỉ chạy cho dòng có mã biểu mẫu/chú thích, nhờ đó ngăn
    # các số trong văn bản thường đi vào báo cáo.
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


    # Block có mã đứng trước làm khóa tạm thời:
    #   * Mã số: 135
    #     * Chỉ tiêu: Các khoản phải thu khác
    #     * Năm nay: 180
    #     * Năm trước: 160
    #
    # Identity semantic là child Chỉ tiêu, không phải parent bao quanh.
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

            # Bắt đầu một block semantic mới có mã.
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


    # Giá trị hiện tại inline theo sau bởi child kỳ trước rõ ràng. Dạng này
    # thường gặp trên các trang tiếp nối.
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
        # Mã thường là sibling ngay trước `Năm nay` trong Markdown cấu trúc.
        if not suffix_code:
            for k in range(max(0, idx-3), idx):
                mk = re.search(r"(?i)Mã\s*số\s*:?\s*(\d{2,4}(?:\.\d+)?)", clean(scoped[k]))
                if mk:
                    suffix_code = clean(mk.group(1))
        # Chấp nhận cả `(Mã số 33)` không có dấu hai chấm.
        mm = re.search(r"\(\s*Mã\s*số\s+(\d{2,4}(?:\.\d+)?)\s*\)\s*$", base_label, re.I)
        if mm:
            suffix_code = suffix_code or clean(mm.group(1)); base_label = clean(base_label[:mm.start()])
        base_label, trailing_code = _extract_trailing_form_code(base_label)
        code, label = _split_code_label(base_label); label = _normalize_row_label(label); code = suffix_code or trailing_code or code
        rows.append(RecoveredRow(label=label, current=parse_number(current_raw), previous=previous, code=code, note=suffix_note,
                                 source_line=s+idx+1, pattern=f"{statement}_RAW_CURRENT_PREVIOUS_CHILD",
                                 parent_label=parent, hierarchy_path=path))

    # Parent + child metadata/giá trị. Xử lý `Số cuối năm`, `Số đầu năm`,
    # `Tại ngày ...` và các child theo năm.
    for idx, raw in enumerate(scoped):
        c = clean(raw)
        if not _valid_label(c):
            continue
        # Không chọn child giá trị/meta làm parent của chính nó.
        if _is_period_value_line(c):
            continue
        if re.fullmatch(r"\(?-?[\d.,]+\)?|-", c):
            continue
        # Dòng inline nhãn:giá trị là observation, không phải parent cấu trúc.
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
            # Khi gặp nhãn sibling/parent mới thì dừng. Bullet Markdown có cùng
            # hoặc ít thụt lề hơn là sibling.
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

    # Nhãn có mã inline có identity ổn định ngay cả khi thụt lề Markdown làm
    # bộ duyệt parent chung dừng ở nhãn sibling kế tiếp.
    rows.extend(_inline_form_code_child_rows(
        scoped, s, current_year, previous_year, statement, hierarchy
    ))

    # Danh sách child theo section kỳ. Ví dụ:
    # `31/12/2025 ...: tổng` theo sau bởi `Nhãn con: giá trị` lồng nhau,
    # rồi đến block năm 2024.
    period_children: dict[tuple, RecoveredRow] = {}
    active_role = None
    active_indent = None
    for idx, raw in enumerate(scoped):
        cc = clean(raw)
        indent = len(raw) - len(raw.lstrip(" \t"))
        if _is_period_column_year_header(scoped, idx, current_year, previous_year):
            active_role = active_indent = None
            continue
        found_role = _period_header_role(cc, current_year, previous_year)
        if found_role:
            active_role, active_indent = found_role, indent
            continue
        if active_role is None or active_indent is None:
            continue
        section_cc = re.sub(r"^[*+\-]\s+", "", cc)
        row_match = re.match(r"^(.+?):\s*(\(?-?\d[\d., ]*\)?|-)(?:\s|$)", section_cc)
        is_period_container = bool(
            section_cc
            and section_cc.upper() == section_cc
            and len(section_cc) <= 180
        )
        # Rời section kỳ khi xuất hiện sibling cấu trúc có cùng hoặc ít thụt lề hơn.
        if (
            indent <= active_indent
            and re.search(r"[A-Za-zÀ-ỹ]", cc)
            and not row_match
            and not is_period_container
        ):
            active_role = active_indent = None
            continue
        if indent <= active_indent and not row_match:
            continue
        if not row_match:
            continue
        label = clean(row_match.group(1))
        if not _valid_label(label) or fold(label) in {"thuyet minh", "ma so", "trang"}:
            continue
        value = parse_number(row_match.group(2))
        code, label = _split_code_label(label)
        # Ghép các section kỳ theo nhãn semantic và hierarchy. Mã báo cáo có
        # thể thiếu, trùng hoặc thuộc lớp Notes, nên không bao giờ là một phần
        # của identity này.
        parent, path = hierarchy.get(idx, (None, None))
        key = (
            fold(label),
            _structural_context_key(parent),
            _structural_context_key(path),
        )
        rr = period_children.get(key)
        if rr is None:
            rr = RecoveredRow(label=label, current=None, previous=None, code=code, source_line=s+idx+1, pattern=f"{statement}_RAW_PERIOD_SECTION", parent_label=parent, hierarchy_path=path)
            period_children[key] = rr
        if active_role == "current":
            rr.current = value
        elif active_role == "previous":
            rr.previous = value
    rows.extend(period_children.values())

    # Khôi phục bố cục phẳng/column-major theo vị trí
    # (mã/chú thích/hiện tại/trước đây là các dòng sibling riêng).
    rows.extend(_positional_numeric_children(scoped, s, current_year, previous_year, statement, hierarchy))

    if statement == "CASHFLOW":
        section_map = _cashflow_section_by_line(scoped, s)
        for r in rows:
            r.section = r.section or section_map.get(r.source_line)

    # Khử trùng và ghép các kỳ bổ sung theo context cấu trúc. Mã và tham chiếu
    # chú thích chỉ giữ vai trò provenance.
    merged: dict[tuple, RecoveredRow] = {}
    order = []
    for r in rows:
        key = (
            statement,
            fold(r.section or ""),
            fold(r.label),
            _structural_context_key(r.parent_label),
            _structural_context_key(r.hierarchy_path),
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
    """Trả về ``[(page_no, content_lines, global_start_line)]``.

    Ranh giới trang trong YAML chỉ được giữ lại như ranh giới.
    """
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
    """Khôi phục dòng cuối B01 bị thiếu khi giá trị bắt đầu ở trang kế tiếp.

    Thiết kế bảo thủ: chỉ ghép hai trang kề nhau, bắt buộc có mã và giá trị phải
    xuất hiện trước dòng semantic mới. Đây là khôi phục cấu trúc chung, không
    phụ thuộc mã cổ phiếu hay mã báo cáo cụ thể.
    """
    blocks = _split_page_blocks(text)
    # Giới hạn ghép trong scope báo cáo chính đã chọn. Cách này ngăn các mảnh có
    # hình dạng tương tự trong notes/bảng mồi bị khôi phục thành dòng B01.
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

        # Chỉ xét các dòng có ý nghĩa ở cuối trang; metadata đã được loại bỏ.
        tail = [(i, clean(x)) for i,x in enumerate(left[-18:]) if clean(x)]
        if not tail:
            continue
        # Tìm mã biểu mẫu hợp lệ cuối cùng gần cuối trang.
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
        # Nếu bên trái đã có giá trị thì đây không phải dòng cuối bị thiếu.
        if any(parse_number(x) is not None for x in after_code):
            continue

        # Dựng lại nhãn từ các dòng trước mã cho đến ranh giới heading/bảng/nhiễu.
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

        # Tìm các giá trị đầu trang kế tiếp; cho phép nhiễu heading/content nhưng
        # không cho phép dòng semantic mới.
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
            # Dấu gạch là null thực sự trong nguồn; giữ nguyên vị trí nếu gặp.
            if t in {"-","–","—"}:
                vals.append(None); value_lines.append(j)
                if len(vals)>=2: break
                continue
            # Dừng khi gặp dòng/bảng semantic mới.
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
    """Khôi phục dòng B01, gồm cả bố cục tách rời và vắt qua trang.

    Hàm trả về evidence kèm dòng nguồn và context hierarchy để hydrator và
    reconciler đưa ra quyết định bảo thủ ở bước sau.
    """
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

    # Ghép sau khôi phục liên trang theo identity nhãn/context cấu trúc.
    merged = {}
    order = []
    for r in rows:
        key = (
            fold(r.label),
            _structural_context_key(r.parent_label),
            _structural_context_key(r.hierarchy_path),
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
    """Khôi phục bảng dòng tiền khách hàng/môi giới trong báo cáo chứng khoán.

    Báo cáo B03-CTCK/B03b-CTCK có thể thêm một bảng dòng tiền khách hàng/đại lý
    riêng sau các section kinh doanh, đầu tư và tài chính theo luật định. Scope
    dòng tiền thông thường cố ý dừng trước bảng này để không lấn sang B04 hoặc
    notes. Lượt có giới hạn này giữ bảng dưới dạng observation nguồn, không ép
    nó vào schema doanh nghiệp/ngân hàng.
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
    # Lịch dòng tiền khách hàng/đại lý là miền identity riêng với các section
    # dòng tiền theo luật định. Gắn marker section có giới hạn cho mọi dòng để
    # mã biểu mẫu như `02` không va chạm với dòng B03 theo luật định.
    for row in rows:
        row.section = row.section or "customer_broker_flow"
    # Trang tiếp nối thường dồn cả hai child kỳ trên một dòng:
    # `...: Năm nay: 1; Năm trước: 2`. Giữ đây là collector có giới hạn riêng
    # vì parser dòng tiền theo luật định đã dừng tại heading bổ sung theo thiết kế.
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

