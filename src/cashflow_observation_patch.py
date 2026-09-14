from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Optional


HEADING_RE = re.compile(r"(?i)B[ÁA]O\s+C[ÁA]O\s+L[ƯU]U\s+CHUY[ỂEÊ]N\s+TI[ỀEÊ]N\s+T[ỆE](?:\s+H[ỢO]P\s+NH[ẤA]T)?")
METHOD_DIRECT_RE = re.compile(r"(?i)ph[ươu]ơng\s+ph[áa]p\s+tr[ựu]c\s+ti[ếe]p")
METHOD_INDIRECT_RE = re.compile(r"(?i)ph[ươu]ơng\s+ph[áa]p\s+gi[áa]n\s+ti[ếe]p")
NOTES_RE = re.compile(
    r"(?i)^(?:(?:B[ẢA]N\s+)?THUY[ẾE]T\s+MINH\s+B[ÁA]O\s+C[ÁA]O\s+T[ÀA]I\s+CH[ÍI]NH|"
    r"B0?5\s*/\s*TCTD|B0?9\s*[-–]?\s*DN|B0?4\s*[-–]?\s*CTCK|"
    r"B[ÁA]O\s+C[ÁA]O\s+(?:T[ÌI]NH\s+H[ÌI]NH\s+)?(?:BI[ẾEÊ]N\s+[ĐD][ỘO]NG|THAY\s+[ĐD][ỔO]I)\s+V[ỐO]N|"
    r"(?:PH[ẦAÂ]N\s+)?L[ƯU]U\s+CHUY[ỂEÊ]N\s+TI[ỀEÊ]N(?:\s+T[ỆE])?\s+(?:HO[ẠA]T\s+[ĐD][ỘO]NG\s+M[ÔO]I\s+GI[ỚO]I|C[ỦU]A\s+KH[ÁA]CH\s+H[ÀA]NG)|"
    r"CAM\s+K[ẾE]T\s+NGO[ẠA]I\s+B[ẢA]NG|C[ÁA]C\s+CAM\s+K[ẾE]T\s+NGO[ẠA]I\s+B[ẢA]NG|"
    r"NGH[ĨI]A\s+V[ỤU]\s+N[ỢO]\s+TI[ỀE]M\s+[ẨA]N|CAM\s+K[ẾE]T\s+B[ẢA]O\s+L[ÃA]NH|B[ẢA]O\s+L[ÃA]NH\s+VAY\s+V[ỐO]N)"
    r"(?:\b|$)"
)

SECTION_PATTERNS = {
    "operating": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n(?:\s+t[ệe])?\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+kinh\s+doanh"),
    "investing": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n(?:\s+t[ệe])?\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+[đd][ầa]u\s+t[ưu]"),
    "financing": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n(?:\s+t[ệe])?\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+t[àa]i\s+ch[íi]nh"),
}


@dataclass
class CashFlowObservation:
    source_label: str
    current: Optional[float]
    previous: Optional[float]
    section: Optional[str] = None
    method: Optional[str] = None
    code: Optional[str] = None
    note: Optional[str] = None
    source_line: Optional[int] = None
    pattern: Optional[str] = None
    unit: Optional[str] = None

    def to_dict(self):
        return asdict(self)


def strip_md(s: Any) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"[*_`#]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" |:")


def fold(s: Any) -> str:
    s = strip_md(s)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def parse_number(v: Any):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = strip_md(v).strip()
    if not s:
        return None
    # Strip trailing unit words like "triệu đồng", "triệu VND", "nghìn đồng", "tỷ đồng", "đồng", "VND", etc.
    while True:
        ns = re.sub(r"(?i)\s*(?:tri[eệ]u|ngh[iì]n|t[yỷ]|vnd|vnđ|đ[oồ]ng)\b", "", s).strip()
        if ns == s:
            break
        s = ns
    s = s.strip()
    if s in {"-", "–", "—", "..."}:
        return 0
    m_paren = re.match(r"^\((\d[\d.,]*)\)$", s)
    if m_paren:
        neg = True
        s = m_paren.group(1)
    else:
        neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-") or s.startswith("−")
        s = s.strip("()−- ").replace(" ", "")
    s = s.replace("−", "-")
    try:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
            val = int(s.replace(".", ""))
        elif re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", s):
            val = int(s.replace(",", ""))
        elif re.fullmatch(r"-?\d+", s):
            val = int(s)
        elif re.fullmatch(r"-?\d+[.,]\d+", s):
            val = float(s.replace(",", "."))
        else:
            return None
        return -abs(val) if neg else val
    except Exception:
        return None


