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
# Strong statutory form stop. OCR often corrupts the cash-flow heading but keeps B03-CTCK/B03b-CTCK.
STOP_FORM_RE = re.compile(r"(?i)\bB\s*0?3(?:a|b)?\s*[-–/]?\s*CTCK\b")
SUPPLEMENT_RE = re.compile(r"(?i)(THÔNG TIN BỔ SUNG|THUYẾT MINH).*(BÁO CÁO KẾT QUẢ)")
BULLET_RE = re.compile(r"^(\s*)[*+-]\s+(.*)$")
NUM_RE = re.compile(
    r"^\(?-?[\d][\d.,]*\)?(?:\s*(?:triệu\s*(?:đồng|vnd)|nghìn\s*(?:đồng|vnd)|đồng|vnd|đồng/cổ\s*phiếu|vnd/cổ\s*phiếu))?$",
    re.I,
)
NOTE_LIKE_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3})?|[IVXLC]+(?:\.\d+)?)$", re.I)
FORM_CODE_RE = re.compile(r"(?i)\b(?:B\s*0?2\s*[-–]?\s*DN(?:/HN)?|B\s*0?3a?\s*/\s*TCTD(?:-HN)?|B\s*0?2\s*[-–]?\s*CTCK)\b")
TOC_HINT_RE = re.compile(r"(?i)(?:\(Trang\s*\d|\bTrang\s*\d|\|\s*\d+(?:-\d+)?\s*$|:\s*\d+(?:-\d+)?\s*$)")

ENTERPRISE_CODES = {"01","02","10","11","20","21","22","23","24","25","26","30","31","32","40","50","51","52","60","61","62","70","71"}


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


def _bullet_info(line: str):
    m = BULLET_RE.match(line)
    if not m:
        return None
    return len(m.group(1)), strip_md(m.group(2))


def _strip_leading_index(label: str):
    label = strip_md(label)
    # Code | label tables serialized as bullets.
    mp = re.match(r"^(\d{1,3}|[IVXLC]+)\s*\|\s*(.+)$", label, re.I)
    if mp:
        lab = re.sub(r"^\d+[.)]\s*", "", mp.group(2)).strip()
        return lab, mp.group(1)
    m = re.match(r"^(?:(\d{1,3}|[IVXLC]+)[.)])\s+(.+)$", label, re.I)
    if m:
        return m.group(2).strip(), m.group(1)
    return label, None


def _row(indicator: str, current=None, previous=None, code=None, note=None, unit=None,
         pattern_id="INCOME_FALLBACK", line_no=None, raw_lines=None, confidence=0.99):
    return {
        "indicator": strip_md(indicator),
        "note": note or "",
        "code": code,
        "previous": previous,
        "current": current,
        "unit": unit,
        "pattern_id": pattern_id,
        "source_start_line": line_no,
        "source_end_line": line_no,
        "confidence": confidence,
        "raw_lines": raw_lines or [],
        "statement_scope": "INCOME_STATEMENT",
        "structural_confidence": confidence,
        "scope_confidence": confidence,
        "observation_confidence": confidence,
    }


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
        if str(current_year) in f or "năm nay" in f or "ky nay" in f or "kỳ này" in f or "cuối quý" in f:
            return "current", 30
        if str(previous_year) in f or "năm trước" in f or "ky truoc" in f or "kỳ trước" in f or "quý trước" in f:
            return "previous", 30
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


