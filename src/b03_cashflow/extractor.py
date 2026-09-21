from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Optional

try:
    from src.common.value_semantics import detect_statement_unit, row_unit_override
    from src.common.report_period import resolve_report_years
except ImportError:
    try:
        from common.value_semantics import detect_statement_unit, row_unit_override
        from common.report_period import resolve_report_years
    except ImportError:
        from value_semantics import detect_statement_unit, row_unit_override
        from report_period import resolve_report_years

try:
    from flat_parser.statement_locator import StatementLocator
except ImportError:
    from statement_locator import StatementLocator

try:
    from src.common.source_recovery import attach_hierarchy_context
except ImportError:
    from common.source_recovery import attach_hierarchy_context

try:
    from src.common.row_block_scanner import attach_row_block_evidence, scan_row_blocks
except ImportError:
    from common.row_block_scanner import attach_row_block_evidence, scan_row_blocks



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
    # ``kinh doanh tài chính`` là tiêu đề tài chính trong một số báo cáo ngân hàng.
    # Không để tiền tố ngắn hơn của hoạt động kinh doanh nuốt tiêu đề này.
    "operating": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n(?:\s+t[ệe])?\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+kinh\s+doanh(?!\s+t[àa]i\s+ch[íi]nh)"),
    "investing": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n(?:\s+t[ệe])?\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+[đd][ầa]u\s+t[ưu]"),
    "financing": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n(?:\s+t[ệe])?\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+(?:t[àa]i\s+ch[íi]nh|kinh\s+doanh\s+t[àa]i\s+ch[íi]nh)"),
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
    # Tên semantic rõ ràng. ``code``/``note`` vẫn là alias tương thích cho
    # caller cũ, nhưng mapping chỉ được dùng statement_code và không bao giờ
    # dùng tham chiếu thuyết minh làm định danh dòng.
    statement_code: Optional[str] = None
    note_ref: Optional[str] = None
    source_line: Optional[int] = None
    pattern: Optional[str] = None
    unit: Optional[str] = None
    # Dạng serialize của nguồn nếu có. ``source_label`` vẫn là nhãn semantic
    # đã chuẩn hóa dùng cho mapper; trường này được tách riêng để các bước sau
    # có thể audit chính xác bằng chứng Markdown.
    raw_text: Optional[str] = None
    # Provenance cây nguồn, được gắn sau khi các collector đã deduplicate row.
    parent_label: Optional[str] = None
    hierarchy_path: Optional[str] = None

    def __post_init__(self):
        if self.statement_code is None:
            self.statement_code = self.code
        if self.code is None:
            self.code = self.statement_code
        if self.note_ref is None:
            self.note_ref = self.note
        if self.note is None:
            self.note = self.note_ref

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
    # Bỏ các từ đơn vị ở cuối như "triệu đồng", "triệu VND", "nghìn đồng",
    # "tỷ đồng", "đồng", "VND" và các biến thể tương tự.
    while True:
        ns = re.sub(r"(?i)\s*(?:tri[eệ]u|ngh[iì]n|t[yỷ]|vnd|vnđ|đ[oồ]ng)\b", "", s).strip()
        if ns == s:
            break
        s = ns
    s = s.strip()
    if s in {"-", "–", "—", "..."}:
        return None
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


def _split_statement_code_prefix(text: str):
    """Tách tiền tố mã báo cáo được serialize khỏi nhãn semantic."""

    clean = strip_md(text)
    match = re.match(
        r"(?i)^(?:mã\s*số|ma\s*so)\s*([0-9]{1,3}[a-z]?|[IVXLC]+)\s*[-–:]\s*(.+)$",
        clean,
    )
    if not match:
        match = re.match(
            r"^([0-9]{1,3}[a-z]?|[IVXLC]+)\s*[-–:]\s*(.+)$",
            clean,
            re.I,
        )
    if match:
        return strip_md(match.group(2)), match.group(1)
    return clean, None


def _looks_metadata_line(text: str) -> bool:
    s = strip_md(text)
    if not s:
        return True
    # Số thuần như "01", "02", "3.715.900".
    if parse_number(s) is not None:
        return True
    # Công thức thuần không có chữ như "(50 = 20 + 30 + 40)".
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
    # Tiêu đề kỳ.
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
    # Dòng địa điểm, vị trí hoặc ký tên.
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


def _has_inline_metadata_reference(text: str) -> bool:
    """Nhận diện dấu hai chấm của thuyết minh/đơn vị/mã trong tiêu đề dòng semantic.

    Dòng bắt đầu bằng mã như ``06. Chi phí ... (Thuyết minh: 30):`` có dấu
    hai chấm của metadata trước dấu hai chấm kết thúc nhãn. Nếu xem token số
    đầu tiên là giá trị dòng, ta sẽ mất các dòng con ``Năm nay`` và ``Năm trước``;
    vì vậy tiêu đề phải đi qua bộ thu dòng đang chờ.
    """

    return bool(re.search(
        r"\(\s*(?:Thuyết\s*minh|TM|Mã\s*số|Ma\s*so|Đơn\s*vị|Don\s*vi)\s*:",
        strip_md(text),
        re.I,
    ))


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
        "anh huong cua thay doi ty gia", "chenh lech quy doi tien te",
        "tien va cac khoan tuong duong tien tai thoi diem cuoi",
        "tien va cac khoan tuong duong tien cuoi nam", "tien va tuong duong tien cuoi",
    )):
        return "reconciliation"
    return current_section


