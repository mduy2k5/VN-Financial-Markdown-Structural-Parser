from __future__ import annotations

import re
from typing import Any, Optional

try:
    from src.common.report_period import resolve_report_years
except ImportError:
    from common.report_period import resolve_report_years

HEADING_RE = re.compile(
    r"(?i)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:BÁO CÁO|BẢNG)\s+KẾT QUẢ\s+HOẠT ĐỘNG(?:\s+KINH DOANH)?(?:\s+HỢP NHẤT|\s+TỔNG HỢP)?"
)
STOP_RE = re.compile(
    r"(?i)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:BÁO CÁO|BẢNG)\s+(?:"
    r"LƯU\s+CHUY[EỂÊ]N\s+TI[EỀÊ]N\s+T[EỆE]|"
    r"TÌNH\s+HÌNH\s+TÀI\s+CHÍNH|"
    r"CÂN\s+ĐỐI\s+KẾ\s+TOÁN"
    r")"
)
STOP_FORM_RE = re.compile(r"(?i)\bB\s*0?3(?:a|b)?\s*[-–/]?\s*CTCK\b")
SUPPLEMENT_RE = re.compile(r"(?i)(THÔNG TIN BỔ SUNG|THUYẾT MINH).*(BÁO CÁO KẾT QUẢ)")
NUM_RE = re.compile(
    r"^\(?-?[\d][\d.,]*\)?(?:\s*(?:triệu\s*(?:đồng|vnd)|nghìn\s*(?:đồng|vnd)|đồng|vnd|đồng/cổ\s*phiếu|vnd/cổ\s*phiếu))?$",
    re.I,
)
FORM_CODE_RE = re.compile(r"(?i)\b(?:B\s*0?2\s*[-–]?\s*DN(?:/HN)?|B\s*0?3a?\s*/\s*TCTD(?:-HN)?|B\s*0?2\s*[-–]?\s*CTCK)\b")
TOC_HINT_RE = re.compile(r"(?i)(?:\(Trang\s*\d|\bTrang\s*\d|\|\s*\d+(?:-\d+)?\s*$|:\s*\d+(?:-\d+)?\s*$)")


def strip_md(s: Any) -> str:
    s = "" if s is None else str(s)
    s = s.strip()
    s = re.sub(r"^[-*+]+\s*", "", s)
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(":").strip()


def clean_value(s: Any) -> Optional[str]:
    s = strip_md(s)
    s = re.sub(
        r"\s+(?:triệu\s*(?:đồng|vnd)|nghìn\s*(?:đồng|vnd)|đồng|vnd|đồng/cổ\s*phiếu|vnd/cổ\s*phiếu)$",
        "",
        s,
        flags=re.I,
    ).strip()
    if not s:
        return None
    if s in {"-", "–", "—"}:
        return "-"
    return s if NUM_RE.match(s) else None


def _period_role_and_priority(label: str, current_year: int, previous_year: int):
    """Trả về ``(role, priority)``. Priority cao hơn được ưu tiên.

    Với báo cáo năm, nhãn năm/hiện tại rõ có priority 20. Với bố cục B03a quý,
    giá trị lũy kế có priority 30, cao hơn giá trị quý.
    """
    f = strip_md(label).casefold()
    f = re.sub(r"\([^)]*\)", " ", f)
    f = re.sub(r"\s+", " ", f).strip()
    cumulative = any(x in f for x in ("lũy kế", "luỹ kế", "luy ke", "từ đầu năm", "tu dau nam"))
    if cumulative:
        # Nhãn lũy kế so sánh thường vẫn chứa cụm chung "cuối quý" (ví dụ
        # "Luỹ kế ... đến cuối quý trước"). Giải quyết cue so sánh rõ trước để
        # không nhầm thành cột lũy kế hiện tại chỉ vì có cụm từ này.
        if str(previous_year) in f or "năm trước" in f or "ky truoc" in f or "kỳ trước" in f or "quý trước" in f:
            return "previous", 30
        if str(current_year) in f or "năm nay" in f or "ky nay" in f or "kỳ này" in f or "cuối quý" in f:
            return "current", 30
    if str(current_year) in f or "năm nay" in f:
        return "current", 20
    if str(previous_year) in f or "năm trước" in f:
        return "previous", 20
    if "kỳ này" in f or "ky nay" in f:
        return "current", 10
    if "kỳ trước" in f or "ky truoc" in f:
        return "previous", 10
    return None, 0