def extract_pipe_table(lines, start, end, current_year=2025, previous_year=2024):
    out = []
    header_period_order = None
    for i in range(start, end):
        line = lines[i]
        if line.count("|") < 2:
            continue
        cells = [strip_md(x) for x in line.strip().strip("|").split("|")]
        if len(cells) < 3 or set("".join(cells)) <= set("-: "):
            continue
        joined = " ".join(cells).casefold()
        if "chỉ tiêu" in joined or "năm nay" in joined or "năm trước" in joined or (str(current_year) in joined and str(previous_year) in joined):
            idx_cur = idx_prev = None
            for idx, c in enumerate(cells):
                role, _ = _period_role_and_priority(c, current_year, previous_year)
                if role == "current": idx_cur = idx
                elif role == "previous": idx_prev = idx
            if idx_cur is not None and idx_prev is not None:
                header_period_order = (idx_cur, idx_prev)
            continue
        label, code = _strip_leading_index(cells[0])
        if header_period_order and max(header_period_order) < len(cells):
            cur = clean_value(cells[header_period_order[0]])
            prev = clean_value(cells[header_period_order[1]])
        else:
            cur = clean_value(cells[-2]); prev = clean_value(cells[-1])
        if label and (cur is not None or prev is not None):
            out.append(_row(label, cur, prev, code=code, pattern_id="SP_INCOME_PIPE_TABLE", line_no=i+1, raw_lines=[line]))
    return out


def _parse_descendants(lines, i, end, current_year, previous_year):
    bi = _bullet_info(lines[i])
    if not bi:
        return None
    indent, raw_label = bi
    label, implicit_code = _strip_leading_index(raw_label)
    code = implicit_code
    note = None
    current = previous = None
    cur_prio = prev_prio = -1
    cur_indent = prev_indent = None
    raw = [lines[i]]
    child_label = None
    j = i + 1
    while j < end:
        bj = _bullet_info(lines[j])
        if bj:
            ind2, txt = bj
            if ind2 <= indent:
                break
            raw.append(lines[j])

            # Keyed row layout: Mã số -> Chỉ tiêu -> values.
            mm = re.match(r"(?i)^Mã\s*số\s*:\s*(.+)$", txt)
            if mm:
                code = strip_md(mm.group(1)); j += 1; continue
            ms = re.match(r"(?i)^STT\s*:\s*(.+)$", txt)
            if ms and not code:
                code = strip_md(ms.group(1)); j += 1; continue
            mc = re.match(r"(?i)^(?:CHỈ\s*TIÊU|Chỉ\s*tiêu|Diễn\s*giải)\s*:\s*(.+)$", txt)
            if mc:
                child_label = strip_md(mc.group(1)); j += 1; continue
            mn = re.match(r"(?i)^(?:Số\s*liệu\s*)?Thuyết\s*minh\s*:\s*(.*)$", txt)
            if mn:
                v = strip_md(mn.group(1))
                if v: note = v
                j += 1; continue

            pp = parse_period_line(txt, current_year, previous_year)
            if pp:
                role, prio, value = pp
                if role == "current" and (cur_indent is None or ind2 < cur_indent or (ind2 == cur_indent and prio >= cur_prio)):
                    current, cur_prio, cur_indent = value, prio, ind2
                elif role == "previous" and (prev_indent is None or ind2 < prev_indent or (ind2 == prev_indent and prio >= prev_prio)):
                    previous, prev_prio, prev_indent = value, prio, ind2
        j += 1

    # Parent itself may be a keyed field rather than semantic label.
    mparent_code = re.match(r"(?i)^Mã\s*số\s*:\s*(.+)$", label)
    mparent_stt = re.match(r"(?i)^STT\s*:\s*(.+)$", label)
    mparent_label = re.match(r"(?i)^(?:CHỈ\s*TIÊU|Chỉ\s*tiêu|Diễn\s*giải)\s*:\s*(.+)$", label)
    if mparent_code:
        code = strip_md(mparent_code.group(1))
        label = child_label or ""
    elif mparent_stt:
        if not code: code = strip_md(mparent_stt.group(1))
        label = child_label or ""
    elif mparent_label:
        label = strip_md(mparent_label.group(1))
    elif child_label:
        label = child_label

    return label, current, previous, code, note, raw


