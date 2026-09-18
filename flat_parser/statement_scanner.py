from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Iterable

from .models import SourceLine
from .textnorm import fold
from .context import find_validated_financial_position_start, find_validated_financial_position_end


STATEMENT_FINANCIAL_POSITION = "FINANCIAL_POSITION"
STATEMENT_OFF_BALANCE = "OFF_BALANCE"
STATEMENT_INCOME = "INCOME_STATEMENT"
STATEMENT_CASH_FLOW = "CASH_FLOW"
STATEMENT_NOTES = "NOTES"


TITLE_PATTERNS = {
    STATEMENT_FINANCIAL_POSITION: (
        "bao cao tinh hinh tai chinh",
        "bang can doi ke toan",
    ),
    STATEMENT_OFF_BALANCE: (
        "cac chi tieu ngoai bao cao tinh hinh tai chinh",
        "cac chi tieu ngoai bang can doi ke toan",
        "cac khoan muc ngoai bang",
        "chi tieu ngoai bang",
    ),
    STATEMENT_INCOME: (
        "bao cao ket qua hoat dong kinh doanh",
        "bao cao ket qua hoat dong",
        "bao cao ket qua kinh doanh",
    ),
    STATEMENT_CASH_FLOW: (
        "bao cao luu chuyen tien te",
    ),
    STATEMENT_NOTES: (
        "thuyet minh bao cao tai chinh",
        "ban thuyet minh bao cao tai chinh",
        "thuyet minh bctc",
    ),
}

OFF_BALANCE_ANCHORS = (
    "bao lanh vay von",
    "bao lanh von vay",
    "bao lanh khac",
    "cam ket giao dich hoi doai",
    "cam ket mua ngoai te",
    "cam ket ban ngoai te",
    "cam ket giao dich hoan doi",
    "cam ket trong nghiep vu l/c",
    "cam ket trong nghiep vu thu tin dung",
    "cam ket cho vay khong huy ngang",
    "cac cam ket khac",
    "cam ket khac",
    "lai cho vay va phi phai thu chua thu duoc",
    "no kho doi da xu ly",
    "tai san va chung tu khac",
)

INCOME_ANCHORS = (
    "doanh thu ban hang",
    "doanh thu thuan",
    "loi nhuan gop",
    "loi nhuan thuan",
    "loi nhuan sau thue",
    "thu nhap lai va cac khoan thu nhap tuong tu",
    "chi phi lai va cac chi phi tuong tu",
    "thu nhap lai thuan",
    "lai co ban tren co phieu",
)

CASH_FLOW_ANCHORS = (
    "luu chuyen tien thuan tu hoat dong kinh doanh",
    "luu chuyen tien thuan tu hoat dong dau tu",
    "luu chuyen tien thuan tu hoat dong tai chinh",
    "tien va tuong duong tien dau ky",
    "tien va tuong duong tien cuoi ky",
    "tien thu tu ban hang",
    "khau hao tai san co dinh",
)

FP_ANCHORS = (
    "tai san",
    "tai san co",
    "no phai tra",
    "von chu so huu",
    "tong cong tai san",
    "tong tai san",
    "tong cong nguon von",
    "tong no phai tra va von chu so huu",
)


@dataclass
class StatementCandidate:
    statement_type: str
    line_no: int
    score: float
    evidence: list[str]
    text: str
    sector: str


@dataclass
class StatementRange:
    statement_type: str
    start_line: int
    end_line: int
    confidence: float
    evidence: list[str]
    sector: str
    resource_profile: str | None = None
    status: str = "detected"

    def as_dict(self):
        return asdict(self)