def parse_period_line(text: str, current_year: int, previous_year: int):
    """Đọc thuộc tính kỳ như:
      Năm nay: 1.000
      Năm trước (Trình bày lại): 900
      Năm 2025 (Triệu đồng): 1.000
      2024 (VND): 900
      Giá trị 2025: ...
      Lũy kế từ đầu năm Năm nay: ...
    """
    t = strip_md(text)
    m = re.match(r"^(.{1,100}?)\s*:\s*(.+)$", t)
    if not m:
        return None
    key, raw = m.group(1).strip(), m.group(2).strip()
    role, priority = _period_role_and_priority(key, current_year, previous_year)
    if not role:
        return None
    v = clean_value(raw)
    if v is None:
        return None
    return role, priority, v


def _candidate_score(lines: list[str], i: int, current_year: int, previous_year: int) -> int:
    head = strip_md(lines[i])
    if SUPPLEMENT_RE.search(head):
        return -10000
    if TOC_HINT_RE.search(head):
        return -5000

    chunk_lines = lines[i:min(len(lines), i + 190)]
    chunk = "\n".join(chunk_lines)
    low = chunk.casefold()
    hlow = head.casefold()
    score = 30

    # Ưu tiên năm báo cáo được yêu cầu và loại heading thuyết minh/bảng của năm trước.
    if str(current_year) in hlow:
        score += 50
    if str(previous_year) in hlow and str(current_year) not in hlow:
        score -= 90

    form_hits = FORM_CODE_RE.findall(chunk)
    score += min(len(form_hits), 3) * 45

    period_lines = 0
    for l in chunk_lines:
        if parse_period_line(l, current_year, previous_year):
            period_lines += 1
    score += min(period_lines, 24) * 6

    # Dòng inline như "...: 100 (Năm nay), 90 (Năm trước)".
    score += min(len(re.findall(r"(?i)\(Năm\s+(?:nay|trước)\)", chunk)), 10) * 4

    for anchor in [
        "doanh thu bán hàng", "doanh thu thuần", "thu nhập lãi", "chi phí lãi",
        "lợi nhuận trước thuế", "lợi nhuận sau thuế", "giá vốn hàng bán"
    ]:
        if anchor in low:
            score += 10

    for token, w in [
        ("số liệu trước điều chỉnh", -12),
        ("các điều chỉnh", -10),
        ("số liệu sau điều chỉnh", -12),
        ("báo cáo kết quả hoạt động kinh doanh bộ phận", -80),
    ]:
        score += low.count(token) * w

    if "tiếp theo" in hlow:
        score -= 15
    return score


def _heading_candidates(lines: list[str], current_year: int, previous_year: int):
    out = []
    for i, line in enumerate(lines):
        head = strip_md(line)
        if HEADING_RE.search(head):
            out.append({"i": i, "score": _candidate_score(lines, i, current_year, previous_year), "head": head})
    return out


def _scope_end_for_candidate(lines: list[str], start: int, max_span: int = 560) -> int:
    """Trả về điểm kết thúc cấu trúc của một candidate B02.

    Hàm cố ý độc lập với việc chấm điểm candidate. Một entry mục lục thường
    giống heading B02 mạnh nhưng ngay sau đó là báo cáo chính kế tiếp. Đo span
    candidate giúp entry đó không thắng chỉ vì nằm sớm hơn trong tài liệu.
    """
    end = min(len(lines), start + max_span)
    for j in range(start + 1, min(len(lines), start + max_span)):
        clean_j = strip_md(lines[j])
        if STOP_RE.search(clean_j) or STOP_FORM_RE.search(clean_j):
            return j
        if j > start + 260 and HEADING_RE.search(clean_j) and "tiếp theo" not in clean_j.casefold():
            return j
    return end


def _find_notes_start(lines: list[str]) -> int | None:
    """Trả về điểm bắt đầu mạnh đầu tiên của section Notes.

    Xếp hạng candidate không được để thuyết minh dài nhiều số (phân tích doanh
    thu, bên liên quan, thuế hoãn lại, thông tin segment...) thắng báo cáo chính
    chỉ vì thuyết minh có nhiều dòng hơn.
    """
    for i, line in enumerate(lines):
        t = strip_md(line).casefold()
        # Heading có trọng số cao hơn văn xuôi chỉ nhắc đến Notes.
        if re.search(r"(?i)^\s*(?:thuyết minh|thuyet minh)\s+(?:báo cáo|bao cao)\s+tài chính", strip_md(line)):
            return i
        if re.search(r"(?i)\bB\s*0?9\s*[-–/]?\s*DN(?:/HN)?\b", strip_md(line)):
            # Mã biểu mẫu có thể nằm trong metadata; khi có thể phải yêu cầu
            # wording Notes ở gần.
            nearby = " ".join(strip_md(x).casefold() for x in lines[max(0, i-4):i+5])
            if "thuyết minh" in nearby or "thuyet minh" in nearby:
                return max(0, i-4)
    return None