def extract_period_children(lines, start, end, current_year=2025, previous_year=2024):
    out = []
    for i in range(start, end):
        bi = _bullet_info(lines[i])
        if not bi:
            continue
        parsed = _parse_descendants(lines, i, end, current_year, previous_year)
        if not parsed:
            continue
        label, current, previous, code, note, raw = parsed
        label = strip_md(label)
        if not label or clean_value(label) is not None:
            continue
        if re.match(r"(?i)^(năm nay|năm trước|năm \d{4}|giá trị \d{4}|mã số|thuyết minh|stt|chỉ tiêu)$", label):
            continue
        if re.match(r"(?i)^tổng cộng(?:\s*\([^)]*\))?$", label):
            continue
        if current is not None or previous is not None:
            out.append(_row(label, current, previous, code, note, pattern_id="SP_INCOME_PERIOD_CHILDREN", line_no=i+1, raw_lines=raw))
    return out


def extract_positional_children(lines, start, end):
    """label -> [optional note] -> current -> previous."""
    out = []
    for i in range(start, end):
        bi = _bullet_info(lines[i])
        if not bi:
            continue
        indent, raw_label = bi
        label, code = _strip_leading_index(raw_label)
        if not label or clean_value(label) is not None:
            continue
        if label.casefold() in {"stt", "chỉ tiêu", "thuyết minh", "năm 2025", "năm 2024", "năm nay", "năm trước"}:
            continue
        children = []
        j = i + 1
        while j < end:
            bj = _bullet_info(lines[j])
            if not bj:
                j += 1; continue
            ind2, txt = bj
            if ind2 <= indent:
                break
            children.append((ind2, txt, lines[j])); j += 1
        if not children:
            continue
        min_indent = min(x[0] for x in children)
        direct = [x for x in children if x[0] == min_indent]
        vals, note = [], None
        for _, txt, _raw in direct:
            v = clean_value(txt)
            if v is not None:
                vals.append(v)
            elif note is None and NOTE_LIKE_RE.match(txt) and len(txt) <= 12:
                note = txt
        if len(vals) >= 2:
            out.append(_row(label, vals[-2], vals[-1], code=code, note=note,
                            pattern_id="SP_POSITIONAL_VALUE_CHILDREN", line_no=i+1,
                            raw_lines=[lines[i]] + [x[2] for x in direct]))
    return out


def extract_inline_period_rows(lines, start, end):
    """Rows like: **1. Thu nhập lãi:** 4.638.361 (Năm nay), 3.496.810 (Năm trước)"""
    out = []
    # OCR/Markdown serializers use comma, semicolon or a pipe between periods.
    # Accept optional currency/unit text after the numeric payload.
    pat = re.compile(
        r"^(.+?)\s*:\s*"
        r"(\(?-?[\d][\d.,]*\)?)\s*(?:đồng|vnd)?\s*\(Năm\s+nay\)"
        r"\s*(?:\||,|;|/)\s*"
        r"(\(?-?[\d][\d.,]*\)?)\s*(?:đồng|vnd)?\s*\(Năm\s+trước\)\s*$",
        re.I,
    )
    for i in range(start, end):
        bi = _bullet_info(lines[i])
        text = bi[1] if bi else strip_md(lines[i])
        m = pat.match(text)
        if not m:
            continue
        label, code = _strip_leading_index(m.group(1))
        cur, prev = clean_value(m.group(2)), clean_value(m.group(3))
        if label and (cur is not None or prev is not None):
            out.append(_row(label, cur, prev, code=code, pattern_id="SP_INCOME_INLINE_PERIODS", line_no=i+1, raw_lines=[lines[i]]))
    return out


