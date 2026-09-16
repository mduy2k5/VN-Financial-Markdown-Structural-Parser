from __future__ import annotations

import re
from typing import Any, Optional

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
    """Return (role, priority). Higher priority wins.

    For annual reports, explicit annual/current labels have priority 20.
    For quarterly B03a layouts, cumulative values have priority 30 over quarter values.
    """
    f = strip_md(label).casefold()
    f = re.sub(r"\([^)]*\)", " ", f)
    f = re.sub(r"\s+", " ", f).strip()
    cumulative = any(x in f for x in ("lũy kế", "luỹ kế", "luy ke", "từ đầu năm", "tu dau nam"))
    if cumulative:
        # A comparative cumulative label normally still contains the generic
        # phrase "cuối quý" (for example, "Luỹ kế ... đến cuối quý trước").
        # Resolve the explicit comparative cue first so it cannot be mistaken
        # for the current cumulative column merely because of that phrase.
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
    """Parse period attributes such as:
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

    # Favor the requested report year and reject a prior-year note/table heading.
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

    # Inline rows such as "...: 100 (Năm nay), 90 (Năm trước)".
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
    """Return the structural end of one income candidate.

    This is intentionally independent from candidate scoring.  A TOC entry often
    looks like a strong income heading but is followed immediately by the next
    primary statement.  Measuring the candidate span prevents such entries from
    winning merely because they occur earlier in the document.
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
    """Return the first strong start of the notes section.

    Candidate ranking must not allow a long numeric note (revenue breakdown,
    related parties, deferred tax, segment information, etc.) to beat the
    primary income statement merely because the note contains more rows.
    """
    for i, line in enumerate(lines):
        t = strip_md(line).casefold()
        # The heading is stronger than incidental prose mentioning notes.
        if re.search(r"(?i)^\s*(?:thuyết minh|thuyet minh)\s+(?:báo cáo|bao cao)\s+tài chính", strip_md(line)):
            return i
        if re.search(r"(?i)\bB\s*0?9\s*[-–/]?\s*DN(?:/HN)?\b", strip_md(line)):
            # B09 can occur in metadata; require nearby notes wording when possible.
            nearby = " ".join(strip_md(x).casefold() for x in lines[max(0, i-4):i+5])
            if "thuyết minh" in nearby or "thuyet minh" in nearby:
                return max(0, i-4)
    return None


def _candidate_viability(lines: list[str], cand: dict, current_year: int, previous_year: int, notes_start: int | None = None) -> dict:
    start = cand["i"]
    end = _scope_end_for_candidate(lines, start)
    span = max(0, end - start)
    chunk = lines[start:end]

    # Evidence that this is a real statement body rather than a TOC/index entry.
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

    # Strong primary-statement evidence. Notes can have hundreds of numbers but
    # normally do not contain this compact set of statutory statement anchors.
    low_chunk = "\n".join(chunk).casefold()
    statement_anchor_hits = sum(1 for a in (
        "doanh thu thuần", "giá vốn hàng bán", "lợi nhuận gộp",
        "lợi nhuận trước thuế", "lợi nhuận sau thuế",
        "thu nhập lãi thuần", "chi phí dự phòng rủi ro tín dụng",
        "tổng doanh thu hoạt động", "kết quả hoạt động",
        "lợi nhuận (lỗ) gộp hoạt động kinh doanh bảo hiểm",
    ) if a in low_chunk)

    adjusted = cand["score"]
    # The primary regression guard: TOC candidates typically terminate in 1-3 lines.
    if span < 8:
        adjusted -= 1000
    elif span < 15:
        adjusted -= 250

    # Once the statutory notes section has started, a later income-like heading
    # is overwhelmingly likely to be a disclosure/note rather than the primary
    # statement. This is the v6 regression guard for BSR/VIC-like documents.
    if notes_start is not None and start >= notes_start:
        adjusted -= 1400

    adjusted += statement_anchor_hits * 35

    # Very long scopes are usually notes/disclosures. Do not ban them outright,
    # but stop raw numeric density from dominating a compact primary statement.
    if span > 320:
        adjusted -= min(500, (span - 320) * 2)

    # Reward actual statement evidence without making it ticker-specific.
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


def choose_income_scope(text: str, current_year: int = 2025, previous_year: int = 2024):
    lines = text.splitlines()
    raw = [c for c in _heading_candidates(lines, current_year, previous_year) if c["score"] > -1000]
    if not raw:
        return lines, 0, len(lines), -9999

    notes_start = _find_notes_start(lines)
    cands = [_candidate_viability(lines, c, current_year, previous_year, notes_start) for c in raw]
    viable = [c for c in cands if c["span"] >= 8 and c["adjusted_score"] > -500]
    pool = viable or cands

    # Choose by structural evidence first.  Earlier position is only a tie-breaker;
    # it must never override a later candidate with a real statement body.
    best = max(pool, key=lambda c: (c["adjusted_score"], c["span"], -c["i"]))

    # If best is a continuation, prefer a nearby viable primary heading so both
    # pages are captured in one scope.
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