def _candidate_viability(lines: list[str], cand: dict, current_year: int, previous_year: int, notes_start: int | None = None) -> dict:
    start = cand["i"]
    end = _scope_end_for_candidate(lines, start)
    span = max(0, end - start)
    chunk = lines[start:end]

    # Evidence cho thấy đây là thân báo cáo thật thay vì entry mục lục/index.
    numeric_rows = 0
    period_rows = 0
    table_rows = 0
    for line in chunk:
        if parse_period_line(line, current_year, previous_year):
            period_rows += 1
        if line.count("|") >= 2:
            table_rows += 1
        t = strip_md(line)
        if re.search(r"\d[\d.,]{2,}", t):
            numeric_rows += 1

    # Evidence mạnh của báo cáo chính. Notes có thể có hàng trăm số nhưng thường
    # không có tập anchor báo cáo theo luật định gọn như vậy.
    low_chunk = "\n".join(chunk).casefold()
    statement_anchor_hits = sum(1 for a in (
        "doanh thu thuần", "giá vốn hàng bán", "lợi nhuận gộp",
        "lợi nhuận trước thuế", "lợi nhuận sau thuế",
        "thu nhập lãi thuần", "chi phí dự phòng rủi ro tín dụng",
        "tổng doanh thu hoạt động", "kết quả hoạt động",
        "lợi nhuận (lỗ) gộp hoạt động kinh doanh bảo hiểm",
    ) if a in low_chunk)

    adjusted = cand["score"]
    # Cổng hồi quy chính: candidate mục lục thường kết thúc sau 1-3 dòng.
    if span < 8:
        adjusted -= 1000
    elif span < 15:
        adjusted -= 250

    # Khi section Notes theo luật định đã bắt đầu, heading giống B02 về sau gần
    # như chắc chắn là disclosure/note thay vì báo cáo chính. Đây là cổng hồi
    # quy cho report có Notes lặp lại heading giống B02.
    if notes_start is not None and start >= notes_start:
        adjusted -= 1400

    adjusted += statement_anchor_hits * 35

    # Scope rất dài thường là Notes/disclosure. Không cấm tuyệt đối, nhưng không
    # để mật độ số raw lấn át một báo cáo chính compact.
    if span > 320:
        adjusted -= min(500, (span - 320) * 2)

    # Thưởng evidence báo cáo thật mà không gắn với mã cổ phiếu.
    adjusted += min(period_rows, 12) * 3
    adjusted += min(table_rows, 8) * 2
    adjusted += min(numeric_rows, 20)

    x = dict(cand)
    x.update({
        "end": end,
        "span": span,
        "period_rows": period_rows,
        "table_rows": table_rows,
        "numeric_rows": numeric_rows,
        "statement_anchor_hits": statement_anchor_hits,
        "after_notes_start": bool(notes_start is not None and start >= notes_start),
        "adjusted_score": adjusted,
    })
    return x


def choose_income_scope(text: str, current_year: int | None = None, previous_year: int | None = None):
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
    raw = [c for c in _heading_candidates(lines, current_year, previous_year) if c["score"] > -1000]
    if not raw:
        return lines, 0, len(lines), -9999

    notes_start = _find_notes_start(lines)
    cands = [_candidate_viability(lines, c, current_year, previous_year, notes_start) for c in raw]
    viable = [c for c in cands if c["span"] >= 8 and c["adjusted_score"] > -500]
    pool = viable or cands

    # Chọn theo evidence cấu trúc trước. Vị trí sớm chỉ là tie-breaker; không bao
    # giờ được lấn át candidate muộn hơn có thân báo cáo thật.
    best = max(pool, key=lambda c: (c["adjusted_score"], c["span"], -c["i"]))

    # Nếu candidate tốt nhất là trang tiếp nối, ưu tiên heading báo cáo chính khả
    # dụng ở gần để scope lấy được cả hai trang.
    if "tiếp theo" in best["head"].casefold():
        prev = [
            c for c in viable
            if c["i"] < best["i"]
            and best["i"] - c["i"] <= 260
            and "tiếp theo" not in c["head"].casefold()
        ]
        if prev:
            best = max(prev, key=lambda c: (c["adjusted_score"], c["span"], -c["i"]))

    start = best["i"]
    end = best.get("end", _scope_end_for_candidate(lines, start))
    return lines, start, end, best["adjusted_score"]