def _line_indent(raw: str) -> int:
    m = re.match(r"^(\s*)", raw)
    return len(m.group(1).replace("\t", "    ")) if m else 0


def _clean_bullet(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^(?:[-+*]|\d+[.)])\s+", "", s)
    return strip_md(s)


def _looks_metadata_line(text: str) -> bool:
    s = strip_md(text)
    if not s:
        return True
    # Pure numbers like "01", "02", "3.715.900"
    if parse_number(s) is not None:
        return True
    # Pure formulas without text like "(50 = 20 + 30 + 40)"
    if re.fullmatch(r"\(\s*\d+\s*=\s*[\d\s+–-]+\s*\)", s):
        return True
    f = fold(s)
    if not f:
        return True
    if f in {
        "chi tieu", "ma so", "thuyet minh", "nam nay", "nam truoc", "ky nay", "ky truoc",
        "content", "ma", "tong cong", "stt", "don vi", "vnd", "dong", "thuyet minh ma so",
        "ma thuyet so minh", "chi tieu ma so thuyet minh", "ma so thuyet minh", "dien giai",
        "m s", "m s d n", "so", "so thuyet minh", "ngay",
        "nhung thay doi ve tai san hoat dong", "nhung thay doi ve cong no hoat dong",
        "tong cong nhung thay doi ve tai san hoat dong", "tong cong nhung thay doi ve cong no hoat dong",
    }:
        return True
    # Period headings
    if re.match(r"^(?:nam|ky|quy)?\s*20\d{2}(?:\s|$)", f):
        return True
    if re.match(r"^(?:quy\s+[ivxlcdm\d]+|luy ke(?:\s+tu\s+dau\s+nam)?)(?:\s|$)", f):
        return True
    if re.match(r"^nam\s+(?:ket\s+thuc|tai\s+chinh|bao\s+cao)\b", f):
        return True
    if re.match(r"^nam\s+ket\s+thuc\s+\d{1,2}[\s/]+\d{1,2}[\s/]+20\d{2}\b", f):
        return True
    if re.fullmatch(r"\(?-?[\d.,]+\)?\s*\(\s*nam\s*20\d{2}\s*\)\s*;?", s, re.I):
        return True
    # City / location / sign-off lines
    if any(loc in f for loc in (
        "thanh pho ho chi minh", "thanh pho ha noi", "q binh thanh", "chu tich",
        "tong giam doc", "ke toan truong", "nguoi lap bieu", "ha noi ngay",
        "quan ly hoat dong", "pho giam doc", "nguoi lap", "nguoi kiem soat", "nguoi phe duyet"
    )):
        return True
    return (
        f.startswith("ma so") or f.startswith("thuyet minh") or
        f.startswith("nam nay") or f.startswith("nam truoc") or
        f.startswith("ky nay") or f.startswith("ky truoc") or
        f.startswith("mau so") or f.startswith("ban hanh theo")
    )


def _section_from_label(label: str, current_section: Optional[str]) -> Optional[str]:
    f = fold(label)
    if "luu chuyen tien thuan tu hoat dong kinh doanh" in f:
        return "operating"
    if "luu chuyen tien thuan tu hoat dong dau tu" in f:
        return "investing"
    if "luu chuyen tien thuan tu hoat dong tai chinh" in f:
        return "financing"
    if any(k in f for k in (
        "luu chuyen tien thuan trong", "tang giam tien thuan trong",
        "tien va cac khoan tuong duong tien tai thoi diem dau", "tien va cac khoan tuong duong tien dau nam",
        "tien va tuong duong tien dau", "dieu chinh anh huong cua thay doi ty gia", "dieu chinh cua anh huong thay doi ty gia",
        "anh huong cua thay doi ty gia", "tien va cac khoan tuong duong tien tai thoi diem cuoi",
        "tien va cac khoan tuong duong tien cuoi nam", "tien va tuong duong tien cuoi",
    )):
        return "reconciliation"
    return current_section