def _candidate_scope(lines: list[str], start: int, next_candidate: Optional[int]) -> tuple[int, int, int]:
    hard_end = min(len(lines), start + 900)
    end = hard_end
    for i in range(start + 1, hard_end):
        clean = strip_md(lines[i])
        # Tiêu đề dòng tiền lặp lại trên trang tiếp theo không phải điểm dừng.
        if NOTES_RE.search(clean):
            end = i
            break
    if next_candidate is not None and next_candidate < end:
        # Không cắt nếu tiêu đề kế tiếp chỉ là trang tiếp theo trong phạm vi 350 dòng.
        window = "\n".join(lines[next_candidate:min(len(lines), next_candidate + 8)])
        if "tiếp theo" not in fold(window) and "tiep theo" not in fold(window):
            # Nếu candidate hiện tại có ít evidence trước candidate kế tiếp,
            # để bước xếp hạng tự chọn candidate phù hợp.
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
    # Khối lớn giống phần thuyết minh có rủi ro cao.
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
    """Chọn cửa sổ B03 có evidence lưu chuyển tiền mạnh nhất.

    Đầu vào là toàn bộ Markdown source. Hàm tìm heading ứng viên, chấm từng
    section theo anchor B03 và trả boundary 1-based, score và số candidate.
    Đầu ra là dict scope; nếu không có heading phù hợp, boundary là ``None``.
    """
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
    """Nhận diện phương pháp direct hoặc indirect trong scope B03.

    Đầu vào là text của scope đã chọn. Hàm ưu tiên heading rõ ràng, sau đó
    đếm semantic anchor của từng phương pháp. Đầu ra là ``(method, source)``;
    method có thể là ``unknown`` khi evidence không đủ.
    """
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
    """Nhận diện sector của B03 từ form cue và semantic anchor.

    Đầu vào là text scope. Hàm kiểm tra cue ngân hàng, chứng khoán, bảo hiểm và
    doanh nghiệp theo thứ tự specificity. Đầu ra là ``(sector, source)`` để
    caller ghi lại cách phát hiện, không dùng tên file làm quyết định.
    """
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
    """Trích xuất giá trị hiện tại/trước đây từ các bố cục inline phổ biến của LLM.

    v13 bổ sung:
    - `current (Năm 2025) | previous (Năm 2024)`;
    - `current (31.12.2025); previous (31.12.2024)`;
    - `current ... (Năm 2024: previous ...)`, trong đó hiện tại không có marker năm rõ.
    """
    clean = strip_md(text)
    vals = {}

    # Giá trị nằm ngay trước marker năm/ngày.
    marker_pat = re.compile(
        r"(?P<val>\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*"
        r"(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng)?\s*"
        r"\(\s*(?:Năm\s*)?(?:31[./-]12[./-])?(?P<year>20\d{2})\s*\)", re.I)
    for m in marker_pat.finditer(clean):
        vals[int(m.group("year"))] = parse_number(m.group("val"))

    # Giá trị trước đây/hiện tại nằm ngay trong chú thích năm: `(Năm 2024: 123 triệu đồng)`
    # hoặc `(Thuyết minh: 30; Năm 2024: 123 triệu đồng)`.
    anno_pat = re.compile(
        r"(?:\(|;)\s*Năm\s*(?P<year>20\d{2})\s*:\s*"
        r"(?P<val>\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*"
        r"(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng)?\s*\)", re.I)
    anno_matches = list(anno_pat.finditer(clean))
    for m in anno_matches:
        vals[int(m.group("year"))] = parse_number(m.group("val"))

    # Bố cục inline chung: `Nhãn: HIỆN TẠI triệu đồng (Năm 2024: TRƯỚC ĐÂY triệu đồng)`.
    # Nếu kỳ trước được ghi rõ nhưng kỳ hiện tại không có marker, lấy token số cuối
    # giữa dấu hai chấm đầu tiên của nhãn và chú thích làm giá trị hiện tại.
    if previous_year in vals and current_year not in vals and anno_matches:
        prefix = clean[:anno_matches[0].start()]
        mc = re.search(
            r":\s*(\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*"
            r"(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng)?\s*(?:\([^)]*)?$", prefix, re.I)
        if mc:
            vals[current_year] = parse_number(mc.group(1))

    if vals:
        return vals.get(current_year), vals.get(previous_year)

    # Giá trị trước `(Năm nay)` / `(Năm trước)`.
    role_pat = re.compile(
        r"(?P<val>\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*"
        r"(?:triệu\s*đồng|triệu\s*VND|VND|VNĐ|đồng)?\s*\(\s*Năm\s*(?P<role>nay|trước)\s*\)", re.I)
    role_vals = {}
    for m in role_pat.finditer(clean):
        role_vals[fold(m.group("role"))] = parse_number(m.group("val"))
    if role_vals:
        return role_vals.get("nay"), role_vals.get("truoc")

    # `Năm nay: x | Năm trước: y`.
    mn = re.search(r"(?i)Năm\s*nay\s*:\s*(\(?-?[\d.,]+\)?|-)", clean)
    mp = re.search(r"(?i)Năm\s*trước\s*:\s*(\(?-?[\d.,]+\)?|-)", clean)
    return (parse_number(mn.group(1)) if mn else None, parse_number(mp.group(1)) if mp else None)

def _join_raw_text(*values):
    """Nối các mảnh nguồn mà không chuẩn hóa làm mất bằng chứng Markdown."""

    parts = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in parts:
            parts.append(text)
    return "\n".join(parts) or None


def _emit(rows, label, current, previous, section, method, code, note, line_no, pattern, raw_text=None):
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
        raw_text=_join_raw_text(raw_text) or label,
    ))


def _major_column_token(text: str):
    """Trả về token số từ khối cột tách rời và giữ nguyên dấu gạch ngang."""

    value = strip_md(text).strip()
    if value in {"-", "–", "—"}:
        return True, None
    if re.fullmatch(r"\(?-?[\d][\d., ]*\)?", value):
        return True, parse_number(value)
    return False, None


def _short_statement_token(text: str) -> bool:
    value = strip_md(text).strip()
    return bool(re.fullmatch(r"\d{1,4}[A-Za-z]?", value))


def _column_label_line(raw: str):
    """Trả về (có bullet hoặc số thứ tự, nhãn) cho dòng nhãn tách rời."""

    value = raw.strip()
    marked = bool(re.match(r"^(?:[*+\-]|\d+[.)])\s+", value))
    value = re.sub(r"^(?:[*+\-]|\d+[.)])\s+", "", value)
    return marked, strip_md(value)


def _is_column_section_heading(label: str) -> bool:
    folded = fold(label)
    return any(pattern.search(label) for pattern in SECTION_PATTERNS.values()) or folded in {
        "dieu chinh cho cac khoan",
        "dieu chinh cho cac khoan",
    }


def _looks_wrapped_column_label(previous: str, current: str) -> bool:
    """Nhận diện nhãn bị xuống dòng mà không dựa vào mã dòng riêng của báo cáo."""

    prev = fold(previous)
    cur = fold(current)
    if not prev or not cur:
        return False
    if prev.endswith(" va") and cur.startswith(("cac ", "duoc ", "phai ", "cua ", "tai san ")):
        return True
    if prev.endswith(" cua") and cur.startswith("don vi"):
        return True
    if prev.endswith(" truoc") and cur.startswith("thay doi"):
        return True
    if prev.endswith(" danh gia") and cur.startswith("cac khoan muc"):
        return True
    if prev.endswith(" khong ke") and cur.startswith("phai tra"):
        return True
    if prev.endswith(" hoat dong kinh") and cur == "doanh":
        return True
    if prev.endswith(" hoat dong dau") and cur.startswith("tu "):
        return True
    if prev.endswith(" cong cu no") and cur.startswith("cua don vi"):
        return True
    if prev.endswith(" phat hanh co phieu") and cur.startswith("nhan von gop"):
        return True
    if prev.endswith(" loi nhuan") and cur.startswith("duoc chia"):
        return True
    return prev.endswith(" lai vay") and cur.startswith("phai tra")


def _is_report_noise_label(label: str) -> bool:
    """Trả về true với metadata tài liệu có thể nằm cạnh bảng.

    Hàm này cố ý không kiểm tra mã báo cáo hay mã thuyết minh. Mã chỉ là
    trường provenance và không bao giờ được quyết định một dòng có phải
    dòng semantic hay không.
    """

    folded = fold(label)
    if not folded:
        return True
    if re.match(r"^b\d{1,2}(?:\s|$)", folded):
        return True
    return folded.startswith((
        "bao cao luu chuyen",
        "cho nam tai chinh ket thuc",
        "don vi tinh",
        "thanh pho ",
        "ngay ",
        "nguoi lap",
        "ke toan truong",
    ))


def _pipe_cells(raw: str) -> list[str]:
    """Tách dòng bảng Markdown mà không làm mất các ô cấu trúc rỗng."""

    if "|" not in raw:
        return []
    return [strip_md(cell) for cell in raw.strip().strip("|").split("|")]


def _period_header_columns(raw: str):
    """Trả về các cột kỳ semantic từ header dạng pipe nếu có."""

    cells = _pipe_cells(raw)
    if not cells:
        return None
    roles = {}
    for idx, cell in enumerate(cells):
        folded = fold(cell)
        if folded.startswith(("nam nay", "ky nay")):
            roles["current"] = idx
        elif folded.startswith(("nam truoc", "ky truoc")):
            roles["previous"] = idx
        elif folded in {"thuyet minh", "dien giai", "note", "notes"}:
            roles["label"] = idx
    if "current" not in roles or "previous" not in roles:
        return None
    return roles