def detect_document_sector(lines: list[SourceLine]) -> dict:
    """Phân loại sector của đơn vị/báo cáo bằng evidence định danh có trọng số.

    Từ khóa sector xuất hiện ở bất kỳ đâu trong thuyết minh chỉ là bằng chứng yếu.
    Báo cáo tài chính thường nhắc ngân hàng, lưu ký chứng khoán và bảo hiểm như
    đối tác. Bằng chứng mạnh là mã biểu mẫu riêng của sector hoặc định danh đơn vị
    gần phần đầu tài liệu/phần mở đầu báo cáo đã kiểm toán.
    """
    front = "\n".join(x.clean for x in lines if x.clean and x.line_no <= 450)
    whole = "\n".join(x.clean for x in lines if x.clean)
    ff = fold(front)
    wf = fold(whole)

    scores = {"enterprise": 0.0, "bank": 0.0, "securities": 0.0, "insurance": 0.0}
    evidence = {k: [] for k in scores}

    def add(kind: str, pts: float, why: str):
        scores[kind] += pts
        evidence[kind].append(f"{why}:+{pts:g}")

    # Bằng chứng mạnh từ mã biểu mẫu riêng của sector.
    if re.search(r"\bb0[2-5](?:[a-z])?/tctd(?:-hn)?\b", ff):
        add("bank", 12, "front_tctd_form_code")
    elif re.search(r"\bb0[2-5](?:[a-z])?/tctd(?:-hn)?\b", wf):
        add("bank", 8, "tctd_form_code")

    if re.search(r"\bb0[1-4](?:[a-z])?[- ]ctck(?:/hn)?\b", ff):
        add("securities", 12, "front_ctck_form_code")
    elif re.search(r"\bb0[1-4](?:[a-z])?[- ]ctck(?:/hn)?\b", wf):
        add("securities", 8, "ctck_form_code")

    if re.search(r"\bb\s*0?[1-3](?:[ab])?\s*[-/]\s*dn(?:n|nklt)?\b", ff):
        add("enterprise", 10, "front_enterprise_form_code")

    # Định danh đơn vị ở phần đầu là bằng chứng mạnh; nhắc đối tác phía sau thì không.
    if any(tok in ff for tok in ("ngan hang thuong mai co phan", "ngan hang tmcp", "to chuc tin dung")):
        add("bank", 6, "front_bank_identity")
    if "cong ty co phan chung khoan" in ff or "cong ty chung khoan" in ff:
        add("securities", 7, "front_securities_identity")
    if any(tok in ff for tok in ("tap doan bao hiem", "cong ty bao hiem", "tong cong ty bao hiem")):
        add("insurance", 7, "front_insurance_identity")

    # Từ vựng kế toán đặc trưng chỉ là bằng chứng củng cố.
    bank_vocab = sum(1 for tok in (
        "tien gui cua khach hang", "cho vay khach hang", "tien gui tai ngan hang nha nuoc",
        "cac to chuc tin dung khac", "von cua to chuc tin dung",
    ) if tok in ff)
    if bank_vocab >= 2:
        add("bank", min(4, bank_vocab), f"bank_vocab_{bank_vocab}")

    sec_vocab = sum(1 for tok in (
        "tai san tai chinh fvtpl", "giao dich ky quy", "phai tra nha dau tu",
        "hoat dong moi gioi chung khoan",
    ) if tok in ff)
    if sec_vocab >= 2:
        add("securities", min(4, sec_vocab), f"securities_vocab_{sec_vocab}")

    ins_vocab = sum(1 for tok in ("tai bao hiem", "du phong toan hoc", "du phong boi thuong") if tok in ff)
    if ins_vocab >= 2:
        add("insurance", min(4, ins_vocab), f"insurance_vocab_{ins_vocab}")

    # Một lần nhắc trong toàn tài liệu như VSDC hay 'ngân hàng thương mại' cố ý
    # không đủ để chuyển sector.
    if "vsdc" in wf:
        add("securities", 0.5, "whole_vsdc_weak")
    if "ngan hang thuong mai" in wf:
        add("bank", 0.5, "whole_bank_mention_weak")

    best_kind, best_score = max(scores.items(), key=lambda kv: kv[1])
    ordered = sorted(scores.values(), reverse=True)
    margin = best_score - (ordered[1] if len(ordered) > 1 else 0)

    # Khi không có bằng chứng định danh mạnh, mặc định là enterprise thay vì
    # phân loại nhầm công ty thường vì phần thuyết minh có nhắc ngân hàng.
    if best_score < 5:
        best_kind = "enterprise"
        confidence = 0.70
        evidence[best_kind].append("default_enterprise:no_strong_sector_identity")
    else:
        confidence = min(0.995, 0.78 + best_score / 60 + max(0, margin) / 100)

    return {
        "sector": best_kind,
        "confidence": round(confidence, 4),
        "evidence": evidence[best_kind][:10],
        "scores": {k: round(v, 3) for k, v in scores.items()},
    }