def _candidate_scope(lines: list[str], start: int, next_candidate: Optional[int]) -> tuple[int, int, int]:
    hard_end = min(len(lines), start + 900)
    end = hard_end
    for i in range(start + 1, hard_end):
        clean = strip_md(lines[i])
        # Repeated cash-flow heading on continuation page is not a stop.
        if NOTES_RE.search(clean):
            end = i
            break
    if next_candidate is not None and next_candidate < end:
        # Do not truncate if the next heading is only a continuation page within 350 lines.
        window = "\n".join(lines[next_candidate:min(len(lines), next_candidate + 8)])
        if "tiếp theo" not in fold(window) and "tiep theo" not in fold(window):
            # If current candidate has very little evidence before next candidate, let ranking choose next.
            pass
    scope = lines[start:end]
    txt = "\n".join(scope)
    score = 0
    if METHOD_DIRECT_RE.search(txt[:2500]) or METHOD_INDIRECT_RE.search(txt[:2500]):
        score += 100
    if re.search(r"(?i)B0?4\s*/\s*TCTD|B0?3\s*[-–]?\s*DN|B0?3\s*[-–]?\s*CTCK", txt[:3000]):
        score += 50
    section_hits = sum(1 for p in SECTION_PATTERNS.values() if p.search(txt))
    score += 45 * section_hits
    period_hits = len(re.findall(r"(?i)Năm\s+(?:nay|trước|20\d{2})|Kỳ\s+(?:này|trước)|\b20\d{2}\b", txt[:12000]))
    score += min(80, period_hits * 3)
    numeric_hits = len(re.findall(r"(?:\(|\b)-?\d{1,3}(?:[.,]\d{3}){1,}", txt[:15000]))
    score += min(100, numeric_hits * 2)
    span = end - start
    if span < 15:
        score -= 300
    if start < 300:
        score -= 250
    # Notes-like large blocks are dangerous.
    if span > 700:
        score -= min(400, span - 700)
    return start, end, score


def _is_valid_heading_candidate(line: str) -> bool:
    clean = strip_md(line)
    if not HEADING_RE.search(clean):
        return False
    if len(clean) > 120:
        return False
    f = fold(clean)
    if any(narr in f for narr in ("chung toi da kiem toan", "theo y kien", "trach nhiem cua", "kiem toan vien")):
        return False
    if re.search(r"trang\s*\d+", f):
        return False
    return True


def choose_cashflow_scope(text: str):
    lines = text.splitlines()
    candidates = [i for i, line in enumerate(lines) if _is_valid_heading_candidate(line)]
    if not candidates:
        candidates = [i for i, line in enumerate(lines) if HEADING_RE.search(strip_md(line))]
    if not candidates:
        return {"scope_start_line": None, "scope_end_line": None, "scope_score": 0, "candidate_count": 0}
    scored = []
    for j, start in enumerate(candidates):
        nxt = candidates[j + 1] if j + 1 < len(candidates) else None
        s, e, score = _candidate_scope(lines, start, nxt)
        scored.append((score, s, e))
    score, s, e = max(scored, key=lambda x: (x[0], -x[1]))
    return {
        "scope_start_line": s + 1,
        "scope_end_line": e,
        "scope_score": score,
        "candidate_count": len(candidates),
    }


def detect_method(scope_text: str) -> tuple[str, str]:
    head = scope_text[:5000]
    if METHOD_DIRECT_RE.search(head):
        return "direct", "heading"
    if METHOD_INDIRECT_RE.search(head):
        return "indirect", "heading"
    f = fold(head)
    direct = sum(k in f for k in (
        "tien thu tu ban hang cung cap dich vu", "thu nhap lai va cac khoan thu nhap tuong tu nhan duoc",
        "tien chi tra cho nguoi cung cap", "tien chi tra cho nhan vien",
    ))
    indirect = sum(k in f for k in (
        "loi nhuan truoc thue", "khau hao", "cac khoan du phong", "truoc thay doi von luu dong",
    ))
    if indirect >= 2 and indirect > direct:
        return "indirect", "semantic_anchors"
    if direct >= 2 and direct > indirect:
        return "direct", "semantic_anchors"
    return "unknown", "unknown"


