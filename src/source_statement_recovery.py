from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional


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
    # Financial statements commonly use '-' for zero/blank.  In statement rows this is
    # materially closer to the reported value than dropping the period entirely.
    if s in {"-", "–", "—"}:
        return 0
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
    section: Optional[str] = None
    source_line: Optional[int] = None
    pattern: Optional[str] = None
    parent_label: Optional[str] = None
    hierarchy_path: Optional[str] = None


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
            score += min(260, len(re.findall(r"(?i)(?:Số\s+cuối\s+năm|Số\s+đầu\s+năm|31[./-]12[./-]20\d{2})\s*:", sample)) * 4)
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
        re.match(r"(?i)^(?:Mã\s*số|Thuyết\s*minh|Số\s*thuyết\s*minh|Số\s*cuối\s*năm(?:\s*\([^)]*\))?|Số\s*đầu\s*năm(?:\s*\([^)]*\))?|Số\s*liệu(?:\s*\([^)]*\))?|Tại\s+ngày|Năm\s+kết\s+thúc\s+31[./-]12[./-]20\d{2}(?:\s*\([^)]*\))*|Năm\s*20\d{2}|20\d{2})\s*:", c)
        or re.match(r"^(?:ngay\s+)?31(?:\s+thang\s+12\s+nam\s*|\s+12\s+|[./-]12[./-])20\d{2}", f)
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
        elif any(x in f for x in ("luu chuyen tien thuan trong", "tien va tuong duong tien dau", "tien va cac khoan tuong duong tien tai thoi diem dau", "anh huong cua thay doi ty gia", "tien va tuong duong tien cuoi", "tien va cac khoan tuong duong tien tai thoi diem cuoi")):
            section = "reconciliation"
        out[absolute_start_zero + idx + 1] = section
    return out


def extract_code_period_table(text: str, start_line: int, end_line: int, current_year=2025, previous_year=2024):
    """Extract code/current/previous evidence from label-less pipe tables.

    Used when OCR renders labels on one block/page and the statutory code/value columns on another.
    It never creates a semantic identity by itself; it can only hydrate an existing unique form-code node.
    """
    lines = text.splitlines()
    s, e = max(0, start_line-1), min(len(lines), end_line)
    out = []
    for idx, raw in enumerate(lines[s:e]):
        if raw.count("|") < 3:
            continue
        cells = [clean(x) for x in raw.strip().strip("|").split("|")]
        if not cells or any(fold(c) in {"ma so", "chi tieu"} for c in cells):
            continue
        code = next((c for c in cells[:2] if re.fullmatch(r"\d{2,4}(?:\.\d+)?", c)), None)
        if not code:
            continue
        nums = []
        for c in cells[1:]:
            v = parse_number(c)
            if v is not None:
                nums.append(v)
        if len(nums) < 2:
            continue
        out.append({"code": code, "current": nums[-2], "previous": nums[-1], "source_line": s+idx+1, "pattern": "CODE_PERIOD_PIPE"})
    return out


def hydrate_canonical_by_form_code(canonical: dict | None, evidence: list[dict], sector: str, method: str):
    if not canonical or not evidence:
        return canonical
    semantic = [n for n in canonical.get("nodes", []) if n.get("kind") != "source_observation"]
    by_code = {}
    for n in semantic:
        if clean(n.get("sector")) != clean(sector):
            continue
        nm = clean(n.get("method"))
        if nm not in {clean(method), "any"}:
            continue
        code = clean(n.get("form_code") or "")
        if code:
            by_code.setdefault(code, []).append(n)
    filled = conflicts = 0
    for ev in evidence:
        cand = by_code.get(clean(ev.get("code")), [])
        if len(cand) != 1:
            continue
        n = cand[0]; v = n.setdefault("value", {}); changed = False
        for period in ("current", "previous"):
            new = ev.get(period)
            if new is None:
                continue
            if v.get(period) is None:
                v[period] = new; changed = True
            elif v.get(period) != new:
                conflicts += 1
        if changed:
            filled += 1
            n.setdefault("extraction_meta", {}).setdefault("form_code_period_fills", []).append(ev)
    canonical.setdefault("diagnostics", {})["form_code_period_recovery"] = {
        "policy": "unique_profile_form_code_fill_missing_only_v16",
        "evidence_rows": len(evidence), "filled_nodes": filled, "conflicts": conflicts,
    }
    return canonical