def _nearby(lines: list[SourceLine], line_no: int, before: int = 8, after: int = 40):
    return [x for x in lines if line_no - before <= x.line_no <= line_no + after]


def _title_type(text: str) -> str | None:
    f = fold(text or "").strip(" *#:_-")
    # tiêu đề metadata rõ ràng
    for prefix in ("tieu de ", "ten bao cao ", "report title "):
        if f.startswith(prefix):
            f = f[len(prefix):].strip(" :")
            break
    for kind, patterns in TITLE_PATTERNS.items():
        if any(f.startswith(p) for p in patterns):
            return kind
    return None


def _toc_penalty(lines: list[SourceLine], line_no: int) -> tuple[float, list[str]]:
    win = _nearby(lines, line_no, before=8, after=8)
    if any("muc luc" in fold(x.clean or "") for x in win):
        return -8.0, ["near_toc:-8"]
    if any(re.fullmatch(r"\s*\d+\s*[-–]\s*\d+\s*", x.clean or "") for x in win):
        return -2.0, ["near_page_range:-2"]
    return 0.0, []


def _numeric_shape_score(lines: list[SourceLine], line_no: int, lookahead: int = 80) -> tuple[float, list[str]]:
    win = [x for x in lines if line_no <= x.line_no <= line_no + lookahead]
    two_value_rows = 0
    period_headers = 0
    for x in win:
        c = x.clean or ""
        f = fold(c)
        if "so cuoi" in f or "so dau" in f or re.search(r"\b20\d{2}\b", c):
            period_headers += 1
        if "|" in c and len(re.findall(r"(?:\(?-?\d[\d., ]*\)?|[-–—−])", c)) >= 2:
            two_value_rows += 1
        elif len(re.findall(r"(?:\(?-?\d[\d., ]*\)?|[-–—−])", c)) >= 2:
            two_value_rows += 1
    score = min(two_value_rows, 6) * 0.6 + min(period_headers, 4) * 0.5
    ev = []
    if two_value_rows:
        ev.append(f"numeric_rows:{two_value_rows}")
    if period_headers:
        ev.append(f"period_headers:{period_headers}")
    return score, ev


def _anchor_score(lines: list[SourceLine], line_no: int, anchors: Iterable[str], lookahead: int = 100) -> tuple[float, list[str]]:
    win = [fold(x.clean or "") for x in lines if line_no <= x.line_no <= line_no + lookahead]
    hit = []
    for a in anchors:
        if any(a in x for x in win):
            hit.append(a)
    score = min(len(hit), 8) * 1.25
    return score, ([f"anchor_hits:{len(hit)}"] if hit else [])