def _find_section_anchor(lines: list[str], end: int):
    """Tìm tiêu đề section dòng tiền gần nhất trước header của bảng."""

    fallback = None
    for idx in range(end - 1, -1, -1):
        clean = _clean_bullet(lines[idx])
        for section, pattern in SECTION_PATTERNS.items():
            if pattern.search(clean):
                if fallback is None:
                    fallback = (idx, section)
                raw = lines[idx].lstrip()
                # Dòng có bullet thường là dòng tổng semantic, không phải
                # tiêu đề section. Ưu tiên tiêu đề Markdown hoặc tiêu đề không
                # có bullet để các dòng trước vẫn nằm trong cùng khối cấu trúc.
                if raw.startswith("#") or not re.match(r"^(?:[*+\-]|\d+[.)])\s+", raw):
                    return idx, section
                break
    return fallback or (None, None)


def _collect_column_label_slots(
    lines: list[str],
    start: int,
    end: int,
    initial_section: str = "operating",
    include_semantic_section_totals: bool = False,
):
    """Tạo các slot dòng semantic từ khối nhãn của bảng theo cột."""

    slots = []
    section = initial_section or "operating"
    last_slot = None
    last_label = ""

    for idx in range(start, end):
        raw = lines[idx]
        marked, label = _column_label_line(raw)
        if not label:
            continue
        folded = fold(label)
        if _is_column_section_heading(label):
            matched = next((name for name, pattern in SECTION_PATTERNS.items() if pattern.search(label)), None)
            # Tiêu đề thường không có bullet hoặc có dấu heading Markdown.
            # Dòng có bullet, không có số thứ tự, dạng ``... thuần từ hoạt động ...``
            # có thể là dòng tổng semantic ngay trước bảng giá trị tách rời;
            # giữ dòng đó làm slot.
            ordinal_heading = bool(re.match(r"^(?:[IVXLC]+|\d+)[.)]\s+", label, re.I))
            keep_total_row = (
                include_semantic_section_totals
                and marked
                and not ordinal_heading
                and "thuan" in folded
            )
            if matched and not keep_total_row:
                section = matched
                continue
        if (_looks_metadata_line(label)
                or _is_report_noise_label(label)
                or folded in {"chi tieu", "ma so", "thuyet minh", "nam nay", "nam truoc"}):
            continue
        # Đây là tiêu đề con của cấu trúc, không phải dòng có giá trị.
        # Các dòng con sẽ được thu thập bình thường ở phía dưới.
        if folded in {"dieu chinh cho cac khoan", "cac dieu chinh cho cac khoan"}:
            continue

        if last_slot is not None and _looks_wrapped_column_label(last_label, label):
            last_slot["label"] = f"{last_slot['label']} {label}".strip()
            last_slot["raw_text"] = _join_raw_text(last_slot.get("raw_text"), raw)
            last_label = last_slot["label"]
            continue

        slot_section = _section_from_label(label, section)
        last_slot = {
            "label": label,
            "section": slot_section,
            "source_line": idx + 1,
            "raw_text": raw.strip(),
        }
        slots.append(last_slot)
        last_label = label

    return slots


def _extract_detached_period_table_rows(
    scoped_lines: list[str],
    absolute_start_zero: int,
    current_year: int,
    previous_year: int,
    method: str,
):
    """Khôi phục bảng có nhãn và giá trị kỳ bị làm phẳng tách rời.

    Một số chuyển đổi PDF sang Markdown phát ra nhãn semantic dưới dạng dòng
    thường, sau đó là bảng pipe chỉ chứa hai vector kỳ. Các ô đầu rỗng trong
    bảng là bằng chứng cấu trúc, không phải lý do bỏ giá trị. Chỉ nhận bố cục
    khi số slot trong khối nhãn khớp số dòng dữ liệu trong cùng section dòng tiền.
    """

    for header_idx, raw_header in enumerate(scoped_lines):
        columns = _period_header_columns(raw_header)
        if not columns:
            continue

        current_idx = columns["current"]
        previous_idx = columns["previous"]
        # Hai cột kỳ phải khác nhau và nằm sau cột nhãn hoặc cột cấu trúc rỗng.
        # Điều này giữ các bảng văn bản inline thông thường ngoài nhánh tách rời.
        if current_idx == previous_idx or min(current_idx, previous_idx) == 0:
            continue

        anchor_idx, section = _find_section_anchor(scoped_lines, header_idx)
        label_start = anchor_idx + 1 if anchor_idx is not None else max(0, header_idx - 80)
        slots = _collect_column_label_slots(
            scoped_lines,
            label_start,
            header_idx,
            initial_section=section or "operating",
            include_semantic_section_totals=True,
        )
        if not slots:
            continue

        data_rows = []
        saw_data = False
        for idx in range(header_idx + 1, min(len(scoped_lines), header_idx + 100)):
            raw = scoped_lines[idx]
            if "|" not in raw:
                if saw_data:
                    break
                continue
            cells = _pipe_cells(raw)
            if max(current_idx, previous_idx) >= len(cells):
                continue

            # Dòng tách rời không có text semantic trong các ô trước giá trị kỳ.
            # Bảng theo dòng thông thường được để cho CF_PIPE_TABLE xử lý.
            leading_cells = cells[:min(current_idx, previous_idx)]
            if any(re.search(r"[A-Za-zÀ-ỹ]", cell) for cell in leading_cells):
                if saw_data:
                    break
                continue

            current_raw = cells[current_idx]
            previous_raw = cells[previous_idx]
            current_is_value = current_raw in {"-", "–", "—"} or parse_number(current_raw) is not None
            previous_is_value = previous_raw in {"-", "–", "—"} or parse_number(previous_raw) is not None
            if not (current_is_value and previous_is_value):
                # Dòng đơn vị và dòng điều chỉnh là metadata của header cấu trúc.
                continue

            data_rows.append({
                "current": parse_number(current_raw),
                "previous": parse_number(previous_raw),
                "source_line": idx + 1,
                "raw_text": raw.strip(),
            })
            saw_data = True

        # Không ghép theo vị trí một khối chưa đủ. Kiểm tra số lượng này ngăn
        # việc nối chéo section tuy có vẻ hợp lệ nhưng thực tế bị sai.
        if not data_rows or len(data_rows) != len(slots):
            continue

        rows = []
        for slot, values in zip(slots, data_rows):
            rows.append(CashFlowObservation(
                source_label=slot["label"],
                current=values["current"],
                previous=values["previous"],
                section=slot["section"],
                method=method,
                code=None,
                note=None,
                statement_code=None,
                note_ref=None,
                source_line=absolute_start_zero + slot["source_line"],
                pattern="CF_DETACHED_PERIOD_TABLE",
                raw_text=_join_raw_text(slot.get("raw_text"), values.get("raw_text")),
            ))

        return {
            "rows": rows,
            "detected": True,
            "layout_type": "detached_period_table",
            "header_line": absolute_start_zero + header_idx + 1,
            "label_start_line": absolute_start_zero + label_start + 1,
            "label_end_line": absolute_start_zero + header_idx,
            "value_count": len(data_rows) * 2,
            "row_slots": len(slots),
            "vector_length": len(data_rows),
            "column_roles": columns,
            "current_year": current_year,
            "previous_year": previous_year,
        }

    return {"rows": [], "detected": False, "reason": "no_detached_period_table"}