def extract_generic_statement_rows(text: str, start_line: int, end_line: int, current_year=2025, previous_year=2024,
                                   statement: str = "GENERIC") -> list[RecoveredRow]:
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
        vals = [(i, parse_number(c)) for i, c in enumerate(cells)]
        numeric = [(i, v) for i, v in vals if v is not None]
        if len(numeric) < 1:
            continue
        text_cells = [(i, c) for i, c in enumerate(cells) if re.search(r"[A-Za-zÀ-ỹ]", c) and _valid_label(c)]
        if not text_cells:
            continue
        li, label = max(text_cells, key=lambda t: len(t[1]))
        # Avoid treating notes/page strings as the label.
        code = next((c for c in cells[:max(1, len(cells)-2)] if re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]+)?|[IVXLC]+", c, re.I)), None)
        cur = numeric[-2][1] if len(numeric) >= 2 else numeric[-1][1]
        prev = numeric[-1][1] if len(numeric) >= 2 else None
        # If code itself was parsed as numeric, remove it from value candidates.
        if code is not None:
            numeric2 = [(i, v) for i, v in numeric if clean(cells[i]) != clean(code)]
            if len(numeric2) >= 2:
                cur, prev = numeric2[-2][1], numeric2[-1][1]
            elif len(numeric2) == 1:
                cur, prev = numeric2[0][1], None
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
        label = c.split(":", 1)[0]
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
            mp = re.match(r"(?i)^(?:Năm\s*trước|2024|Năm\s*2024)\s*:\s*(.+)$", cc)
            if mp:
                previous = parse_number(mp.group(1)); break
            if re.search(r"[A-Za-zÀ-ỹ]", cc) and ":" in cc:
                break
        if previous is None:
            continue
        parent, path = hierarchy.get(idx, (None, None))
        if fold(label_raw) in {"nam nay", "nam truoc", "2025", "2024"}:
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
            m = re.match(r"(?i)^Số\s*cuối\s*năm(?:\s*\([^)]*\))?\s*:\s*(.+)$", meta_cc)
            if m:
                current = parse_number(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Số\s*đầu\s*năm(?:\s*\([^)]*\))?\s*:\s*(.+)$", meta_cc)
            if m:
                previous = parse_number(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Số\s*liệu\s*\(\s*(?:Trình\s*bày\s*lại|Đầu\s*năm|Năm\s*20\d{2})\s*\)\s*:\s*(.+)$", meta_cc)
            if m:
                previous = parse_number(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Số\s*liệu\s*:\s*(.+)$", meta_cc)
            if m:
                current = parse_number(m.group(1)); found = True; continue
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
        key = (fold(label), clean(code or ""))
        rr = period_children.get(key)
        if rr is None:
            parent, path = hierarchy.get(idx, (None, None))
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

    # Deduplicate and merge complementary periods.  Code is retained in the key when present to disambiguate repeated generic labels.
    merged: dict[tuple, RecoveredRow] = {}
    order = []
    for r in rows:
        key = (fold(r.label), clean(r.code or ""), fold(r.parent_label or ""), fold(r.hierarchy_path or ""))
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


def extract_financial_position_source_rows(text: str, current_year=2025, previous_year=2024):
    scope = choose_financial_position_scope(text)
    if not scope.get("scope_start_line"):
        return {**scope, "rows": []}
    rows = extract_generic_statement_rows(text, scope["scope_start_line"], scope["scope_end_line"], current_year, previous_year, "FP")
    return {**scope, "rows": rows}


def _source_id(statement: str, label: str, code: str, line: Optional[int], hierarchy_path: str = "") -> str:
    h = hashlib.sha1(f"{fold(label)}|{clean(code)}|{fold(hierarchy_path)}|{line or 0}".encode("utf-8")).hexdigest()[:14]
    return f"SOURCE.{statement}.{h}"


def augment_canonical_with_recovered_rows(canonical: dict | None, rows: list[RecoveredRow], statement: str) -> dict | None:
    if not canonical:
        return canonical
    nodes = canonical.setdefault("nodes", [])
    # Index exact label+code first; then unique exact label.  We only overwrite missing periods on semantic nodes.
    by_lc: dict[tuple, list[dict]] = {}
    by_l: dict[str, list[dict]] = {}
    for n in nodes:
        fl = fold(n.get("canonical_name"))
        if not fl:
            continue
        code = clean(n.get("form_code") or "")
        by_lc.setdefault((fl, code), []).append(n)
        by_l.setdefault(fl, []).append(n)

    added = filled = conflicts = 0
    seen_source = set()
    for r in rows:
        fl = fold(r.label)
        code = clean(r.code or "")
        if not fl:
            continue
        candidates = by_lc.get((fl, code), []) if code else []
        if not candidates and len(by_l.get(fl, [])) == 1:
            candidates = by_l[fl]
        # Fill missing periods where identity is unambiguous; never replace an existing non-null semantic value.
        if len(candidates) == 1:
            n = candidates[0]
            v = n.setdefault("value", {})
            changed = False
            if v.get("current") is None and r.current is not None:
                v["current"] = r.current; changed = True
            if v.get("previous") is None and r.previous is not None:
                v["previous"] = r.previous; changed = True
            if changed:
                filled += 1
                em = n.setdefault("extraction_meta", {})
                em.setdefault("source_recovery_occurrences", []).append({
                    "source_line": r.source_line, "source_label": r.label, "pattern": r.pattern,
                    "current": r.current, "previous": r.previous, "code": r.code, "note": r.note,
                    "parent_label": r.parent_label, "hierarchy_path": r.hierarchy_path,
                })
                continue
            # Exact identity with differing values is valuable debug evidence, but avoid creating duplicate exact labels
            # that could make downstream row selection unstable.
            if ((r.current is not None and v.get("current") is not None and r.current != v.get("current")) or
                (r.previous is not None and v.get("previous") is not None and r.previous != v.get("previous"))):
                conflicts += 1
                canonical.setdefault("diagnostics", {}).setdefault("source_recovery_conflicts", []).append({
                    "label": r.label, "code": r.code, "source_line": r.source_line,
                    "recovered_current": r.current, "recovered_previous": r.previous,
                    "existing_current": v.get("current"), "existing_previous": v.get("previous"),
                })
            continue

        key = (fl, code, fold(r.parent_label or ""), fold(r.hierarchy_path or ""), r.current, r.previous)
        if key in seen_source:
            continue
        seen_source.add(key)
        node = {
            "node_id": _source_id(statement, r.label, code, r.source_line, r.hierarchy_path or r.parent_label or ""),
            "canonical_name": clean(r.label),
            "kind": "source_observation",
            "semantic_role": "recovered_source_row",
            "sector": canonical.get("sector"),
            "method": canonical.get("method"),
            "section": r.section,
            "parent_label": r.parent_label,
            "hierarchy_path": r.hierarchy_path,
            "form_code": code or None,
            "value": {
                "current": r.current, "previous": r.previous, "note": r.note,
                "unit": None, "raw_text": clean(r.label),
            },
            "extraction_meta": {
                "source_recovery": True,
                "occurrences": [{
                    "source_line": r.source_line, "source_label": clean(r.label), "pattern": r.pattern,
                    "current": r.current, "previous": r.previous, "code": r.code, "note": r.note,
                    "parent_label": r.parent_label, "hierarchy_path": r.hierarchy_path,
                }],
            },
        }
        nodes.append(node)
        by_lc.setdefault((fl, code), []).append(node)
        by_l.setdefault(fl, []).append(node)
        added += 1

        # v16.1: ambiguous short labels often require hierarchy to recover their real row identity.
        # Preserve the literal source row and add a contextual evidence alias; never replace it.
        if statement == "FINANCIAL_POSITION" and r.parent_label:
            generic = {
                "nguyen gia", "hao mon luy ke", "gia tri hao mon luy ke", "khau hao luy ke",
                "du phong", "gia tri con lai", "tong cong", "cong", "khac"
            }
            if fl in generic:
                if fl in {"tong cong", "cong"}:
                    contextual_label = clean(r.parent_label)
                else:
                    contextual_label = clean(f"{r.label} {r.parent_label}")
                cfl = fold(contextual_label)
                if cfl and cfl != fl and not by_l.get(cfl):
                    ctx = {
                        "node_id": _source_id(statement, contextual_label, code, r.source_line, (r.hierarchy_path or "") + "|contextual"),
                        "canonical_name": contextual_label,
                        "kind": "source_observation",
                        "semantic_role": "contextual_source_identity",
                        "sector": canonical.get("sector"),
                        "method": canonical.get("method"),
                        "section": r.section,
                        "parent_label": r.parent_label,
                        "hierarchy_path": r.hierarchy_path,
                        "form_code": code or None,
                        "value": {"current": r.current, "previous": r.previous, "note": r.note, "unit": None, "raw_text": clean(r.label)},
                        "extraction_meta": {
                            "source_recovery": True, "contextual_identity": True,
                            "occurrences": [{"source_line": r.source_line, "source_label": clean(r.label), "contextual_label": contextual_label, "pattern": r.pattern}]
                        },
                    }
                    nodes.append(ctx)
                    by_l.setdefault(cfl, []).append(ctx)
                    by_lc.setdefault((cfl, code), []).append(ctx)
                    added += 1

    canonical.setdefault("diagnostics", {})["source_statement_recovery"] = {
        "statement": statement, "rows_recovered": len(rows), "added_nodes": added,
        "filled_existing_nodes": filled, "conflicts": conflicts,
        "policy": "source_scope_structural_identity_repair_v16_1",
    }
    return canonical