def _form_code_hint(lines: list[SourceLine], line_no: int, sector: str) -> tuple[str | None, float, list[str]]:
    win = _nearby(lines, line_no, before=5, after=12)
    raw = " ".join(x.clean or "" for x in win)
    f = fold(raw)

    # Mã biểu mẫu riêng của sector. Mã chỉ là evidence, không bao giờ là sự thật duy nhất.
    mappings = []
    if sector == "bank":
        mappings = [
            (r"\bb02(?:[a-z])?/tctd(?:-hn)?\b", STATEMENT_FINANCIAL_POSITION),
            (r"\bb03(?:[a-z])?/tctd(?:-hn)?\b", STATEMENT_INCOME),
            (r"\bb04(?:[a-z])?/tctd(?:-hn)?\b", STATEMENT_CASH_FLOW),
            (r"\bb05(?:[a-z])?/tctd(?:-hn)?\b", STATEMENT_NOTES),
        ]
    elif sector == "securities":
        mappings = [
            (r"\bb01(?:[a-z])?[- ]ctck(?:/hn)?\b", STATEMENT_FINANCIAL_POSITION),
            (r"\bb02(?:[a-z])?[- ]ctck(?:/hn)?\b", STATEMENT_INCOME),
            (r"\bb03(?:[a-z])?[- ]ctck(?:/hn)?\b", STATEMENT_CASH_FLOW),
        ]
    else:
        mappings = [
            (r"\bb\s*0?1(?:[ab])?\s*[-/]\s*dn(?:n|nklt)?\b", STATEMENT_FINANCIAL_POSITION),
            (r"\bb\s*0?2(?:[ab])?\s*[-/]\s*dn(?:n)?\b", STATEMENT_INCOME),
            (r"\bb\s*0?3(?:[ab])?\s*[-/]\s*dn(?:n)?\b", STATEMENT_CASH_FLOW),
            (r"\bb\s*0?9(?:[ab])?\s*[-/]\s*dn(?:n|nklt)?\b", STATEMENT_NOTES),
        ]

    for pat, kind in mappings:
        if re.search(pat, f, flags=re.I):
            return kind, 2.5, [f"sector_form_code:{kind}:+2.5"]
    return None, 0.0, []



def _looks_like_toc_entry(lines: list[SourceLine], line: SourceLine) -> bool:
    f = fold(line.clean or "")
    win = _nearby(lines, line.line_no, before=8, after=3)
    near_toc = any("muc luc" in fold(x.clean or "") for x in win)
    trailing_pages = bool(re.search(r"\b\d+\s*[-–]\s*\d+\s*$", line.clean or ""))
    trailing_page = bool(re.search(r"\s+\d+\s*$", line.clean or ""))
    near_reporting_date = any(
        "tai ngay" in fold(x.clean or "") or re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b", x.clean or "")
        for x in _nearby(lines, line.line_no, before=0, after=3)
    )
    return near_toc and (trailing_pages or trailing_page) and not near_reporting_date

def _looks_like_statement_reference_entry(lines: list[SourceLine], line: SourceLine) -> bool:
    """Loại tham chiếu mục lục/đầu báo cáo bắt đầu bằng tên báo cáo.

    Ví dụ bị loại:
      Báo cáo tình hình tài chính (Mẫu B02/TCTD...) ...
      Bảng cân đối kế toán hợp nhất: Trang 06-09
      Báo cáo lưu chuyển tiền tệ - Trang 10-11
    """
    f = fold(line.clean or "")
    reference_markers = (
        "mau b0", "mau so b0", "ban hanh theo thong tu", "trang ",
    )
    if any(x in f for x in reference_markers):
        return True
    if re.search(r"\btrang\s*\d+(?:\s*[-–]\s*\d+)?\s*$", f):
        return True
    if re.search(r"[:\-]\s*\d+\s*[-–]\s*\d+\s*$", f):
        return True
    return False