def _extract_column_major_cashflow_rows(
    scoped_lines: list[str],
    absolute_start_zero: int,
    current_year: int,
    previous_year: int,
    method: str,
):
    """Khôi phục dòng khi bảng bị làm phẳng thành các khối nhãn/mã/giá trị.

    Bộ nhận diện dựa trên header bảng và cấu trúc tuần tự của các chuỗi
    nhãn/giá trị. Các cột mã và thuyết minh, nếu có, được bỏ qua như metadata;
    chúng không bao giờ quyết định định danh dòng.
    """

    detached = _extract_detached_period_table_rows(
        scoped_lines,
        absolute_start_zero,
        current_year,
        previous_year,
        method,
    )
    if detached.get("detected"):
        return detached

    header_candidates = []
    for idx, raw in enumerate(scoped_lines):
        if "|" in raw:
            continue
        folded = fold(raw)
        if folded in {"chi tieu", "chi tieu items"} or "chi tieu" == folded:
            window = " ".join(fold(x) for x in scoped_lines[idx:idx + 8])
            if "ma so" in window and ("nam nay" in window or "nam truoc" in window):
                header_candidates.append(idx)
    if not header_candidates:
        return {"rows": [], "detected": False, "reason": "no_detached_header"}

    for header_idx in header_candidates:
        # Khối nhãn tách rời kết thúc ở chuỗi số ngắn đầu tiên. Cần nhiều token
        # liên tiếp để nhãn có số thứ tự thông thường không kích hoạt nhận diện.
        numeric_start = None
        for idx in range(header_idx + 1, len(scoped_lines)):
            if "|" in scoped_lines[idx]:
                continue
            clean_value = strip_md(scoped_lines[idx]).strip()
            if not _short_statement_token(clean_value):
                continue
            run = 0
            j = idx
            while j < len(scoped_lines) and run < 3:
                candidate = strip_md(scoped_lines[j]).strip()
                if not candidate:
                    j += 1
                    continue
                if _short_statement_token(candidate):
                    run += 1
                    j += 1
                    continue
                break
            if run >= 3:
                numeric_start = idx
                break
        if numeric_start is None:
            continue

        slots = _collect_column_label_slots(scoped_lines, header_idx + 1, numeric_start)
        if len(slots) < 4:
            continue

        values = []
        value_raw_texts = []
        for raw in scoped_lines[numeric_start:]:
            if "|" in raw:
                continue
            token = strip_md(raw).strip()
            if not token or _short_statement_token(token):
                continue
            is_value, value = _major_column_token(token)
            if is_value:
                values.append(value)
                value_raw_texts.append(raw.strip())

        # Bảng tách rời hai kỳ có hai vector giá trị tuần tự. Chỉ chấp nhận
        # hai vector có cùng độ dài khi chúng phủ đúng số slot dòng; nếu không,
        # để tài liệu ở trạng thái cần xem xét thay vì ghép cưỡng bức.
        if len(values) < 2 * len(slots):
            continue
        vector_length = len(values) // 2
        if vector_length != len(slots):
            # Giá trị thừa có thể thuộc một mảnh tiếp nối. Chỉ dùng tiền tố đối
            # xứng đầy đủ khi ranh giới của nó rõ ràng.
            if len(values) % 2 or vector_length < 4:
                continue
            slots = slots[:vector_length]
            if len(slots) != vector_length:
                continue

        current_values = values[:vector_length]
        previous_values = values[vector_length:vector_length * 2]
        rows = []
        current_raw_texts = value_raw_texts[:vector_length]
        previous_raw_texts = value_raw_texts[vector_length:vector_length * 2]
        for index, (slot, current, previous) in enumerate(zip(slots, current_values, previous_values)):
            if current is None and previous is None:
                continue
            rows.append(CashFlowObservation(
                source_label=slot["label"],
                current=current,
                previous=previous,
                section=slot["section"],
                method=method,
                code=None,
                note=None,
                statement_code=None,
                note_ref=None,
                source_line=absolute_start_zero + slot["source_line"],
                pattern="CF_COLUMN_MAJOR_STRUCTURAL",
                raw_text=_join_raw_text(
                    slot.get("raw_text"),
                    current_raw_texts[index] if index < len(current_raw_texts) else None,
                    previous_raw_texts[index] if index < len(previous_raw_texts) else None,
                ),
            ))
        if rows:
            return {
                "rows": rows,
                "detected": True,
                "header_line": absolute_start_zero + header_idx + 1,
                "label_start_line": absolute_start_zero + header_idx + 2,
                "label_end_line": absolute_start_zero + numeric_start,
                "value_count": len(values),
                "row_slots": len(slots),
                "vector_length": vector_length,
                "current_year": current_year,
                "previous_year": previous_year,
            }
    return {"rows": [], "detected": False, "reason": "no_symmetric_value_vectors"}


def _period_value_line(clean: str, current_year: int, previous_year: int):
    """Đọc vai trò kỳ và giá trị từ một dòng kỳ độc lập."""

    if ":" not in clean:
        return None
    head, value_text = clean.split(":", 1)
    folded_head = fold(head)
    role = None
    if re.search(r"\b(?:nam|ky)\s+nay\b", folded_head):
        role = "current"
    elif re.search(r"\b(?:nam|ky)\s+truoc\b", folded_head):
        role = "previous"
    else:
        years = [int(year) for year in re.findall(r"\b20\d{2}\b", folded_head)]
        if years:
            if years[-1] == current_year:
                role = "current"
            elif years[-1] == previous_year:
                role = "previous"
    if role is None:
        return None
    value_text = value_text.strip()
    if value_text not in {"-", "–", "—"} and parse_number(value_text) is None:
        return None
    return role, parse_number(value_text)


def _next_value_before_label(scoped_lines: list[str], value_idx: int, current_year: int, previous_year: int):
    """Tìm nhãn semantic theo sau một giá trị kỳ độc lập."""

    value_indent = _line_indent(scoped_lines[value_idx])
    for idx in range(value_idx + 1, min(len(scoped_lines), value_idx + 7)):
        raw = scoped_lines[idx]
        clean = _clean_bullet(raw)
        if not clean:
            continue
        # Dấu phân cách, tiêu đề trang hoặc tiêu đề hành chính/chữ ký kết thúc
        # dòng bảng. Nếu bỏ qua và đi tiếp vào tên con thụt lề, giá trị tài chính
        # trước đó sẽ bị gắn nhầm vào tên người.
        if clean == "---" or raw.lstrip().startswith("#"):
            return None
        if "|" in raw:
            return None
        if _period_value_line(clean, current_year, previous_year):
            return None
        if any(pattern.search(clean) for pattern in SECTION_PATTERNS.values()):
            return None
        if _is_report_noise_label(clean):
            return None
        if _looks_metadata_line(clean):
            # Metadata cấp dòng có thể nằm giữa giá trị độc lập và nhãn semantic;
            # metadata hành chính là ranh giới cứng.
            if re.match(r"(?i)^(?:Thuyết\s*minh|Mã(?:\s*số)?|Số|MS)\s*:", clean):
                continue
            return None
        if _extract_inline_periods(clean, current_year, previous_year) != (None, None):
            return None
        if not re.search(r"[A-Za-zÀ-ỹ]", clean):
            continue
        # Trong hierarchy bị làm phẳng thông thường, nhãn là dòng con của dòng
        # giá trị kỳ. Cần yêu cầu độ thụt lề sâu hơn; nếu không, dòng bình thường
        # ``nhãn -> giá trị năm`` sẽ khiến giá trị kỳ cuối bị xem là giá trị của
        # cặp value-before-label kế tiếp.
        if _line_indent(raw) <= value_indent:
            return None
        label = re.sub(r"^(?:[IVXLC]+|\d{1,3}(?:\.\d+)*)[.)]?\s+", "", clean, flags=re.I).strip()
        if not label or _looks_metadata_line(label):
            return None
        return label, idx
    return None