def extract_heading_attribute_rows(lines, start, end, current_year=2025, previous_year=2024):
    """Non-bullet semantic heading followed by bullet attributes; common on continuation pages."""
    out = []
    for i in range(start, end):
        if _bullet_info(lines[i]):
            continue
        label = strip_md(lines[i])
        if not label or len(label) < 4 or HEADING_RE.search(label) or STOP_RE.search(label):
            continue
        if any(x in label.casefold() for x in ("mẫu b", "ban hành theo", "đơn vị", "cho năm", "phân bổ cho")):
            continue
        current = previous = code = note = None
        cur_prio = prev_prio = -1
        raw = [lines[i]]
        saw_attr = False
        for j in range(i+1, min(end, i+12)):
            bj = _bullet_info(lines[j])
            if not bj:
                if strip_md(lines[j]):
                    break
                continue
            txt = bj[1]; raw.append(lines[j]); saw_attr = True
            mm = re.match(r"(?i)^Mã\s*số\s*:\s*(.+)$", txt)
            if mm: code = strip_md(mm.group(1)); continue
            mn = re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.*)$", txt)
            if mn:
                v=strip_md(mn.group(1)); note=v or note; continue
            pp = parse_period_line(txt, current_year, previous_year)
            if pp:
                role, prio, value = pp
                if role=="current" and prio>=cur_prio: current,cur_prio=value,prio
                if role=="previous" and prio>=prev_prio: previous,prev_prio=value,prio
        if saw_attr and (current is not None or previous is not None):
            label2, implicit = _strip_leading_index(label)
            out.append(_row(label2, current, previous, code=code or implicit, note=note,
                            pattern_id="SP_INCOME_HEADING_ATTRIBUTES", line_no=i+1, raw_lines=raw))
    return out


def extract_plain_text_code_rows(lines, start, end):
    """Fallback for OCR/plain-text enterprise tables without bullets.

    Typical sequence:
      1.
      Doanh thu bán hàng và cung cấp
      dịch vụ
      01
      16.820...
      13.657...
    """
    out = []
    for i in range(start, end):
        code = strip_md(lines[i])
        if code not in ENTERPRISE_CODES:
            continue
        vals = []
        val_lines = []
        j = i + 1
        while j < min(end, i+7) and len(vals) < 2:
            v = clean_value(lines[j])
            if v is not None:
                vals.append(v); val_lines.append(lines[j])
            elif strip_md(lines[j]) and not re.match(r"(?i)^(thuyết|minh|năm nay|năm trước)$", strip_md(lines[j])):
                if len(vals)==0:
                    break
            j += 1
        if len(vals) < 2:
            continue
        # Build label from up to four previous non-header text lines.
        parts = []
        k = i - 1
        while k >= start and len(parts) < 4:
            t = strip_md(lines[k])
            if not t:
                if parts: break
                k -= 1; continue
            if re.fullmatch(r"\d+[.)]?", t) or re.match(r"(?i)^(chỉ tiêu|mã số|thuyết|minh|năm nay|năm trước)$", t):
                k -= 1; continue
            if clean_value(t) is not None or FORM_CODE_RE.search(t):
                break
            parts.append(t); k -= 1
        label = " ".join(reversed(parts)).strip()
        label = re.sub(r"^\d+[.)]\s*", "", label).strip()
        if 3 <= len(label) <= 220:
            out.append(_row(label, vals[0], vals[1], code=code,
                            pattern_id="SP_INCOME_PLAIN_TEXT_CODE", line_no=i+1,
                            raw_lines=list(reversed(parts)) + [lines[i]] + val_lines, confidence=0.93))
    return out