def _score_title_candidate(lines: list[SourceLine], line: SourceLine, kind: str, sector: str) -> StatementCandidate:
    score = 5.0
    evidence = ["statement_title:+5"]
    p, ev = _toc_penalty(lines, line.line_no)
    score += p; evidence.extend(ev)
    form_kind, form_score, form_ev = _form_code_hint(lines, line.line_no, sector)
    if form_kind == kind:
        score += form_score; evidence.extend(form_ev)
    elif form_kind is not None and form_kind != kind:
        score -= 2.0; evidence.append(f"conflicting_form_code:{form_kind}:-2")

    if kind == STATEMENT_FINANCIAL_POSITION:
        a, e = _anchor_score(lines, line.line_no, FP_ANCHORS)
    elif kind == STATEMENT_OFF_BALANCE:
        a, e = _anchor_score(lines, line.line_no, OFF_BALANCE_ANCHORS, 70)
    elif kind == STATEMENT_INCOME:
        a, e = _anchor_score(lines, line.line_no, INCOME_ANCHORS)
    elif kind == STATEMENT_CASH_FLOW:
        a, e = _anchor_score(lines, line.line_no, CASH_FLOW_ANCHORS)
    else:
        a, e = (0.0, [])
    score += a; evidence.extend(e)

    n, ne = _numeric_shape_score(lines, line.line_no)
    if kind != STATEMENT_NOTES:
        score += n; evidence.extend(ne)
    if line.heading_level > 0:
        score += 0.5; evidence.append("markdown_heading:+0.5")
    return StatementCandidate(kind, line.line_no, score, evidence, line.clean, sector)


def _off_balance_fallback(lines: list[SourceLine], sector: str) -> StatementCandidate | None:
    if sector != "bank":
        return None
    # Yêu cầu cluster semantic dày; một lần nhắc trong văn xuôi chung là chưa đủ.
    best = None
    for i, line in enumerate(lines):
        f = fold(line.clean or "")
        if not any(a in f for a in OFF_BALANCE_ANCHORS):
            continue
        win = lines[i:i + 55]
        present = {a for a in OFF_BALANCE_ANCHORS if any(a in fold(x.clean or "") for x in win)}
        if len(present) < 4:
            continue
        nscore, nev = _numeric_shape_score(lines, line.line_no, 55)
        score = 3.0 + min(len(present), 8) * 1.2 + nscore
        cand = StatementCandidate(
            STATEMENT_OFF_BALANCE,
            line.line_no,
            score,
            ["dense_off_balance_signature:+3", f"anchor_hits:{len(present)}"] + nev,
            line.clean,
            sector,
        )
        if best is None or cand.score > best.score:
            best = cand
    return best