def _extract_value_before_label_rows(
    scoped_lines: list[str],
    absolute_start_zero: int,
    current_year: int,
    previous_year: int,
    method: str,
):
    """Khôi phục dòng phát ra theo dạng ``giá trị kỳ`` rồi đến nhãn dòng.

    Việc ghép mang tính cục bộ và semantic: dùng vai trò kỳ, nhãn gần đó,
    section và thứ tự xuất hiện. Không dùng mã báo cáo hay tham chiếu thuyết minh.
    """

    records = []
    section = None
    last_note = None

    for idx, raw in enumerate(scoped_lines):
        clean = _clean_bullet(raw)
        if not clean:
            continue
        for candidate_section, pattern in SECTION_PATTERNS.items():
            if pattern.search(clean):
                section = candidate_section
                break

        note_match = re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.+)$", clean)
        if note_match:
            last_note = strip_md(note_match.group(1))
            continue

        period = _period_value_line(clean, current_year, previous_year)
        if not period:
            continue
        role, value = period
        following = _next_value_before_label(scoped_lines, idx, current_year, previous_year)
        if not following:
            continue
        label, label_idx = following
        row_section = _section_from_label(label, section)

        # Ưu tiên occurrence chưa đủ gần nhất của cùng nhãn semantic. Cách này
        # hỗ trợ cả thứ tự hiện tại-trước đây và trước đây-hiện tại mà không
        # gộp các nhãn thực sự lặp lại thành một dòng.
        key = (fold(label), row_section or "", method or "")
        target = None
        for record in reversed(records):
            if record["key"] != key:
                continue
            if role == "current" and record["current"] is None:
                target = record
                break
            if role == "previous" and record["previous"] is None:
                target = record
                break
        if target is None:
            target = {
                "key": key,
                "label": label,
                "section": row_section,
                "current": None,
                "previous": None,
                "note": last_note,
                "line": absolute_start_zero + label_idx + 1,
                "raw_lines": [raw.strip(), scoped_lines[label_idx].strip()],
            }
            records.append(target)
        else:
            target.setdefault("raw_lines", []).append(raw.strip())
        target[role] = value
        if not target.get("note") and last_note:
            target["note"] = last_note

    rows = []
    for record in records:
        if record["current"] is None and record["previous"] is None:
            continue
        rows.append(CashFlowObservation(
            source_label=record["label"],
            current=record["current"],
            previous=record["previous"],
            section=record["section"],
            method=method,
            code=None,
            note=record.get("note"),
            statement_code=None,
            note_ref=record.get("note"),
            source_line=record["line"],
            pattern="CF_VALUE_BEFORE_LABEL",
            raw_text=_join_raw_text(*record.get("raw_lines", []), record["label"]),
        ))
    return {
        "rows": rows,
        "detected": bool(rows),
        "rows_recovered": len(rows),
    }