def extract_column_major(lines, start, end, current_year=2025, previous_year=2024):
    labels, codes, current, previous = [], [], [], []
    mode = None
    for i in range(start, end):
        t = strip_md(lines[i])
        m = re.match(r"^(?:[*+-]\s*)?(?:\*\*)?([0-9]{1,3}|[IVXLC]+)\.?\s*:\s*(.+)$", lines[i].strip(), re.I)
        if m and clean_value(m.group(2)) is None:
            labels.append(strip_md(m.group(2))); codes.append(m.group(1)); continue
        role, _ = _period_role_and_priority(t, current_year, previous_year)
        if role and clean_value(t) is None:
            mode = role; continue
        bi = _bullet_info(lines[i])
        val = clean_value(bi[1] if bi else t)
        if val is not None and mode:
            (current if mode == "current" else previous).append(val)
    if len(labels) < 3 or max(len(current), len(previous)) < max(3, len(labels)//2):
        return []
    n = min(len(labels), max(len(current), len(previous)))
    out = []
    for idx in range(n):
        cur = current[idx] if idx < len(current) else None
        prev = previous[idx] if idx < len(previous) else None
        if cur is not None or prev is not None:
            out.append(_row(labels[idx], cur, prev, code=codes[idx] if idx < len(codes) else None,
                            pattern_id="SP_INCOME_COLUMN_MAJOR", line_no=start+1, confidence=0.96))
    return out




def extract_code_led_mixed_rows(lines, start, end, current_year=2025, previous_year=2024):
    """Handle OCR blocks led by `Mã số`, with attributes and semantic label in mixed bullet/non-bullet lines.

    Example:
      Mã số: 02
      Thuyết minh: 32
      2025 (đồng): 360...
      2024 (đồng): 291...
      Các khoản giảm trừ doanh thu
    """
    out=[]
    code_re=re.compile(r"(?i)^Mã\s*số\s*:?\s*([0-9]{1,3}|[IVXLC]+)\s*$")
    i=start
    while i<end:
        t=strip_md(lines[i])
        m=code_re.match(t)
        if not m:
            i+=1; continue
        code=m.group(1); cur=prev=note=None; curp=prevp=-1; candidates=[]; raw=[lines[i]]
        j=i+1
        while j<min(end,i+18):
            tj=strip_md(lines[j])
            if code_re.match(tj): break
            if tj:
                raw.append(lines[j])
                mn=re.match(r"(?i)^Thuyết\s*minh\s*:?\s*(.*)$",tj)
                if mn:
                    nv=strip_md(mn.group(1)); note=nv or note; j+=1; continue
                pp=parse_period_line(tj,current_year,previous_year)
                if pp:
                    role,prio,val=pp
                    if role=='current' and prio>=curp: cur,curp=val,prio
                    if role=='previous' and prio>=prevp: prev,prevp=val,prio
                    j+=1; continue
                md=re.match(r"(?i)^Diễn\s*giải\s*:?\s*(.+)$",tj)
                if md:
                    candidates.append(strip_md(md.group(1))); j+=1; continue
                if not re.match(r"(?i)^(chỉ tiêu|stt|đơn vị|mẫu b|ban hành theo|năm báo cáo|năm nay|năm trước|giá trị\s+20\d{2})",tj) and clean_value(tj) is None:
                    # Ignore page metadata / separators / document metadata fields.
                    if (not tj.startswith('#')
                        and not re.match(r"(?i)^(page|metadata|content|category|created_at|updated_at|file_name|search_folder|s3_key|status|symbol|year|period)\s*:?", tj)
                        and not HEADING_RE.search(tj)
                        and not STOP_RE.search(tj)):
                        candidates.append(tj)
            j+=1
        if cur is not None or prev is not None:
            # Last semantic-looking candidate is usually the row label in this serialization.
            label=''
            for cand in reversed(candidates):
                c=strip_md(cand)
                if len(c)>=4 and not re.match(r"(?i)^(mã số|thuyết minh|20\d{2})",c):
                    label=c; break
            if label:
                out.append(_row(label,cur,prev,code=code,note=note,pattern_id='SP_INCOME_CODE_LED_MIXED',line_no=i+1,raw_lines=raw,confidence=0.97))
        i=max(i+1,j if j>i+1 else i+1)
    return out


def extract_year_section_rows(lines, start, end, current_year=2025, previous_year=2024):
    """Handle layouts split into one complete current-year section and one previous-year section.

    Example: **Năm báo cáo: 2025 (VND)** followed by rows with `Số liệu: ...`,
    then a matching 2024 section. Rows are joined by form code when available.
    """
    headers = []
    for i in range(start, end):
        t = strip_md(lines[i])
        m = re.search(r"(?i)^Năm\s+báo\s+cáo\s*:\s*(20\d{2})", t)
        if m:
            headers.append((i, int(m.group(1))))
    if not headers:
        return []
    sections = {}
    for pos, (hs, year) in enumerate(headers):
        he = headers[pos+1][0] if pos+1 < len(headers) else end
        if year not in {current_year, previous_year}:
            continue
        sec_rows = []
        for i in range(hs+1, he):
            bi = _bullet_info(lines[i])
            if not bi:
                continue
            indent, raw_label = bi
            label, implicit = _strip_leading_index(raw_label)
            if not label or clean_value(label) is not None:
                continue
            # Ignore field bullets.
            if re.match(r"(?i)^(mã số|thuyết minh|số liệu)\s*:", label):
                continue
            code = implicit; note = None; value = None; raw=[lines[i]]
            j=i+1
            while j < he:
                bj=_bullet_info(lines[j])
                if not bj: j+=1; continue
                ind2,txt=bj
                if ind2 <= indent: break
                raw.append(lines[j])
                mm=re.match(r"(?i)^Mã\s*số\s*:\s*(.+)$",txt)
                if mm: code=strip_md(mm.group(1))
                mn=re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.*)$",txt)
                if mn:
                    nv=strip_md(mn.group(1)); note=nv or note
                mv=re.match(r"(?i)^Số\s*liệu\s*:\s*(.+)$",txt)
                if mv:
                    vv=clean_value(mv.group(1))
                    if vv is not None: value=vv
                j+=1
            if value is not None:
                sec_rows.append({"label":label,"code":code,"note":note,"value":value,"line":i+1,"raw":raw})
        sections[year]=sec_rows
    if current_year not in sections and previous_year not in sections:
        return []
    merged={}
    for year, arr in sections.items():
        for x in arr:
            key=(str(x.get("code") or "").upper(), _norm_dedupe_label(x["label"]))
            z=merged.setdefault(key,{"label":x["label"],"code":x.get("code"),"note":x.get("note"),"current":None,"previous":None,"line":x["line"],"raw":[]})
            z["raw"] += x["raw"]
            if x.get("note") and not z.get("note"): z["note"]=x["note"]
            if year==current_year: z["current"]=x["value"]
            if year==previous_year: z["previous"]=x["value"]
    return [_row(z["label"],z["current"],z["previous"],code=z["code"],note=z["note"],pattern_id="SP_INCOME_YEAR_SECTIONS",line_no=z["line"],raw_lines=z["raw"]) for z in merged.values() if z["current"] is not None or z["previous"] is not None]