def detect_sector(scope_text: str) -> tuple[str, str]:
    f = fold(scope_text[:10000])
    raw = scope_text[:10000]
    if re.search(r"(?i)B\s*0?4\s*/\s*TCTD", raw) or "to chuc tin dung" in f:
        return "bank", "form_or_text"
    if re.search(r"(?i)B\s*0?3\s*[-–]?\s*CTCK", raw) or "cong ty chung khoan" in f:
        return "securities", "form_or_text"
    if "bao hiem" in f and sum(k in f for k in ("phi bao hiem", "boi thuong", "du phong nghiep vu")) >= 1:
        return "insurance", "text_anchors"
    if re.search(r"(?i)B\s*0?3\s*[-–]?\s*DN", raw):
        return "enterprise", "form_code"
    bank_hits = sum(k in f for k in (
        "thu nhap lai va cac khoan thu nhap tuong tu nhan duoc",
        "tien gui va cho vay cac to chuc tin dung khac", "tien gui cua khach hang",
        "du phong rui ro tin dung",
    ))
    ent_hits = sum(k in f for k in (
        "tien thu tu ban hang cung cap dich vu", "tang giam hang ton kho",
        "tang giam cac khoan phai thu", "tien thu tu di vay",
    ))
    if bank_hits >= 2 and bank_hits > ent_hits:
        return "bank", "semantic_anchors"
    if ent_hits >= 2:
        return "enterprise", "semantic_anchors"
    return "unknown", "unknown"


def _extract_inline_periods(text: str, current_year: int, previous_year: int):
    """Extract current/previous values from common LLM inline layouts.

    v13 adds:
    - `current (Năm 2025) | previous (Năm 2024)`;
    - `current (31.12.2025); previous (31.12.2024)`;
    - `current ... (Năm 2024: previous ...)`, where current has no explicit year marker.
    """
    clean = strip_md(text)
    vals = {}

    # Value immediately before a year/date marker.
    marker_pat = re.compile(
        r"(?P<val>\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*"
        r"(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng)?\s*"
        r"\(\s*(?:Năm\s*)?(?:31[./-]12[./-])?(?P<year>20\d{2})\s*\)", re.I)
    for m in marker_pat.finditer(clean):
        vals[int(m.group("year"))] = parse_number(m.group("val"))

    # Previous/current value written inside the year annotation itself: `(Năm 2024: 123 triệu đồng)` or `(Thuyết minh: 30; Năm 2024: 123 triệu đồng)`.
    anno_pat = re.compile(
        r"(?:\(|;)\s*Năm\s*(?P<year>20\d{2})\s*:\s*"
        r"(?P<val>\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*"
        r"(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng)?\s*\)", re.I)
    anno_matches = list(anno_pat.finditer(clean))
    for m in anno_matches:
        vals[int(m.group("year"))] = parse_number(m.group("val"))

    # TCB-like layout: `Label: CURRENT triệu đồng (Năm 2024: PREVIOUS triệu đồng)`.
    # If the previous period is explicit but the current period is not, take the last numeric token
    # between the first label colon and the annotation as current.
    if previous_year in vals and current_year not in vals and anno_matches:
        prefix = clean[:anno_matches[0].start()]
        mc = re.search(
            r":\s*(\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*"
            r"(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng)?\s*(?:\([^)]*)?$", prefix, re.I)
        if mc:
            vals[current_year] = parse_number(mc.group(1))

    if vals:
        return vals.get(current_year), vals.get(previous_year)

    # Value before `(Năm nay)` / `(Năm trước)`.
    role_pat = re.compile(
        r"(?P<val>\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*"
        r"(?:triệu\s*đồng|triệu\s*VND|VND|VNĐ|đồng)?\s*\(\s*Năm\s*(?P<role>nay|trước)\s*\)", re.I)
    role_vals = {}
    for m in role_pat.finditer(clean):
        role_vals[fold(m.group("role"))] = parse_number(m.group("val"))
    if role_vals:
        return role_vals.get("nay"), role_vals.get("truoc")

    # `Năm nay: x | Năm trước: y`
    mn = re.search(r"(?i)Năm\s*nay\s*:\s*(\(?-?[\d.,]+\)?|-)", clean)
    mp = re.search(r"(?i)Năm\s*trước\s*:\s*(\(?-?[\d.,]+\)?|-)", clean)
    return (parse_number(mn.group(1)) if mn else None, parse_number(mp.group(1)) if mp else None)