def extract_cashflow_fallback(
    text: str,
    current_year=None,
    previous_year=None,
    fallback_unit: Optional[str] = None,
    locator_result: Optional[dict] = None,
    preserve_decimal_branch_rows: bool = True,
    row_scan_mode: str = "off",
):
    """Trích xuất dòng B03 và giữ ngữ cảnh section cùng phương pháp.

    Đầu vào:
    - ``text``: toàn bộ Markdown source;
    - cặp năm, unit và ``locator_result`` tùy chọn.

    Xử lý:
    - chọn scope, rồi kiểm tra candidate locator;
    - nhận diện sector và direct/indirect;
    - chạy collector cho bảng, bullet, inline và code-led row;
    - giữ section, mã/thuyết minh và raw text làm provenance.

    Đầu ra là dict gồm ``rows``, scope, method, sector, unit và diagnostics.
    Row chưa map vẫn được trả về để mapper hoặc source recovery xử lý tiếp.

    Bố cục trực tiếp và gián tiếp có ngữ nghĩa dòng khác nhau. Vì vậy, bộ
    trích xuất xác định phương pháp và scope trước khi mapping, đồng thời giữ
    các bảng bổ sung chưa hỗ trợ ở dạng observation nguồn thay vì ép chúng vào
    một node canonical không liên quan.
    """
    if row_scan_mode not in {"off", "shadow", "assist"}:
        raise ValueError(f"Unsupported row_scan_mode: {row_scan_mode}")

    period = resolve_report_years(
        text,
        source_name="input",
        current_year=current_year,
        previous_year=previous_year,
    )
    current_year = period["current_year"]
    previous_year = period["previous_year"]
    scope = choose_cashflow_scope(text)
    locator = dict(locator_result or {}) if locator_result else None
    if locator is not None and scope.get("scope_start_line") and scope.get("scope_end_line"):
        baseline_start = int(scope["scope_start_line"])
        baseline_end = int(scope["scope_end_line"])
        accepted, reason = StatementLocator.evaluate_scope(
            locator,
            baseline_start,
            baseline_end,
        )
        baseline_unhealthy = (baseline_end - baseline_start) < 8 or float(scope.get("scope_score") or 0) < -500
        if not accepted and baseline_unhealthy:
            selected = locator.get("selected_scope") or {}
            chosen = next(
                (
                    candidate
                    for candidate in (locator.get("candidates") or [])
                    if candidate.get("start_line") == selected.get("start_line")
                    and candidate.get("end_line") == selected.get("end_line")
                ),
                {},
            )
            if selected and chosen.get("title_detected") and float(selected.get("confidence") or 0.0) >= 0.72:
                accepted = True
                reason = "baseline_scope_unhealthy_recovered"
        locator["activation"] = {
            "activated": accepted,
            "reason": reason,
            "baseline_start": scope.get("scope_start_line"),
            "baseline_end": scope.get("scope_end_line"),
        }
        if accepted:
            selected = locator["selected_scope"]
            scope = dict(scope)
            scope["scope_start_line"] = int(selected["start_line"])
            scope["scope_end_line"] = int(selected["end_line"])
            scope["scope_score"] = selected.get("score", scope.get("scope_score"))
            scope["scope_method"] = "alias_assisted_locator"
    elif locator is not None:
        selected = locator.get("selected_scope") or {}
        chosen = next(
            (
                candidate
                for candidate in (locator.get("candidates") or [])
                if candidate.get("start_line") == selected.get("start_line")
                and candidate.get("end_line") == selected.get("end_line")
            ),
            {},
        )
        recovered = bool(
            selected
            and chosen.get("title_detected")
            and float(selected.get("confidence") or 0.0) >= 0.72
        )
        locator["activation"] = {
            "activated": recovered,
            "reason": "baseline_scope_missing_recovered" if recovered else "baseline_scope_missing",
            "baseline_start": scope.get("scope_start_line"),
            "baseline_end": scope.get("scope_end_line"),
        }
        if recovered:
            scope = dict(scope)
            scope["scope_start_line"] = int(selected["start_line"])
            scope["scope_end_line"] = int(selected["end_line"])
            scope["scope_score"] = selected.get("score", scope.get("scope_score"))
            scope["scope_method"] = "alias_assisted_locator"
    scope["locator"] = locator
    row_block_scan = None
    if row_scan_mode != "off" and scope.get("scope_start_line") and scope.get("scope_end_line"):
        row_block_scan = scan_row_blocks(
            text,
            int(scope["scope_start_line"]),
            int(scope["scope_end_line"]),
            profile="cash_flow",
        )
    if not scope.get("scope_start_line"):
        unit_val = fallback_unit if fallback_unit and fallback_unit != "unknown" else "unknown"
        return {
            **scope,
            "rows": [],
            "method": "unknown",
            "method_method": "unknown",
            "sector": "unknown",
            "sector_method": "unknown",
            "unit": unit_val,
            "row_block_scan": row_block_scan,
        }
    lines = text.splitlines()
    s = scope["scope_start_line"] - 1
    e = scope["scope_end_line"]
    source_scoped_lines = lines[s:e]
    scoped_lines = source_scoped_lines
    # Tiền xử lý scoped_lines để ghép các dòng text bị xuống dòng nhưng thuộc
    # cùng một ô, ví dụ ô bảng OCR bị wrap qua nhiều dòng.
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

    column_major_layout = _extract_column_major_cashflow_rows(
        source_scoped_lines,
        s,
        current_year,
        previous_year,
        method,
    )
    rows = list(column_major_layout.get("rows") or [])
    value_before_label_layout = _extract_value_before_label_rows(
        source_scoped_lines,
        s,
        current_year,
        previous_year,
        method,
    )
    rows.extend(value_before_label_layout.get("rows") or [])
    section = None
    pending = None

    def emit(label, current=None, previous=None, sec=None, code=None, note=None, line_no=None, pattern=None, raw_text=None):
        label = strip_md(label)
        label = re.sub(r"(?i)^(?:Chỉ\s*tiêu|Chi\s*tiết)\s*:\s*", "", label).strip()
        if not label or _looks_metadata_line(label):
            return
        fl = fold(label)
        if fl in {"page", "year", "so trang", "trang"} or fl.startswith(("createdat", "pageocrat", "updatedat", "s3 key", "file name", "search folder")):
            return
        if fl.startswith("nam tai chinh ket thuc ngay") or fl.startswith("ngay 31 thang 12 nam"):
            return
        _emit(rows, label, current, previous, _section_from_label(label, sec), method, code, note, line_no, pattern,
              raw_text=raw_text)

    def flush_pending():
        nonlocal pending
        if pending and (pending.get("current") is not None or pending.get("previous") is not None):
            emit(pending.get("label"), pending.get("current"), pending.get("previous"),
                 pending.get("section"), pending.get("code"), pending.get("note"),
                 pending.get("line"), pending.get("pattern", "CF_PERIOD_CHILDREN"),
                 pending.get("raw_text"))
        pending = None

    def pending_accepts_child(raw_line: str) -> bool:
        """Chỉ gắn metadata/kỳ vào semantic row nếu còn nằm dưới row đó.

        Bản Markdown có thể giữ hai dòng ``Năm nay`` ở cùng mức thụt lề với
        hai sibling semantic khác nhau. Trước đây B03 chỉ dùng biến ``pending``
        theo thứ tự dòng, không kiểm tra indent, nên giá trị tổng của parent
        bị kéo vào child ngay trước đó (ví dụ mã 08 ``Dự thu tiền lãi``).
        Dòng plain không thụt lề vẫn giữ tương thích với layout cũ; guard chỉ
        chặn cấu trúc bullet có indent rõ ràng.
        """

        if not pending:
            return False
        pending_indent = pending.get("indent")
        if pending_indent in (None, 0):
            return True
        return _line_indent(raw_line) > pending_indent

    # LƯỢT 1: dòng parent/child, pipe, inline và dòng bắt đầu bằng mã thông thường.
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
        # Tiêu đề section không có payload số.
        if matched_section and parse_number(re.sub(r".*?:", "", clean)) is None and not re.search(r"(?i)(?:20\d{2}|Năm\s+(?:nay|trước))\s*:", clean):
            # Dòng tổng là dòng semantic; tiêu đề thuần chỉ chuyển section.
            if "thuan" not in f and "thuần" not in clean.casefold() and not re.match(r"^(?:[IVXLC]+|\d+)[.)]", clean):
                flush_pending(); section = matched_section; continue
            section = matched_section

        # Dòng metadata/giá trị con, gồm cả năm ghi rõ vì LLM thường bỏ Năm nay/Năm trước.
        # Markdown OCR/LLM luân phiên dùng ``Mã số:``, ``Mã:`` và ``MS:``.
        # Xem cả ba là cùng một field của dòng có khóa. Nếu ``Mã:`` rơi xuống
        # thành nhãn mới, các dòng kỳ sau sẽ gắn vào token metadata và dòng tiền
        # thật sẽ bị bỏ qua mà không báo lỗi.
        m = re.match(r"(?i)^(?:Mã(?:\s*số)?|Số|MS)\s*:\s*([^|]+)$", clean)
        if m:
            code_val = strip_md(m.group(1))
            if pending and not pending_accepts_child(raw):
                flush_pending()
                continue
            if pending and (pending.get("current") is not None or pending.get("previous") is not None):
                flush_pending()
                pending = {"label": "", "code": code_val, "note": None, "current": None, "previous": None,
                           "section": section, "line": abs_line, "pattern": "CF_PERIOD_CHILDREN",
                           "indent": _line_indent(raw), "raw_text": raw.strip()}
            elif pending:
                pending["code"] = code_val
                pending["raw_text"] = _join_raw_text(pending.get("raw_text"), raw)
            continue

        m = re.match(r"(?i)^Chi\s*tiết\s*:\s*(.+)$", clean)
        if m and pending:
            if not pending_accepts_child(raw):
                flush_pending()
                continue
            pending["label"] = strip_md(m.group(1))
            pending["raw_text"] = _join_raw_text(pending.get("raw_text"), raw)
            continue

        m = re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.+)$", clean)
        if m and pending:
            if not pending_accepts_child(raw):
                flush_pending()
                continue
            pending["note"] = strip_md(m.group(1))
            pending["raw_text"] = _join_raw_text(pending.get("raw_text"), raw)
            continue

        # Một số báo cáo bị làm phẳng serialize nhãn semantic dưới dạng dòng con
        # tên ``Diễn giải`` sau mã và giá trị kỳ. Giữ giá trị trong block hiện tại
        # và chỉ thay heading do serializer tạo ra; mã biểu mẫu vẫn là provenance
        # và không bao giờ được dùng làm định danh dòng.
        m = re.match(r"(?i)^Diễn\s*giải\s*:\s*(.+)$", clean)
        if m and pending:
            if not pending_accepts_child(raw):
                flush_pending()
                continue
            pending["label"] = strip_md(m.group(1))
            pending["section"] = _section_from_label(pending["label"], pending.get("section"))
            pending["raw_text"] = _join_raw_text(pending.get("raw_text"), raw)
            continue

        m = re.match(r"(?i)^(?:Năm\s*nay|Kỳ\s*này)(?:\s*\([^)]*\))?\s*:\s*(.+)$", clean)
        if m and pending:
            if not pending_accepts_child(raw):
                flush_pending()
                continue
            pending["current"] = parse_number(m.group(1))
            pending["raw_text"] = _join_raw_text(pending.get("raw_text"), raw)
            continue

        m = re.match(r"(?i)^(?:Năm\s*trước|Kỳ\s*trước)(?:\s*\([^)]*\))?\s*:\s*(.+)$", clean)
        if m and pending:
            if not pending_accepts_child(raw):
                flush_pending()
                continue
            pending["previous"] = parse_number(m.group(1))
            pending["raw_text"] = _join_raw_text(pending.get("raw_text"), raw)
            continue

        m = re.search(r"(?i)\b(20\d{2})\b(?:\s*\([^)]*\))?\s*:\s*(\(?-?[\d.,]+\)?|-)", clean)
        if m and pending:
            if not pending_accepts_child(raw):
                flush_pending()
                continue
            yr, val = int(m.group(1)), parse_number(m.group(2))
            if yr == current_year: pending["current"] = val
            elif yr == previous_year: pending["previous"] = val
            pending["raw_text"] = _join_raw_text(pending.get("raw_text"), raw)
            continue

        # Dòng bảng pipe: nhãn | mã? | thuyết minh? | hiện tại | trước đây.
        # v22.4: giữ vị trí cột dù một kỳ được báo bằng dấu gạch/null.
        # Không suy luận từ hai token *số* cuối vì cách đó đẩy mã biểu mẫu vào
        # cột giá trị khi hiện tại/trước đây là '-'.
        if raw.count("|") >= 2:
            cells = [strip_md(x) for x in raw.strip().strip("|").split("|")]
            if len(cells) >= 3 and not any(fold(x) in {"chi tieu", "nam nay", "nam truoc", "stt chi tieu"} for x in cells[:2]):
                cur_raw, prev_raw = cells[-2], cells[-1]
                cur_is_value = bool(re.fullmatch(r"\(?-?[\d., ]+\)?|-|–|—", cur_raw))
                prev_is_value = bool(re.fullmatch(r"\(?-?[\d., ]+\)?|-|–|—", prev_raw))
                if cur_is_value and prev_is_value:
                    cur_val, prev_val = parse_number(cur_raw), parse_number(prev_raw)
                    code = next((c for c in cells[:-2] if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+", c, re.I)), None)
                    text_cells = [c for c in cells[:-2] if re.search(r"[A-Za-zÀ-ỹ]", c) and not _looks_metadata_line(c)]
                    label = max(text_cells, key=len) if text_cells else cells[0]
                    mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
                    if mc and not code:
                        code, label = mc.group(1), mc.group(2)
                    flush_pending(); emit(label, cur_val, prev_val, section, code, None, abs_line, "CF_PIPE_TABLE", raw_text=raw); continue

        # Giá trị năm inline trên một dòng.
        cur, prev = _extract_inline_periods(clean, current_year, previous_year)
        if cur is not None or prev is not None:
            clean_without_numbers = re.sub(r"(?i)\b20\d{2}\b|\(?-?[\d.,]+\)?|\b(nam|ky|trieu|vnd|dong)\b|[;:.,()\-]", "", fold(clean)).strip()
            if pending and not clean_without_numbers and not pending_accepts_child(raw):
                flush_pending()
                continue
            if pending and not clean_without_numbers:
                pending["current"] = cur
                pending["previous"] = prev
                pending["raw_text"] = _join_raw_text(pending.get("raw_text"), raw)
                continue
            flush_pending()
            label = re.split(r"(?i):\s*(?:\*\*)?(?:[–—-]|(?:\(?-?\d))|\s+(?:\(?-?\d{1,3}[.,]\d{3})", clean, maxsplit=1)[0]
            label, code = _split_statement_code_prefix(label)
            mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
            if mc: code, label = mc.group(1), mc.group(2)
            emit(label, cur, prev, section, code, None, abs_line, "CF_INLINE_PERIODS", raw_text=raw); continue

        # Dòng bắt đầu bằng mã/văn bản thuần có một giá trị số: `01 nhãn: 123`.
        mc = re.match(r"^(?:\*\s*)?([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+?)\s*:\s*(\(?-?[\d.,]+\)?|-)(?:\s|$)", clean, re.I)
        if mc and not _has_inline_metadata_reference(clean):
            flush_pending()
            code, label, val = mc.group(1), mc.group(2), parse_number(mc.group(3))
            emit(label, val, None, section, code, None, abs_line, "CF_PLAIN_TEXT_CODE", raw_text=raw); continue

        # Tiêu đề/nhãn có một giá trị inline, ví dụ `LƯU CHUYỂN ...: 57.639.048`.
        mh = re.match(r"^(.+?)\s*:\s*(\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)(?:\s*(?:triệu\s*(?:đồng|VND|VNĐ)|nghìn\s*đồng|VND|VNĐ|đồng))?(?:\s|$)", clean)
        if mh and not _has_inline_metadata_reference(clean) and re.search(r"[A-Za-zÀ-ỹ]", mh.group(1)):
            label, code = _split_statement_code_prefix(mh.group(1))
            flush_pending(); emit(label, parse_number(mh.group(2)), None, section, code, None, abs_line, "CF_HEADING_VALUE", raw_text=raw); continue

        if _looks_metadata_line(clean):
            continue
        if any(k in f for k in ("bao cao tai chinh hop nhat", "cho nam tai chinh ket thuc", "don vi tinh", "nguoi lap", "ke toan truong", "tong giam doc", "metadata", "s3 key", "page ocr")):
            continue
        if re.match(r"(?i)^(?:Mã(?:\s*số)?|Số|MS)\s*:\s*[^|]+$", clean):
            continue
        if re.match(r"(?i)^(?:Năm\s*)?20\d{2}\b", clean):
            continue

        # Dòng semantic mới.
        flush_pending()
        code = None; label = clean
        label = re.sub(r"(?i)^Chỉ\s*tiêu\s*:\s*", "", label).strip()
        label, prefix_code = _split_statement_code_prefix(label)
        code = prefix_code
        mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
        if mc: code, label = mc.group(1), mc.group(2)
        pending = {"label": label, "code": code, "note": None, "current": None, "previous": None,
                   "section": _section_from_label(label, section), "line": abs_line,
                   "pattern": "CF_PERIOD_CHILDREN", "indent": _line_indent(raw), "raw_text": raw.strip()}
    flush_pending()

    # LƯỢT 2: block theo kỳ (Năm 2025 -> nhiều dòng nhãn:giá trị; sau đó
    # Năm 2024 -> các nhãn tương ứng).
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
        role_header = re.match(r"(?i)^Năm\s*(nay|trước)\s*:?$", clean)
        if role_header:
            active_year = current_year if fold(role_header.group(1)) == "nay" else previous_year
            continue
        if active_year is None: continue
        m = re.match(r"^(.+?)\s*:\s*(\(?-?[\d.,]+\)?|-)(?:\s|$)", clean)
        if not m: continue
        label, val = strip_md(m.group(1)), parse_number(m.group(2))
        if not label or _looks_metadata_line(label): continue
        label, code = _split_statement_code_prefix(label)
        mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
        if mc: code, label = mc.group(1), mc.group(2)
        sec = _section_from_label(label, section)
        # Ghép observation tách theo kỳ bằng nhãn semantic và section báo cáo.
        # Mã biểu mẫu chỉ giữ làm metadata, không bao giờ làm khóa dòng.
        key=(fold(label), sec)
        rec=period_rows.setdefault(key, {"label":label,"section":sec,"code":code,"current":None,"previous":None,
                                          "line":abs_line,"raw_text":raw.strip()})
        rec["raw_text"] = _join_raw_text(rec.get("raw_text"), raw)
        if active_year == current_year: rec["current"] = val
        else: rec["previous"] = val
    for rec in period_rows.values():
        if rec["current"] is not None or rec["previous"] is not None:
            emit(rec["label"], rec["current"], rec["previous"], rec["section"], rec["code"], None, rec["line"],
                 "CF_YEAR_SECTIONS", raw_text=rec.get("raw_text"))

    # LƯỢT 3: dòng con số theo vị trí dưới một nhãn semantic.
    # Bố cục LLM thường gặp trong báo cáo trực tiếp của ngân hàng:
    #   * Thu nhập lãi ...:
    #       * 85.076.748
    #       * 68.529.262
    # Hai số con là hiện tại/trước đây dù các dòng con không lặp lại nhãn năm.
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
        if re.match(r"(?i)^(?:Mã(?:\s*số)?|Số|MS)\s*:\s*[^|]+$", clean):
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

        # Không dùng tiêu đề section thuần làm observation nếu nó không phải dòng tổng semantic.
        matched_section = next((sec for sec, pat in SECTION_PATTERNS.items() if pat.search(clean)), None)
        if matched_section and "thuan" not in f:
            continue

        # Bỏ mã biểu mẫu tùy chọn ở đầu nhãn.
        code = None
        label = clean.rstrip(":").strip()
        mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
        if mc:
            code, label = mc.group(1), mc.group(2)

        nums = []
        year_vals = {}
        child_raw_lines = []
        # Chỉ quét block dòng con trực tiếp. Dừng khi xuất hiện item text mới không liên quan.
        for j in range(idx + 1, min(len(scoped_lines), idx + 8)):
            child_raw = scoped_lines[j]
            child = _clean_bullet(child_raw)
            if not child:
                continue
            if re.match(r"^#\s*Page\b|^---$", child_raw.strip(), re.I):
                break
            cm = re.match(r"(?i)^(?:Mã(?:\s*số)?|Số|MS)\s*:\s*([^|]+)$", child)
            if cm:
                code = strip_md(cm.group(1))
                continue
            if code is None and re.fullmatch(r"\b\d{1,2}\b", child.strip()):
                code = child.strip()
                continue
            # Dòng con dạng `Năm 2025 (triệu đồng): 123` / `Năm 2024: 456`.
            ym = re.search(r"(?i)\b(20\d{2})\b(?:\s*\([^)]*\))?\s*:\s*(\(?-?[\d.,]+\)?|-)", child)
            if ym:
                year_vals[int(ym.group(1))] = parse_number(ym.group(2))
                child_raw_lines.append(child_raw.strip())
                if current_year in year_vals and previous_year in year_vals:
                    break
                continue
            # Header chỉ có năm trong block con là ngữ cảnh, không phải giá trị.
            if re.match(r"(?i)^(?:Năm\s*)?20\d{2}(?:\s*\([^)]*\))?\s*:?$", child):
                continue
            v = parse_number(child.rstrip(":"))
            if v is not None and re.fullmatch(r"\(?-?[\d.,]+\)?|-", child.rstrip(":")):
                nums.append(v)
                child_raw_lines.append(child_raw.strip())
                if len(nums) >= 2:
                    break
                continue
            # Nhãn bullet rõ như `Mua sắm TSCĐ: 123` thuộc một bố cục khác.
            if re.search(r"[A-Za-zÀ-ỹ]", child):
                break
        if year_vals:
            emit(label, year_vals.get(current_year), year_vals.get(previous_year),
                 _section_from_label(label, section), code, None, abs_line,
                 "CF_YEAR_VALUE_CHILDREN", raw_text=_join_raw_text(raw, *child_raw_lines))
        elif nums:
            emit(label, nums[0], nums[1] if len(nums) > 1 else None,
                 _section_from_label(label, section), code, None, abs_line,
                 "CF_POSITIONAL_VALUE_CHILDREN", raw_text=_join_raw_text(raw, *child_raw_lines))

        # Trong bảng tách theo cột, lượt dòng con theo vị trí có thể nhầm token số
    # đầu tiên của block giá trị thành cặp con dưới nhãn cuối. Bộ thu cấu trúc
    # đáng tin cậy hơn; bỏ artifact fallback này nhưng giữ observation pipe theo dòng.
    if column_major_layout.get("detected"):
        rows = [row for row in rows if row.pattern != "CF_POSITIONAL_VALUE_CHILDREN"]

    # Loại trùng/gộp các observation bổ sung từ những bộ thu chồng lấn. Các
    # mã nhánh thập phân như 101.1 và 103.1 là hai dòng luật định khác nhau dù
    # cùng nhãn ``Tiền``; giữ mã nhánh trong khóa để không gộp mất child.
    merged = {}
    order = []
    for r in rows:
        # Định danh cấu trúc là nhãn + section + phương pháp. Mã báo cáo và
        # tham chiếu thuyết minh chỉ là provenance, không bao giờ là khóa gộp.
        # Riêng mã nhánh dạng 101.1/103.1 là identity của dòng con trong cùng
        # bảng và cần được giữ để tránh gộp hai dòng cùng tên.
        raw_code = strip_md(r.statement_code or r.code)
        branch_code = (
            raw_code
            if preserve_decimal_branch_rows and re.fullmatch(r"\d+\.\d+", raw_code)
            else ""
        )
        key = (fold(r.source_label), r.section or "", r.method or "", branch_code)
        if key not in merged:
            merged[key] = r; order.append(key); continue
        old = merged[key]
        def recovery_priority(pattern: Optional[str]) -> int:
            value = pattern or ""
            if "CF_DETACHED_PERIOD_TABLE" in value:
                return 40
            if "CF_COLUMN_MAJOR_STRUCTURAL" in value:
                return 40
            if "CF_VALUE_BEFORE_LABEL" in value:
                return 35
            if "CF_PERIOD_CHILDREN" in value:
                return 10
            return 20

        if recovery_priority(r.pattern) > recovery_priority(old.pattern):
            merged[key] = r
            old, r = r, old
        if old.current is None and r.current is not None:
            old.current = r.current
        if old.previous is None and r.previous is not None:
            old.previous = r.previous
        if old.code is None and r.code is not None:
            old.code = r.code
            old.statement_code = r.statement_code or r.code
        if old.note is None and r.note is not None:
            old.note = r.note
            old.note_ref = r.note_ref or r.note
        if not old.raw_text and r.raw_text:
            old.raw_text = r.raw_text
        # Khôi phục block kỳ lặp. Một số chuyển đổi LLM phát ra hai block đầy đủ
        # các dòng `nhãn: giá trị` nhưng làm mất/gán sai header kỳ thứ hai. Nếu
        # cùng dòng semantic xuất hiện lại đủ xa với một giá trị hiện tại khác,
        # xem occurrence thứ hai là kỳ trước thay vì bỏ đi. Cố ý loại occurrence
        # chồng lấn từ cùng một dòng nguồn.
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

    # B03 trước đây chỉ giữ label/value, làm mất bằng chứng row đang là child
    # hay sibling. Khôi phục parent/path từ indent trên source gốc sau dedupe;
    # đây là provenance, không phải một phép đoán mapping mới.
    attach_hierarchy_context(dedup, source_scoped_lines, s + 1)

    unit_ctx = detect_statement_unit("\n".join(scoped_lines), fallback_unit=fallback_unit)
    for r in dedup:
        u = row_unit_override(r.source_label, unit_ctx)
        r.unit = u.unit

    patterns = sorted({r.pattern for r in dedup if r.pattern})
    row_dicts = [r.to_dict() for r in dedup]
    if row_scan_mode == "assist" and row_block_scan:
        attach_row_block_evidence(row_dicts, row_block_scan)
    return {**scope, "rows": row_dicts, "method": method, "method_method": method_method,
            "sector": sector, "sector_method": sector_method,
            "unit": unit_ctx.unit, "unit_source": unit_ctx.source,
            "row_block_scan": row_block_scan,
            "column_major_layout": {
                **{k: v for k, v in column_major_layout.items() if k != "rows"},
                "rows_recovered": len(column_major_layout.get("rows") or []),
            },
            "value_before_label_layout": {
                **{k: v for k, v in value_before_label_layout.items() if k != "rows"},
                "rows_recovered": len(value_before_label_layout.get("rows") or []),
            },
            "patterns": patterns}