def extract_label_list_column_major(lines, start, end, current_year=2025, previous_year=2024):
    """Handle hierarchy/list of labels followed by separate `Năm 2025` and `Năm 2024` value lists."""
    cur_header = prev_header = None
    for i in range(start,end):
        t=strip_md(lines[i])
        role,_=_period_role_and_priority(t,current_year,previous_year)
        # Require a standalone year heading, not an attribute with a value.
        if role and ":" not in t and re.match(r"(?i)^(?:năm\s+(?:nay|trước|20\d{2})|20\d{2})$", t):
            if role=="current" and cur_header is None: cur_header=i
            elif role=="previous" and prev_header is None: prev_header=i
    if cur_header is None or prev_header is None or cur_header>=prev_header:
        return []
    labels=[]
    for i in range(start,cur_header):
        bi=_bullet_info(lines[i])
        if not bi: continue
        txt=bi[1]
        if clean_value(txt) is not None: continue
        if re.match(r"(?i)^(thuyết minh|chỉ tiêu|stt|mã số)$",txt): continue
        if re.match(r"(?i)^(mã số|thuyết minh)\s*:",txt): continue
        lab,code=_strip_leading_index(txt)
        if len(lab)>=4:
            labels.append((lab,code,i+1))
    def values_between(a,b):
        vals=[]
        for j in range(a+1,b):
            t=strip_md(lines[j])
            if not t or re.match(r"(?i)^(triệu đồng|triệu vnd|vnd|đồng)$",t): continue
            v=clean_value(t)
            if v is not None: vals.append(v)
        return vals
    cur=values_between(cur_header,prev_header)
    prev=values_between(prev_header,end)
    if len(labels)<5 or min(len(cur),len(prev))<max(5,int(len(labels)*0.7)):
        return []
    n=min(len(labels),len(cur),len(prev))
    return [_row(labels[i][0],cur[i],prev[i],code=labels[i][1],pattern_id="SP_INCOME_LABEL_LIST_COLUMN_MAJOR",line_no=labels[i][2],confidence=0.95) for i in range(n)]