def scan_statements(lines: list[SourceLine]) -> dict:
    """Nhận diện phạm vi báo cáo bằng phân loại nhiều tín hiệu.

    Thứ tự ưu tiên:
      1. tiêu đề báo cáo đã xác thực;
      2. mã biểu mẫu theo sector làm evidence hỗ trợ;
      3. chữ ký semantic và hình dạng bảng riêng cho báo cáo;
      4. fallback thận trọng cho báo cáo tình hình tài chính/ngoại bảng ngân hàng.

    Scanner cố ý không dùng catalog alias canonical để nhận diện phạm vi. Điều
    này ngăn một alias pack lớn mở scope trong văn xuôi thuyết minh chỉ vì có
    nhắc đến một thuật ngữ nghiệp vụ.
    """
    sector_info = detect_document_sector(lines)
    sector = sector_info["sector"]

    candidates: list[StatementCandidate] = []
    for line in lines:
        if not line.clean:
            continue
        kind = _title_type(line.clean)
        if (
            kind
            and not _looks_like_toc_entry(lines, line)
            and not _looks_like_statement_reference_entry(lines, line)
        ):
            candidates.append(_score_title_candidate(lines, line, kind, sector))

    # Dùng lại bộ nhận diện điểm bắt đầu FP v0.4.14 đã được regression test kỹ
    # làm anchor FINANCIAL_POSITION chính. Nó đã tích lũy xử lý mục lục, trang
    # tiếp nối và khôi phục root dày qua bộ báo cáo B02.
    fp_start, fp_debug = find_validated_financial_position_start(lines)
    if fp_start is not None:
        candidates = [c for c in candidates if c.statement_type != STATEMENT_FINANCIAL_POSITION]
        candidates.append(StatementCandidate(
            STATEMENT_FINANCIAL_POSITION,
            fp_start,
            12.0,
            ["legacy_validated_fp_start_authoritative:+12"],
            next((x.clean for x in lines if x.line_no == fp_start), ""),
            sector,
        ))

    ob = _off_balance_fallback(lines, sector)
    if ob and not any(c.statement_type == STATEMENT_OFF_BALANCE and abs(c.line_no - ob.line_no) <= 2 for c in candidates):
        candidates.append(ob)

    # Chỉ giữ candidate đáng tin. Notes cần tiêu đề; loại khác cần >=5 sau phạt mục lục.
    candidates = [c for c in candidates if c.score >= (4.5 if c.statement_type != STATEMENT_NOTES else 4.0)]
    candidates.sort(key=lambda c: (c.line_no, -c.score))

    # Gộp tiêu đề trùng/lặp của cùng loại khi nằm gần nhau.
    collapsed: list[StatementCandidate] = []
    for c in candidates:
        if collapsed and c.statement_type == collapsed[-1].statement_type and c.line_no - collapsed[-1].line_no <= 12:
            if c.score > collapsed[-1].score:
                collapsed[-1] = c
            continue
        collapsed.append(c)
    candidates = collapsed

    ranges: list[StatementRange] = []
    max_line = lines[-1].line_no if lines else 1
    for i, c in enumerate(candidates):
        next_different = None
        for nxt in candidates[i + 1:]:
            if nxt.statement_type != c.statement_type:
                next_different = nxt
                break
        end = (next_different.line_no - 1) if next_different else max_line

        # FP phải dừng trước substatement OFF_BALANCE đã nhận diện.
        if c.statement_type == STATEMENT_FINANCIAL_POSITION:
            ob_after = next((x for x in candidates if x.statement_type == STATEMENT_OFF_BALANCE and c.line_no < x.line_no <= end), None)
            if ob_after:
                end = ob_after.line_no - 1
            else:
                # Giữ end legacy đã xác thực nếu nó sớm hơn và đáng tin.
                legacy_end = find_validated_financial_position_end(lines, c.line_no)
                if legacy_end >= c.line_no:
                    end = min(end, legacy_end)

        confidence = max(0.0, min(0.999, 0.45 + c.score / 20.0))
        profile = None
        status = "detected"
        if c.statement_type == STATEMENT_FINANCIAL_POSITION:
            profile = "financial_position"
        elif c.statement_type == STATEMENT_OFF_BALANCE:
            if sector == "bank":
                profile = "off_balance_bank"
            else:
                profile = f"off_balance_{sector}_unavailable"
                status = "resource_unavailable"
        ranges.append(StatementRange(
            c.statement_type, c.line_no, max(c.line_no, end), confidence,
            c.evidence, sector, profile, status,
        ))

    # Giữ range tốt nhất cho mỗi loại lõi được hỗ trợ; tiêu đề tiếp nối lặp thuộc cùng báo cáo.
    best_by_type: dict[str, StatementRange] = {}
    for r in ranges:
        prev = best_by_type.get(r.statement_type)
        if prev is None or r.confidence > prev.confidence:
            best_by_type[r.statement_type] = r

    # Nếu range tốt nhất bắt đầu ở trang tiếp nối, ưu tiên range đáng tin sớm nhất cùng loại.
    final_ranges: list[StatementRange] = []
    for kind in (STATEMENT_FINANCIAL_POSITION, STATEMENT_OFF_BALANCE, STATEMENT_INCOME, STATEMENT_CASH_FLOW, STATEMENT_NOTES):
        same = [r for r in ranges if r.statement_type == kind]
        if not same:
            continue
        strong = [r for r in same if r.confidence >= 0.70]
        chosen = min(strong, key=lambda r: r.start_line) if strong else max(same, key=lambda r: r.confidence)
        final_ranges.append(chosen)

    final_ranges.sort(key=lambda r: r.start_line)
    return {
        "sector": sector_info,
        "ranges": [r.as_dict() for r in final_ranges],
        "candidates": [asdict(c) for c in candidates],
    }