def _emit(rows, label, current, previous, section, method, code, note, line_no, pattern):
    label = strip_md(label)
    if not label or _looks_metadata_line(label):
        return
    if current is None and previous is None:
        return
    rows.append(CashFlowObservation(
        source_label=label,
        current=current,
        previous=previous,
        section=_section_from_label(label, section),
        method=method,
        code=strip_md(code) if code not in (None, "") else None,
        note=strip_md(note) if note not in (None, "") else None,
        source_line=line_no,
        pattern=pattern,
    ))


def extract_cashflow_fallback(text: str, current_year=2025, previous_year=2024):
    scope = choose_cashflow_scope(text)
    if not scope.get("scope_start_line"):
        return {**scope, "rows": [], "method": "unknown", "method_method": "unknown", "sector": "unknown", "sector_method": "unknown"}
    lines = text.splitlines()
    s = scope["scope_start_line"] - 1
    e = scope["scope_end_line"]
    scoped_lines = lines[s:e]
    # Preprocess scoped_lines to merge wrapped text lines that belong together (e.g. OCR table cells wrapped across lines)
    processed_scoped_lines = []
    for raw in scoped_lines:
        s_raw = raw.strip()
        if (processed_scoped_lines
            and not s_raw.startswith(("#", "|", "*", "-", "+", ">"))
            and not re.match(r"^\d+[.)]", s_raw)
            and ":" not in s_raw
            and "|" not in s_raw
            and re.search(r"[A-Za-zÀ-ỹ]", s_raw)
            and parse_number(s_raw) is None
            and not _looks_metadata_line(s_raw)):
            prev = processed_scoped_lines[-1].strip()
            if (not prev.startswith(("#", "|", "*", "-", "+", ">"))
                and not re.match(r"^\d+[.)]", prev)
                and ":" not in prev
                and "|" not in prev
                and re.search(r"[A-Za-zÀ-ỹ]", prev)
                and parse_number(prev) is None
                and not _looks_metadata_line(prev)):
                processed_scoped_lines[-1] = processed_scoped_lines[-1] + " " + s_raw
                continue
        processed_scoped_lines.append(raw)
    scoped_lines = processed_scoped_lines

    scoped_text = "\n".join(scoped_lines)
    method, method_method = detect_method(scoped_text)
    sector, sector_method = detect_sector(scoped_text)

    rows = []
    section = None
    pending = None

    def emit(label, current=None, previous=None, sec=None, code=None, note=None, line_no=None, pattern=None):
        label = strip_md(label)
        label = re.sub(r"(?i)^(?:Chỉ\s*tiêu|Chi\s*tiết)\s*:\s*", "", label).strip()
        if not label or _looks_metadata_line(label):
            return
        fl = fold(label)
        if fl in {"page", "year", "so trang", "trang"} or fl.startswith(("createdat", "pageocrat", "updatedat", "s3 key", "file name", "search folder")):
            return
        if fl.startswith("nam tai chinh ket thuc ngay") or fl.startswith("ngay 31 thang 12 nam"):
            return
        _emit(rows, label, current, previous, _section_from_label(label, sec), method, code, note, line_no, pattern)

    def flush_pending():
        nonlocal pending
        if pending and (pending.get("current") is not None or pending.get("previous") is not None):
            emit(pending.get("label"), pending.get("current"), pending.get("previous"),
                 pending.get("section"), pending.get("code"), pending.get("note"),
                 pending.get("line"), pending.get("pattern", "CF_PERIOD_CHILDREN"))
        pending = None

    # PASS 1: normal parent/children, pipe, inline and code-led rows.
    for rel, raw in enumerate(scoped_lines, start=1):
        abs_line = s + rel
        clean = _clean_bullet(raw)
        if not clean:
            continue
        f = fold(clean)

        matched_section = None
        for sec, pat in SECTION_PATTERNS.items():
            if pat.search(clean):
                matched_section = sec
                break
        # Section header without a numeric payload.
        if matched_section and parse_number(re.sub(r".*?:", "", clean)) is None and not re.search(r"(?i)(?:20\d{2}|Năm\s+(?:nay|trước))\s*:", clean):
            # Totals are semantic rows; pure headers are section switches.
            if "thuan" not in f and "thuần" not in clean.casefold() and not re.match(r"^(?:[IVXLC]+|\d+)[.)]", clean):
                flush_pending(); section = matched_section; continue
            section = matched_section

        # Child metadata/value lines, including explicit years because LLM often omits Năm nay/Năm trước.
        m = re.match(r"(?i)^(?:Mã\s*số|Số|MS)\s*:\s*([^|]+)$", clean)
        if m:
            code_val = strip_md(m.group(1))
            if pending and (pending.get("current") is not None or pending.get("previous") is not None):
                flush_pending()
                pending = {"label": "", "code": code_val, "note": None, "current": None, "previous": None,
                           "section": section, "line": abs_line, "pattern": "CF_PERIOD_CHILDREN", "indent": _line_indent(raw)}
            elif pending:
                pending["code"] = code_val
            continue

        m = re.match(r"(?i)^Chi\s*tiết\s*:\s*(.+)$", clean)
        if m and pending:
            pending["label"] = strip_md(m.group(1))
            continue

        m = re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.+)$", clean)
        if m and pending:
            pending["note"] = strip_md(m.group(1)); continue

        m = re.match(r"(?i)^(?:Năm\s*nay|Kỳ\s*này)(?:\s*\([^)]*\))?\s*:\s*(.+)$", clean)
        if m and pending:
            pending["current"] = parse_number(m.group(1)); continue

        m = re.match(r"(?i)^(?:Năm\s*trước|Kỳ\s*trước)(?:\s*\([^)]*\))?\s*:\s*(.+)$", clean)
        if m and pending:
            pending["previous"] = parse_number(m.group(1)); continue

        m = re.search(r"(?i)\b(20\d{2})\b(?:\s*\([^)]*\))?\s*:\s*(\(?-?[\d.,]+\)?|-)", clean)
        if m and pending:
            yr, val = int(m.group(1)), parse_number(m.group(2))
            if yr == current_year: pending["current"] = val
            elif yr == previous_year: pending["previous"] = val
            continue

        # Pipe table row: label | code? | note? | current | previous.
        if raw.count("|") >= 2:
            cells = [strip_md(x) for x in raw.strip().strip("|").split("|")]
            if len(cells) >= 3 and not any(fold(x) in {"chi tieu", "nam nay", "nam truoc", "stt chi tieu"} for x in cells[:2]):
                nums = [(idx, parse_number(c)) for idx, c in enumerate(cells)]
                numeric = [(idx, val) for idx, val in nums if val is not None]
                if len(numeric) >= 2:
                    code = next((c for c in cells[:-2] if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+", c, re.I)), None)
                    text_cells = [c for c in cells[:-2] if re.search(r"[A-Za-zÀ-ỹ]", c) and not _looks_metadata_line(c)]
                    label = max(text_cells, key=len) if text_cells else cells[0]
                    mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
                    if mc and not code:
                        code, label = mc.group(1), mc.group(2)
                    flush_pending(); emit(label, numeric[-2][1], numeric[-1][1], section, code, None, abs_line, "CF_PIPE_TABLE"); continue

        # Inline year values on one line.
        cur, prev = _extract_inline_periods(clean, current_year, previous_year)
        if cur is not None or prev is not None:
            clean_without_numbers = re.sub(r"(?i)\b20\d{2}\b|\(?-?[\d.,]+\)?|\b(nam|ky|trieu|vnd|dong)\b|[;:.,()\-]", "", fold(clean)).strip()
            if pending and not clean_without_numbers:
                pending["current"] = cur
                pending["previous"] = prev
                continue
            flush_pending()
            label = re.split(r"(?i):\s*(?:\*\*)?(?:[–—-]|(?:\(?-?\d))|\s+(?:\(?-?\d{1,3}[.,]\d{3})", clean, maxsplit=1)[0]
            code = None
            mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
            if mc: code, label = mc.group(1), mc.group(2)
            emit(label, cur, prev, section, code, None, abs_line, "CF_INLINE_PERIODS"); continue

        # Code-led/plain-text row with one numeric value: `01 label: 123`.
        mc = re.match(r"^(?:\*\s*)?([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+?)\s*:\s*(\(?-?[\d.,]+\)?|-)(?:\s|$)", clean, re.I)
        if mc:
            flush_pending()
            code, label, val = mc.group(1), mc.group(2), parse_number(mc.group(3))
            emit(label, val, None, section, code, None, abs_line, "CF_PLAIN_TEXT_CODE"); continue

        # Heading/label with inline single value, e.g. `LƯU CHUYỂN ...: 57.639.048`.
        mh = re.match(r"^(.+?)\s*:\s*(\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)(?:\s*(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng))?(?:\s|$)", clean)
        if mh and re.search(r"[A-Za-zÀ-ỹ]", mh.group(1)):
            flush_pending(); emit(mh.group(1), parse_number(mh.group(2)), None, section, None, None, abs_line, "CF_HEADING_VALUE"); continue

        if _looks_metadata_line(clean):
            continue
        if any(k in f for k in ("bao cao tai chinh hop nhat", "cho nam tai chinh ket thuc", "don vi tinh", "nguoi lap", "ke toan truong", "tong giam doc", "metadata", "s3 key", "page ocr")):
            continue
        if re.match(r"(?i)^(?:Mã\s*số|Số|MS)\s*:\s*[^|]+$", clean):
            continue
        if re.match(r"(?i)^(?:Năm\s*)?20\d{2}\b", clean):
            continue

        # New semantic row candidate.
        flush_pending()
        code = None; label = clean
        label = re.sub(r"(?i)^Chỉ\s*tiêu\s*:\s*", "", label).strip()
        mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
        if mc: code, label = mc.group(1), mc.group(2)
        pending = {"label": label, "code": code, "note": None, "current": None, "previous": None,
                   "section": _section_from_label(label, section), "line": abs_line,
                   "pattern": "CF_PERIOD_CHILDREN", "indent": _line_indent(raw)}
    flush_pending()

    # PASS 2: period-major blocks (Năm 2025 -> many label:value rows; then Năm 2024 -> same labels).
    period_rows = {}
    section = None; active_year = None
    for rel, raw in enumerate(scoped_lines, start=1):
        abs_line = s + rel
        clean = _clean_bullet(raw)
        if not clean: continue
        for sec, pat in SECTION_PATTERNS.items():
            if pat.search(clean):
                section = sec; break
        my = re.match(r"(?i)^Năm\s*(20\d{2})(?:\s*\([^)]*\))?\s*:?$", clean)
        if not my:
            my = re.match(r"^(20\d{2})(?:\s*\([^)]*\))?\s*:?$", clean)
        if my:
            y = int(my.group(1)); active_year = y if y in {current_year, previous_year} else None; continue
        if active_year is None: continue
        m = re.match(r"^(.+?)\s*:\s*(\(?-?[\d.,]+\)?|-)(?:\s|$)", clean)
        if not m: continue
        label, val = strip_md(m.group(1)), parse_number(m.group(2))
        if not label or _looks_metadata_line(label): continue
        code = None
        mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
        if mc: code, label = mc.group(1), mc.group(2)
        sec = _section_from_label(label, section)
        key=(fold(label), sec, code or "")
        rec=period_rows.setdefault(key, {"label":label,"section":sec,"code":code,"current":None,"previous":None,"line":abs_line})
        if active_year == current_year: rec["current"] = val
        else: rec["previous"] = val
    for rec in period_rows.values():
        if rec["current"] is not None or rec["previous"] is not None:
            emit(rec["label"], rec["current"], rec["previous"], rec["section"], rec["code"], None, rec["line"], "CF_YEAR_SECTIONS")

    # PASS 3: positional numeric children under a semantic label.
    # Common LLM layout for bank direct statements:
    #   * Thu nhập lãi ...:
    #       * 85.076.748
    #       * 68.529.262
    # The two child numbers are current/previous even when the child lines do not repeat year labels.
    section = None
    for idx, raw in enumerate(scoped_lines):
        abs_line = s + idx + 1
        clean = _clean_bullet(raw)
        if not clean:
            continue
        for sec, pat in SECTION_PATTERNS.items():
            if pat.search(clean):
                section = sec
                break
        f = fold(clean)
        if _looks_metadata_line(clean):
            continue
        if re.match(r"(?i)^(?:Mã\s*số|Số|MS)\s*:\s*[^|]+$", clean):
            continue
        if re.match(r"(?i)^(?:Năm\s*)?20\d{2}\b", clean):
            continue
        if re.fullmatch(r"\(?-?[\d.,]+\)?|-", clean):
            continue
        cur, prev = _extract_inline_periods(clean, current_year, previous_year)
        if cur is not None or prev is not None:
            continue
        if re.search(r":\s*\(?-?\d{1,3}(?:[.,]\d{3})*", clean):
            continue
        if not re.search(r"[A-Za-zÀ-ỹ]", clean):
            continue
        if any(k in f for k in ("bao cao tai chinh", "cho nam tai chinh ket thuc", "don vi tinh", "nguoi lap", "ke toan truong", "tong giam doc", "metadata")):
            continue

        # Do not use pure section headings as observations unless they are semantic totals.
        matched_section = next((sec for sec, pat in SECTION_PATTERNS.items() if pat.search(clean)), None)
        if matched_section and "thuan" not in f:
            continue

        # Strip an optional leading form code from the label.
        code = None
        label = clean.rstrip(":").strip()
        mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
        if mc:
            code, label = mc.group(1), mc.group(2)

        nums = []
        year_vals = {}
        # Look only through the immediate child block. Stop when a new unrelated textual item begins.
        for j in range(idx + 1, min(len(scoped_lines), idx + 8)):
            child_raw = scoped_lines[j]
            child = _clean_bullet(child_raw)
            if not child:
                continue
            if re.match(r"^#\s*Page\b|^---$", child_raw.strip(), re.I):
                break
            cm = re.match(r"(?i)^(?:Mã\s*số|Số|MS)\s*:\s*([^|]+)$", child)
            if cm:
                code = strip_md(cm.group(1))
                continue
            if code is None and re.fullmatch(r"\b\d{1,2}\b", child.strip()):
                code = child.strip()
                continue
            # `Năm 2025 (triệu đồng): 123` / `Năm 2024: 456` children.
            ym = re.search(r"(?i)\b(20\d{2})\b(?:\s*\([^)]*\))?\s*:\s*(\(?-?[\d.,]+\)?|-)", child)
            if ym:
                year_vals[int(ym.group(1))] = parse_number(ym.group(2))
                if current_year in year_vals and previous_year in year_vals:
                    break
                continue
            # A year-only header inside the child block is context, not a value.
            if re.match(r"(?i)^(?:Năm\s*)?20\d{2}(?:\s*\([^)]*\))?\s*:?$", child):
                continue
            v = parse_number(child.rstrip(":"))
            if v is not None and re.fullmatch(r"\(?-?[\d.,]+\)?|-", child.rstrip(":")):
                nums.append(v)
                if len(nums) >= 2:
                    break
                continue
            # Explicit bullet labels such as `Mua sắm TSCĐ: 123` belong to another layout.
            if re.search(r"[A-Za-zÀ-ỹ]", child):
                break
        if year_vals:
            emit(label, year_vals.get(current_year), year_vals.get(previous_year),
                 _section_from_label(label, section), code, None, abs_line,
                 "CF_YEAR_VALUE_CHILDREN")
        elif nums:
            emit(label, nums[0], nums[1] if len(nums) > 1 else None,
                 _section_from_label(label, section), code, None, abs_line,
                 "CF_POSITIONAL_VALUE_CHILDREN")

    # Deduplicate/merge complementary observations from overlapping collectors.
    merged = {}
    order = []
    for r in rows:
        key = (fold(r.source_label), r.section or "", r.method or "", r.code or "")
        if key not in merged:
            merged[key] = r; order.append(key); continue
        old = merged[key]
        if old.current is None and r.current is not None:
            old.current = r.current
        if old.previous is None and r.previous is not None:
            old.previous = r.previous
        # Repeated-period block recovery. Some LLM conversions emit two complete blocks of
        # `label: value` rows but lose/mislabel the second period header. If the same semantic
        # row reappears materially later with another current-only value, treat the second
        # occurrence as previous rather than dropping it. Overlapping collectors on the same
        # source line are intentionally excluded.
        if (old.previous is None and old.current is not None and r.current is not None and r.previous is None
                and old.current != r.current
                and (old.source_line or 0) and (r.source_line or 0)
                and abs((r.source_line or 0) - (old.source_line or 0)) >= 5):
            old.previous = r.current
            old.pattern = (old.pattern or "") + "+CF_REPEATED_PERIOD_BLOCK"
        if not old.note and r.note: old.note = r.note
        if old.pattern != r.pattern and r.pattern and "CF_REPEATED_PERIOD_BLOCK" not in (old.pattern or ""):
            old.pattern = old.pattern or r.pattern
    dedup=[merged[k] for k in order if merged[k].current is not None or merged[k].previous is not None]

    return {**scope, "rows": [r.to_dict() for r in dedup], "method": method, "method_method": method_method,
            "sector": sector, "sector_method": sector_method}