def _norm_dedupe_label(s: str):
    x = strip_md(s).casefold()
    x = re.sub(r"\s*\((?:mã\s*số|ma\s*so|mã\s*tham\s*chiếu|ma\s*tham\s*chieu)[^)]*\)", "", x, flags=re.I)
    x = re.sub(r"\s+", " ", x).strip()
    return x


def dedupe(rows):
    best = {}
    # Prefer stronger patterns over generic period-child rows when same semantic/value tuple exists.
    rank = {
        "SP_INCOME_PIPE_TABLE": 7,
        "SP_INCOME_INLINE_PERIODS": 7,
        "SP_INCOME_HEADING_ATTRIBUTES": 6,
        "SP_INCOME_PERIOD_CHILDREN": 6,
        "SP_POSITIONAL_VALUE_CHILDREN": 5,
        "SP_INCOME_COLUMN_MAJOR": 5,
        "SP_INCOME_PLAIN_TEXT_CODE": 4,
    }
    for r in rows:
        key = (_norm_dedupe_label(r.get("indicator","")), str(r.get("current")), str(r.get("previous")))
        if key not in best or rank.get(r.get("pattern_id"),0) > rank.get(best[key].get("pattern_id"),0):
            best[key] = r
    return list(best.values())


def _extract_rows_for_scope(lines, start, end, current_year, previous_year):
    rows = []
    rows += extract_pipe_table(lines, start, end, current_year, previous_year)
    rows += extract_inline_period_rows(lines, start, end)
    rows += extract_period_children(lines, start, end, current_year, previous_year)
    rows += extract_heading_attribute_rows(lines, start, end, current_year, previous_year)
    rows += extract_positional_children(lines, start, end)
    rows += extract_code_led_mixed_rows(lines, start, end, current_year, previous_year)
    rows += extract_year_section_rows(lines, start, end, current_year, previous_year)
    rows += extract_label_list_column_major(lines, start, end, current_year, previous_year)
    rows += extract_column_major(lines, start, end, current_year, previous_year)
    rows += extract_plain_text_code_rows(lines, start, end)
    return dedupe(rows)


def extract_income_fallback(markdown_text: str, current_year: int = 2025, previous_year: int = 2024):
    lines, start, end, score = choose_income_scope(markdown_text, current_year, previous_year)
    rows = _extract_rows_for_scope(lines, start, end, current_year, previous_year)

    # Defensive candidate failover. If the selected heading produces no observations,
    # try other structurally viable headings before declaring `no_structural_rows`.
    # This protects against OCR/TOC variations without weakening statement boundaries.
    if not rows:
        raw = [c for c in _heading_candidates(lines, current_year, previous_year) if c["score"] > -1000]
        alts = [_candidate_viability(lines, c, current_year, previous_year) for c in raw]
        alts = [c for c in alts if c["span"] >= 8 and c["i"] != start]
        alts.sort(key=lambda c: (c["adjusted_score"], c["span"], -c["i"]), reverse=True)
        for cand in alts:
            alt_rows = _extract_rows_for_scope(lines, cand["i"], cand["end"], current_year, previous_year)
            if alt_rows:
                start, end, score, rows = cand["i"], cand["end"], cand["adjusted_score"], alt_rows
                break

    return {
        "rows": rows,
        "scope_start_line": start + 1 if start < len(lines) else None,
        "scope_end_line": end,
        "scope_score": score,
    }


def augment_income_rows(markdown_text: str, existing_rows=None, current_year: int = 2025, previous_year: int = 2024):
    existing_rows = list(existing_rows or [])
    fallback = extract_income_fallback(markdown_text, current_year, previous_year)["rows"]
    return dedupe(existing_rows + fallback)
