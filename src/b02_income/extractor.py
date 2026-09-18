from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

try:
    from src.common.value_semantics import detect_statement_unit, row_unit_override, is_note_reference
    from src.common.report_period import resolve_report_years
except ImportError:
    try:
        from common.value_semantics import detect_statement_unit, row_unit_override, is_note_reference
        from common.report_period import resolve_report_years
    except ImportError:
        from value_semantics import detect_statement_unit, row_unit_override, is_note_reference
        from report_period import resolve_report_years

try:
    from .scope import (
        FORM_CODE_RE,
        HEADING_RE,
        NUM_RE,
        STOP_FORM_RE,
        STOP_RE,
        SUPPLEMENT_RE,
        TOC_HINT_RE,
        _candidate_score,
        _candidate_viability,
        _find_notes_start,
        _heading_candidates,
        _period_role_and_priority,
        _scope_end_for_candidate,
        choose_income_scope,
        clean_value,
        parse_period_line,
        strip_md,
    )
except ImportError:
    from b02_income_scope import (
        FORM_CODE_RE,
        HEADING_RE,
        NUM_RE,
        STOP_FORM_RE,
        STOP_RE,
        SUPPLEMENT_RE,
        TOC_HINT_RE,
        _candidate_score,
        _candidate_viability,
        _find_notes_start,
        _heading_candidates,
        _period_role_and_priority,
        _scope_end_for_candidate,
        choose_income_scope,
        clean_value,
        parse_period_line,
        strip_md,
    )

try:
    from .mapper import parse_number, strip_mapping_qualifiers
except ImportError:
    from b02_income.mapper import parse_number, strip_mapping_qualifiers

try:
    from flat_parser.statement_locator import StatementLocator
except ImportError:
    from statement_locator import StatementLocator

BULLET_RE = re.compile(r"^(\s*)[*+-]\s+(.*)$")
NOTE_LIKE_RE = re.compile(r"^(?:(?:\d{1,3}|[IVXLC]+)(?:\.\d{1,3})+|\d{1,3}|[IVXLC]+)$", re.I)
ENTERPRISE_CODES = {"01","02","10","11","20","21","22","23","24","25","26","30","31","32","40","50","51","52","60","61","62","70","71"}



def fold(s: Any) -> str:
    s = strip_mapping_qualifiers(strip_md(s))
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"^\s*\d+(?:\.\d+)+[.)]?\s*", "", s)
    s = re.sub(r"^\s*don\s+vi\s*:\s*.*?\bma\s+so\b(?:\s+\w+)?\s+", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _is_cumulative_period_label(value: Any) -> bool:
    """Identify a year-to-date period without changing the public period API."""
    label = fold(value)
    return any(token in label for token in ("luy ke", "cumulative", "year to date", "ytd"))


def _primary_period_priority(label: Any, current_year: int, previous_year: int):
    """Rank primary quarter columns above cumulative columns for extraction."""
    role, priority = _period_role_and_priority(label, current_year, previous_year)
    if role and _is_cumulative_period_label(label):
        priority = min(priority, 5)
    return role, priority


def is_non_item_header_or_noise(label: Any) -> bool:
    s = strip_md(label)
    if not s:
        return True
    f = fold(s)
    if not f:
        return True
    # Keyed serializers may prefix a structural child heading with the field
    # name.  Normalize that wrapper before applying the semantic noise list.
    f = re.sub(r"^(?:ghi\s*chu|dien\s*giai|chi\s*tieu)\s+(?:-\s*)?", "", f)
    # Table headers & field prompts
    if f in {
        "chi tieu", "stt", "ma so", "thuyet minh", "thuyet minh ma so",
        "ma so thuyet minh", "ma so chi tieu", "chi tieu ma so",
        "cac khoan muc", "cac chi tieu tai chinh", "tong doanh thu va chi phi",
        "chi tiet doanh thu va chi phi", "nam tai chinh", "dien giai",
        "trong do", "noi dung", "content", "ma", "tong cong",
    }:
        return True
    # Form codes e.g. B02-DN, B03/TCTD-HN, B 02 - DN/HN, B02-CTCK
    if re.match(r"(?i)^(?:b\s*0?2|b\s*0?3|b\s*0?4|b\s*0?5|b\s*0?9)[a-z]?(?:[-–/]\s*[a-z0-9]+)*$", s):
        return True
    # Footnote references e.g. VI.13, VI.14, V.18.2, 12.1
    if re.match(r"(?i)^[vixlcdm\d]+(?:\.\d+)+$", s):
        return True
    # Footers / disclaimers
    if f.startswith("cac thuyet minh") or f.startswith("thuyet minh bao cao") or f.startswith("dien giai bao cao"):
        return True
    # Sub-period column headings
    if re.match(r"^(?:quy\s+[ivxlcdm\d]+|luy ke(?:\s+tu\s+dau\s+nam)?)(?:\s|$)", f):
        return True
    # Annual period headings e.g. "Nam 2025", "Nam ket thuc ngay 31 thang 12 nam 2025"
    if re.match(r"^nam\s+(?:ket\s+thuc|bao\s+cao|tai\s+chinh|20\d{2})\b", f):
        return True
    if re.match(r"^(?:nam nay|nam truoc|ky nay|ky truoc)(?:\s*[:\-].*)?$", f):
        return True
    # Administrative lines frequently acquire a numeric payload when a PDF
    # table is flattened.  They are not observations even when they contain a
    # date, page number, or a signatory's name.
    if re.match(r"^(?:trang|page)\s*:?\s*\d+(?:\s*[-/]\s*\d+)?$", f):
        return True
    if re.match(r"^(?:ngay|date)\s*:?\s*\d{1,2}\b", f):
        return True
    if re.match(r"^m\s*s\s*d\s*n\b", f):
        return True
    if f.startswith((
        "nguoi lap", "ke toan truong", "tong giam doc", "pho tong giam doc",
        "chu tich", "ky ten", "ban hanh theo", "cac thuyet minh",
        "thuyet minh bao cao", "bao cao tai chinh", "don vi tinh",
        "chuc vu", "ngan hang nha nuoc", "stt chi tieu",
        "dien giai bao cao", "thanh pho ", "bang ket qua ",
        "bao cao ket qua", "cong ty co phan",
    )):
        # A plain-text fallback may prepend the statement heading to the
        # first real row label.  Keep that row when accounting vocabulary is
        # present; filter only a standalone administrative heading.
        if not (
            f.startswith("bao cao ket qua")
            and any(token in f for token in ("doanh thu", "chi phi", "loi nhuan", "thu nhap"))
        ):
            return True

    # Role suffixes and page-transfer annotations are frequently flattened
    # after a numeric column.  They are structural text, even when a value
    # token was attached to the same line.
    if re.search(r"\b(?:tong giam doc|pho tong giam doc|ke toan truong|nguoi lap bieu|giam doc tai chinh|chuc vu)\s*$", f):
        return True
    if f in {"lai tren co phieu", "phan bo cho", "da dieu chinh lai", "dieu chinh lai"}:
        return True
    if f.startswith("mang ") and "trang" in f:
        return True

    # A short all-word footer is normally a signatory/person name.  Keep
    # labels with accounting vocabulary such as "Doanh thu" or "Chi phí".
    if re.fullmatch(r"[a-z]+(?: [a-z]+){1,7}", f):
        accounting_markers = (
            "doanh thu", "chi phi", "loi nhuan", "thue", "tai san",
            "co phieu", "co dong", "tien", "luu chuyen", "hoat dong",
            "du phong", "hang ton", "von", "no phai", "phai tra",
            "lai", "gia tri", "dich vu", "bao hiem", "ngan hang",
            "khoan", "thu nhap", "chi tieu", "so huu", "dau tu",
            "tang", "giam", "thay doi", "nhan vien", "quan ly",
            "cong ty", "cung cap", "ban hang", "giao dich", "khac",
        )
        if not any(marker in f for marker in accounting_markers):
            return True
    return False




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



def extract_pipe_table(lines, start, end, current_year=None, previous_year=None):
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
            cur_prio = prev_prio = -1
            for idx, c in enumerate(cells):
                role, priority = _primary_period_priority(c, current_year, previous_year)
                if role == "current" and priority >= cur_prio:
                    idx_cur, cur_prio = idx, priority
                elif role == "previous" and priority >= prev_prio:
                    idx_prev, prev_prio = idx, priority
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
        line = lines[j]
        bj = _bullet_info(line)
        if bj:
            ind2, txt = bj
            if ind2 <= indent:
                break
        else:
            ind2 = len(line) - len(line.lstrip())
            txt = strip_md(line)
            if not txt:
                j += 1; continue
            if ind2 <= indent:
                break
        raw.append(line)

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
            if _is_cumulative_period_label(txt):
                prio = min(prio, 5)
            if role == "current" and (cur_indent is None or ind2 < cur_indent or (ind2 == cur_indent and prio >= cur_prio)):
                current, cur_prio, cur_indent = value, prio, ind2
            elif role == "previous" and (prev_indent is None or ind2 < prev_indent or (ind2 == prev_indent and prio >= prev_prio)):
                previous, prev_prio, prev_indent = value, prio, ind2
            j += 1; continue

        if not bj and clean_value(txt) is None and len(txt) >= 4 and not is_non_item_header_or_noise(txt):
            if child_label is None:
                child_label = txt
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


def extract_period_children(lines, start, end, current_year=None, previous_year=None):
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
        if is_non_item_header_or_noise(label):
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
        if is_non_item_header_or_noise(label):
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
            # If child is a new top-level Roman numeral section label, break early
            if clean_value(txt) is None and not (NOTE_LIKE_RE.match(txt) and len(txt) <= 12):
                if re.match(r"(?i)^[IVXLCDM]+[.)\s]", txt):
                    break
            children.append((ind2, txt, lines[j])); j += 1
        if children:
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
                continue
                # Fallback: check if subsequent lines at the same indent are values in OCR output.
        same_indent_vals = []
        j = i + 1
        note = None
        while j < min(end, i + 5):
            bj = _bullet_info(lines[j])
            if not bj:
                j += 1; continue
            ind2, txt = bj
            if ind2 != indent:
                break
            v = clean_value(txt)
            if v is not None:
                same_indent_vals.append((v, lines[j]))
            elif note is None and NOTE_LIKE_RE.match(txt) and len(txt) <= 12:
                note = txt
            else:
                break
            j += 1
        if len(same_indent_vals) >= 2:
            vals = [x[0] for x in same_indent_vals]
            out.append(_row(label, vals[-2], vals[-1], code=code, note=note,
                            pattern_id="SP_POSITIONAL_VALUE_CHILDREN", line_no=i+1,
                            raw_lines=[lines[i]] + [x[1] for x in same_indent_vals]))
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


def extract_heading_attribute_rows(lines, start, end, current_year=None, previous_year=None):
    """Non-bullet semantic heading followed by bullet attributes; common on continuation pages."""
    out = []
    for i in range(start, end):
        if _bullet_info(lines[i]):
            continue
        label = strip_md(lines[i])
        if not label or len(label) < 4 or HEADING_RE.search(label) or STOP_RE.search(label):
            continue
        if is_non_item_header_or_noise(label):
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
                if _is_cumulative_period_label(txt):
                    prio = min(prio, 5)
                if role=="current" and prio>=cur_prio: current,cur_prio=value,prio
                if role=="previous" and prio>=prev_prio: previous,prev_prio=value,prio
        if saw_attr and (current is not None or previous is not None):
            label2, implicit = _strip_leading_index(label)
            if not is_non_item_header_or_noise(label2):
                out.append(_row(label2, current, previous, code=code or implicit, note=note,
                                pattern_id="SP_INCOME_HEADING_ATTRIBUTES", line_no=i+1, raw_lines=raw))
    return out


def _looks_like_plain_note_token(raw: str) -> bool:
    """Generalized note reference detector. Structural position is still required."""
    return is_note_reference(strip_md(raw))

def extract_plain_text_code_rows(lines, start, end):
    """Fallback for OCR/plain-text enterprise tables without bullets.

    Supported layouts:

      label
      code
      current
      previous

    and the common degraded 5-line layout:

      label
      code
      note
      current
      previous

    The note is consumed only when there are THREE numeric tokens after the form
    code and the first token is a conservative note-like reference.  This avoids
    shifting the note into the current-period value.
    """
    out = []
    for i in range(start, end):
        code = strip_md(lines[i])
        if code not in ENTERPRISE_CODES:
            continue

        numeric_tokens = []
        j = i + 1
        while j < min(end, i + 8) and len(numeric_tokens) < 3:
            raw = lines[j]
            t = strip_md(raw)
            if not t:
                j += 1
                continue

            v = clean_value(raw)
            if v is not None:
                numeric_tokens.append((raw, t, v))
                j += 1
                continue
            # Generalized note references such as VI.02 / V.03.3 are payload tokens
            # only in the structural slot immediately after the form code.
            if not numeric_tokens and is_note_reference(t):
                numeric_tokens.append((raw, t, None))
                j += 1
                continue

            # A textual row after the code means the vertical numeric payload ended.
            if not re.match(
                r"(?i)^(?:thuyết\s*minh|tm|năm\s*nay|năm\s*trước|"
                r"202\d|số\s*cuối\s*năm|số\s*đầu\s*năm)$",
                t,
            ):
                break
            j += 1

        if len(numeric_tokens) < 2:
            continue

        note = None
        payload = list(numeric_tokens)

        # label -> code -> note -> current -> previous
        if (
            len(payload) >= 3
            and _looks_like_plain_note_token(payload[0][1])
            and clean_value(payload[1][0]) is not None
            and clean_value(payload[2][0]) is not None
        ):
            note = payload.pop(0)[1]

        if len(payload) < 2:
            continue

        current = payload[0][2]
        previous = payload[1][2]
        value_lines = [x[0] for x in numeric_tokens]

        # Build label from up to four previous non-header text lines.
        parts = []
        k = i - 1
        while k >= start and len(parts) < 4:
            t = strip_md(lines[k])
            if not t:
                if parts:
                    break
                k -= 1
                continue
            if (
                re.fullmatch(r"\d+[.)]?", t)
                or re.match(
                    r"(?i)^(?:chỉ\s*tiêu|mã\s*số|thuyết\s*minh|tm|"
                    r"năm\s*nay|năm\s*trước|ma|số|tự|thuyết|thuyet|minh|"
                    r"chi|tiêu|tieu|dien\s*giai)$",
                    t,
                )
            ):
                k -= 1
                continue
            if clean_value(t) is not None or FORM_CODE_RE.search(t):
                break
            parts.append(t)
            k -= 1

        label = " ".join(reversed(parts)).strip()
        label = re.sub(r"^\d+[.)]\s*", "", label).strip()
        if 3 <= len(label) <= 220:
            out.append(
                _row(
                    label,
                    current,
                    previous,
                    code=code,
                    note=note,
                    pattern_id="SP_INCOME_PLAIN_TEXT_CODE_NOTE_VALUES"
                    if note
                    else "SP_INCOME_PLAIN_TEXT_CODE",
                    line_no=i + 1,
                    raw_lines=list(reversed(parts)) + [lines[i]] + value_lines,
                    confidence=0.97 if note else 0.93,
                )
            )
    return out


def _plain_label_before_code(lines, start, code_index):
    """Recover the wrapped row label immediately before a detached form code."""

    parts = []
    index = code_index - 1
    while index >= start and len(parts) < 5:
        text = strip_md(lines[index]).strip()
        if not text:
            if parts:
                break
            index -= 1
            continue
        if clean_value(text) is not None or text in ENTERPRISE_CODES:
            break
        if re.match(
            r"(?i)^(?:chỉ\s*tiêu|mã\s*số|thuyết\s*minh|tm|năm\s*nay|"
            r"năm\s*trước|ma|số|tự|thuyết|thuyet|minh|chi|tiêu|tieu|"
            r"dien\s*giai)$",
            text,
        ):
            index -= 1
            continue
        if FORM_CODE_RE.search(text):
            break
        parts.append(text)
        index -= 1
    label = " ".join(reversed(parts)).strip()
    label, _ = _strip_leading_index(label)
    return label


def _plain_next_label_code(lines, start, index, end):
    """Find the next wrapped semantic label followed by a form code."""

    parts = []
    while index < end and len(parts) < 5:
        text = strip_md(lines[index]).strip()
        if not text:
            index += 1
            continue
        if text in ENTERPRISE_CODES:
            if parts:
                label = " ".join(parts).strip()
                label, _ = _strip_leading_index(label)
                return label, text, index
            index += 1
            continue
        if clean_value(text) is not None:
            # The caller normally starts after the value run.  A second numeric
            # run means the block is ambiguous, so do not guess its label.
            return None
        if FORM_CODE_RE.search(text) or is_non_item_header_or_noise(text):
            return None
        parts.append(text)
        index += 1
    return None


def _interleaved_pair_layout(values, anchor):
    """Return a two-row layout when an arithmetic anchor confirms the order."""

    if len(values) != 4 or not anchor:
        return None
    anchor_current = parse_number(anchor.get("current"))
    anchor_previous = parse_number(anchor.get("previous"))
    if anchor_current is None or anchor_previous is None:
        return None

    candidates = [
        # Column-major: current values for both rows, then previous values.
        ((0, 2), (1, 3)),
        # Row-major: current/previous for the first row, then the second row.
        ((0, 1), (2, 3)),
    ]
    best = None
    for first_pair, second_pair in candidates:
        first_current = parse_number(values[first_pair[0]])
        first_previous = parse_number(values[first_pair[1]])
        second_current = parse_number(values[second_pair[0]])
        second_previous = parse_number(values[second_pair[1]])
        if None in (first_current, first_previous, second_current, second_previous):
            continue
        current_error = _relative_error(anchor_current - first_current, second_current)
        previous_error = _relative_error(anchor_previous - first_previous, second_previous)
        score = int(current_error <= 1e-8) + int(previous_error <= 1e-8)
        candidate = (
            score,
            current_error + previous_error,
            first_pair,
            second_pair,
            first_current,
            first_previous,
            second_current,
            second_previous,
        )
        if best is None or candidate[0] > best[0] or (
            candidate[0] == best[0] and candidate[1] < best[1]
        ):
            best = candidate
    if best is None or best[0] < 1:
        return None
    return {
        "first_current_index": best[2][0],
        "first_previous_index": best[2][1],
        "second_current_index": best[3][0],
        "second_previous_index": best[3][1],
    }


def extract_interleaved_formula_pairs(lines, start, end, base_rows):
    """Recover adjacent rows whose values are interleaved across detached columns.

    Some OCR serializers emit one row's code and then four values for two
    adjacent rows before emitting the next row's label/code.  This collector
    only accepts the block when the labels describe a known statement identity
    (net revenue = cost of sales + gross profit) and the source values satisfy
    that identity in at least one period.  It therefore remains structural and
    semantic, rather than report- or ticker-specific.
    """

    anchors = [
        row for row in base_rows
        if row.get("code") == "10" or "doanh thu thuần" in fold(row.get("indicator", ""))
    ]
    if not anchors:
        return [], set()
    anchor = anchors[0]
    rows = []
    replaced_labels = set()
    for index in range(start, end):
        code = strip_md(lines[index]).strip()
        if code not in ENTERPRISE_CODES:
            continue
        label = _plain_label_before_code(lines, start, index)
        folded_label = fold(label)
        if "gia von" not in folded_label:
            continue

        values = []
        cursor = index + 1
        note = None
        while cursor < end:
            text = strip_md(lines[cursor]).strip()
            if not text:
                cursor += 1
                continue
            detached_note = bool(
                re.fullmatch(r"(?:\d{1,2}[a-z]?|[IVXLC]+(?:\.\d+)*)", text, re.I)
                and cursor + 1 < end
                and _is_vector_value_token(lines[cursor + 1])
            )
            if (
                not values
                and note is None
                and (
                    (clean_value(text) is None and _looks_like_plain_note_token(text))
                    or detached_note
                )
            ):
                note = text
                cursor += 1
                continue
            value = clean_value(text)
            if value is None:
                break
            values.append(text)
            cursor += 1
        if len(values) != 4:
            continue

        next_row = _plain_next_label_code(lines, start, cursor, end)
        if not next_row:
            continue
        next_label, next_code, _ = next_row
        if "loi nhuan gop" not in fold(next_label):
            continue
        layout = _interleaved_pair_layout(values, anchor)
        if not layout:
            continue

        raw_lines = list(lines[index:cursor])
        rows.extend([
            _row(
                label,
                values[layout["first_current_index"]],
                values[layout["first_previous_index"]],
                code=code,
                note=note,
                pattern_id="SP_INCOME_INTERLEAVED_FORMULA_PAIR",
                line_no=index + 1,
                raw_lines=raw_lines,
                confidence=0.94,
            ),
            _row(
                next_label,
                values[layout["second_current_index"]],
                values[layout["second_previous_index"]],
                code=next_code,
                pattern_id="SP_INCOME_INTERLEAVED_FORMULA_PAIR",
                line_no=next_row[2] + 1,
                raw_lines=raw_lines,
                confidence=0.94,
            ),
        ])
        replaced_labels.update({fold(label), fold(next_label)})
        break
    return rows, replaced_labels


def _is_short_vector_token(raw: str) -> bool:
    """Identify a compact code/note token in a detached statement column."""

    text = strip_md(raw).strip()
    return bool(re.fullmatch(r"(?:\d{1,3}[a-z]?|[IVXLC]+)", text, re.I))


def _is_vector_value_token(raw: str) -> bool:
    """Identify a numeric value while excluding short form/note tokens."""

    text = strip_md(raw).strip()
    if text in {"-", "–", "—"}:
        return True
    if not re.fullmatch(r"\(?-?[\d][\d., ]*\)?", text):
        return False
    digits = re.sub(r"\D", "", text)
    return bool(re.search(r"[.,]", text) or len(digits) > 3 or text.startswith("("))


def _collect_vector_labels(lines, start: int, end: int):
    """Collect ordinal and wrapped labels from a detached label block.

    A few PDF/OCR serializers emit the label column first, then the statement
    code/note columns, and finally the two value columns.  Labels may be
    wrapped over several physical lines and child rows may not carry an
    ordinal.  This collector uses those structural signals only.
    """

    labels = []
    current = None
    child_block = False

    def flush():
        nonlocal current
        if current and len(current["label"]) >= 4 and not is_non_item_header_or_noise(current["label"]):
            labels.append(current)
        current = None

    for idx in range(start, end):
        text = strip_md(lines[idx]).strip()
        if not text or _is_short_vector_token(text) or _is_vector_value_token(text):
            continue
        folded = fold(text)
        if folded in {"trong do", "trong do :"}:
            child_block = True
            flush()
            continue

        # Wrapped OCR lines such as "hiện hành", "không kiểm soát", or
        # "doanh nghiệp" belong to the preceding label.  Check this before
        # the generic short-name/footer filter; otherwise the continuation is
        # mistaken for a signatory name and the vector loses a semantic slot.
        if current is not None:
            current_folded = fold(current["label"])
            starts_new_index = bool(re.match(r"^(?:\d+|[IVXLC]+)[.)]\s+", text, flags=re.I))
            if not starts_new_index and (text[:1].islower() or current_folded.endswith((
                " va", " kinh", " thu nhap", " cung cap", " doanh nghiep",
                " ban hang", " hoat dong",
            ))):
                current["label"] = f"{current['label']} {text}".strip()
                current["raw"].append(lines[idx])
                continue

        if is_non_item_header_or_noise(text):
            continue

        # Formula-only lines are wrapped qualifiers of the preceding row, not
        # independent statement labels.
        if current and re.fullmatch(r"\(\s*[\d\s+=*/×xX–—-]+\s*\)", text):
            current["label"] = f"{current['label']} {text}".strip()
            current["raw"].append(lines[idx])
            continue

        label, implicit_code = _strip_leading_index(text)
        if not label or clean_value(label) is not None:
            continue
        if implicit_code is not None:
            flush()
            current = {"label": label, "line": idx + 1, "raw": [lines[idx]]}
            continue

        # Child labels in the detached block often omit their ordinal.  Two
        # consecutive "Lợi nhuận..." lines are separate children; a lowercase
        # continuation line belongs to the preceding label.
        if child_block and current and folded.startswith(("loi nhuan sau thue", "lai co ban", "lai suy giam")):
            flush()
            current = {"label": text, "line": idx + 1, "raw": [lines[idx]]}
            continue
        if current is None:
            current = {"label": text, "line": idx + 1, "raw": [lines[idx]]}
            continue
        flush()
        current = {"label": text, "line": idx + 1, "raw": [lines[idx]]}
    flush()
    return labels


def _vector_label_index(labels, *terms):
    for index, slot in enumerate(labels):
        label = fold(slot.get("label", ""))
        if all(term in label for term in terms):
            return index
    return None


def _relative_error(left, right):
    if left is None or right is None:
        return float("inf")
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) / scale


def _infer_vector_gap(labels, current_values, previous_values):
    """Find one unlabeled row in a balanced value vector using formulas.

    OCR/PDF serializers can emit an extra numeric row while its label is lost.
    Dropping the value by position would be unsafe, so a candidate is accepted
    only when the statement's own semantic relationships identify it for both
    periods.  No form code, ticker, or report name participates in this step.
    """

    if len(current_values) != len(previous_values) or len(current_values) <= len(labels):
        return None
    extra = len(current_values) - len(labels)
    if extra != 1:
        return None

    op = _vector_label_index(labels, "loi nhuan thuan", "hoat dong kinh doanh")
    other_income = _vector_label_index(labels, "thu nhap khac")
    other_expense = _vector_label_index(labels, "chi phi khac")
    other_profit = _vector_label_index(labels, "loi nhuan khac")
    if other_profit is None:
        other_profit = _vector_label_index(labels, "lo khac")
    profit_before_tax = _vector_label_index(labels, "loi nhuan", "truoc thue")
    current_tax = _vector_label_index(labels, "thue", "hien hanh")
    deferred_tax = _vector_label_index(labels, "thue", "hoan lai")
    profit_after_tax = None
    for index, slot in enumerate(labels):
        folded = fold(slot.get("label", ""))
        if "loi nhuan sau thue" in folded and not any(
            token in folded for token in ("co dong", "cong ty me", "co phieu")
        ):
            profit_after_tax = index
            break

    current_numbers = [parse_number(value) for value in current_values]
    previous_numbers = [parse_number(value) for value in previous_values]
    if any(value is None for value in current_numbers + previous_numbers):
        return None

    def aligned(values, drop):
        return [value for index, value in enumerate(values) if index != drop]

    candidates = []
    for drop in range(len(current_values)):
        cur = aligned(current_numbers, drop)
        prev = aligned(previous_numbers, drop)
        score = 0
        error = 0.0

        for values in (cur, prev):
            if op is not None and other_profit is not None and profit_before_tax is not None:
                error += _relative_error(values[op] + values[other_profit], values[profit_before_tax])
                score += 1
            if other_income is not None and other_expense is not None and other_profit is not None:
                # Statements present expense rows with either a positive
                # magnitude or a negative signed value.
                direct = _relative_error(values[other_income] - values[other_expense], values[other_profit])
                signed = _relative_error(values[other_income] + values[other_expense], values[other_profit])
                error += min(direct, signed)
                score += 1
            if (
                profit_before_tax is not None
                and current_tax is not None
                and deferred_tax is not None
                and profit_after_tax is not None
            ):
                variants = (
                    values[profit_before_tax] - values[current_tax] - values[deferred_tax],
                    values[profit_before_tax] + values[current_tax] + values[deferred_tax],
                    values[profit_before_tax] - values[current_tax] + values[deferred_tax],
                    values[profit_before_tax] + values[current_tax] - values[deferred_tax],
                )
                tax_error = min(_relative_error(candidate, values[profit_after_tax]) for candidate in variants)
                error += tax_error
                score += 1

        candidates.append((score, error, drop))

    anchor = next(
        (index for index in (op, other_income, profit_before_tax) if index is not None),
        len(labels) - 1,
    )
    # If every candidate before the first arithmetic anchor preserves the
    # same relationships, prefer the gap immediately before that anchor.  It
    # is the conservative boundary between the preceding labelled block and
    # the first subtotal; this remains semantic rather than code-based.
    candidates.sort(key=lambda item: (-item[0], item[1], abs(item[2] - anchor), item[2]))
    best = candidates[0]
    # Require at least two independent relationships to agree.  A single
    # coincidence must not mutate an otherwise ambiguous vector.
    if best[0] >= 4 and best[1] <= 2e-3:
        return best[2]
    return None


def extract_vector_column_major(lines, start, end):
    """Recover a non-Markdown table with label/code/value vectors.

    The detector requires a period header, a sizeable compact metadata run,
    and exactly enough numeric payload for the discovered label slots.  It is
    therefore not enabled by a ticker or a report-specific exception and will
    leave ambiguous blocks to the normal collectors.
    """

    for header_idx in range(start, min(end, start + 40)):
        if fold(lines[header_idx]) not in {"chi tieu", "chi tieu items"}:
            continue
        period_lines = []
        for idx in range(header_idx + 1, min(end, header_idx + 20)):
            folded = fold(lines[idx])
            if folded in {"nam nay", "nam truoc", "ky nay", "ky truoc"}:
                period_lines.append(idx)
        if len(period_lines) < 2:
            continue
        data_start = period_lines[-1] + 1

        runs = []
        idx = data_start
        while idx < end:
            if not _is_short_vector_token(lines[idx]):
                idx += 1
                continue
            run_start = idx
            while idx < end and (_is_short_vector_token(lines[idx]) or not strip_md(lines[idx])):
                idx += 1
            run_end = idx
            run_length = sum(1 for line in lines[run_start:run_end] if strip_md(line))
            if run_length >= 5:
                runs.append((run_start, run_end, run_length))

        for run_start, run_end, run_length in runs:
            previous_values = [
                idx for idx in range(data_start, run_start)
                if _is_vector_value_token(lines[idx])
            ]
            short_before = [
                idx for idx in range(data_start, run_start)
                if _is_short_vector_token(lines[idx])
            ]
            label_start = data_start
            if previous_values:
                label_start = previous_values[-1] + 1
            if short_before:
                label_start = max(label_start, short_before[-1] + 1)
            labels = _collect_vector_labels(lines, label_start, run_start)
            if len(labels) < 5 or run_length < len(labels):
                continue

            values = []
            value_start = run_end
            for idx in range(run_end, end):
                text = strip_md(lines[idx]).strip()
                if not text:
                    continue
                if _is_vector_value_token(text):
                    values.append((idx, clean_value(text)))
                    continue
                # Once the numeric vectors have started, a semantic line is a
                # hard boundary.  This avoids consuming the signature/footer.
                if values:
                    break
            n = len(labels)
            if len(values) < 2 * n:
                continue

            raw_current = [value for _, value in values[: len(values) // 2]]
            raw_previous = [value for _, value in values[len(values) // 2 :]]
            drop = _infer_vector_gap(labels, raw_current, raw_previous)
            if drop is not None:
                current_values = [(idx, value) for idx, value in values[: len(values) // 2] if idx != values[drop][0]]
                previous_start = len(values) // 2
                previous_values = [
                    (idx, value)
                    for idx, value in values[previous_start:]
                    if idx != values[previous_start + drop][0]
                ]
            else:
                current_values = values[:n]
                previous_values = values[n:2 * n]
            rows = []
            for slot, current, previous in zip(labels, current_values, previous_values):
                if current[1] is None and previous[1] is None:
                    continue
                rows.append(_row(
                    slot["label"], current[1], previous[1],
                    pattern_id="SP_INCOME_VECTOR_COLUMN_MAJOR",
                    line_no=slot["line"], raw_lines=slot["raw"], confidence=0.94,
                ))
            if rows:
                return {
                    "rows": rows,
                    "detected": True,
                    "label_start": label_start,
                    "metadata_start": run_start,
                    "value_start": value_start,
                    "label_count": n,
                    "value_count": len(values),
                }
    return {"rows": [], "detected": False}

def extract_column_major(lines, start, end, current_year=None, previous_year=None):
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




def extract_code_led_mixed_rows(lines, start, end, current_year=None, previous_year=None):
    """Handle OCR blocks led by `Mã số`, with attributes and semantic label in mixed bullet/non-bullet lines.

    Example:
      Mã số: 02
      Thuyết minh: 32
      2025 (đồng): 360...
      2024 (đồng): 291...
      Các khoản giảm trừ doanh thu
    """
    out = []
    code_re = re.compile(r"(?i)^Mã\s*số\s*:?\s*([0-9]{1,3}|[IVXLC]+)\s*$")
    i = start
    while i < end:
        t = strip_md(lines[i])
        m = code_re.match(t)
        if not m:
            i += 1; continue
        code = m.group(1); cur = prev = note = None; curp = prevp = -1; candidates = []; raw = [lines[i]]

        # Check if there is a leading label immediately before line i
        leading_label = None
        for back_idx in (i - 1, i - 2):
            if back_idx >= start:
                bt = strip_md(lines[back_idx])
                if bt and not code_re.match(bt) and clean_value(bt) is None and not parse_period_line(bt, current_year, previous_year):
                    if not is_non_item_header_or_noise(bt) and len(bt) >= 4 and not bt.startswith('#'):
                        leading_label = bt
                        break

        j = i + 1
        while j < min(end, i + 18):
            tj = strip_md(lines[j])
            if code_re.match(tj): break
            # If line j is a label followed immediately by another Mã số, break so it belongs to next code
            if j + 1 < end and code_re.match(strip_md(lines[j+1])):
                break
            if j + 2 < end and not strip_md(lines[j+1]) and code_re.match(strip_md(lines[j+2])):
                break
            if tj:
                # A completed keyed row must not absorb the next plain-text row label.
                # Keep trailing-label serialization support only when this code block
                # has not already acquired an explicit semantic label.
                original = lines[j]
                is_top_level_plain = (
                    len(original) == len(original.lstrip(" \t"))
                    and not original.lstrip().startswith(("*", "+", "-"))
                )
                if (
                    cur is not None
                    and prev is not None
                    and candidates
                    and is_top_level_plain
                    and clean_value(tj) is None
                    and not parse_period_line(tj, current_year, previous_year)
                    and not re.match(r"(?i)^(?:Thuyết\s*minh|Mã\s*số|Chỉ\s*tiêu|Diễn\s*giải)\s*:", tj)
                    and not HEADING_RE.search(tj)
                    and not STOP_RE.search(tj)
                ):
                    break

                raw.append(lines[j])
                mn = re.match(r"(?i)^Thuyết\s*minh\s*:?\s*(.*)$", tj)
                if mn:
                    nv = strip_md(mn.group(1)); note = nv or note; j += 1; continue
                pp = parse_period_line(tj, current_year, previous_year)
                if pp:
                    role, prio, val = pp
                    if role == 'current' and prio >= curp: cur, curp = val, prio
                    if role == 'previous' and prio >= prevp: prev, prevp = val, prio
                    j += 1; continue
                md = re.match(r"(?i)^(?:Chỉ\s*tiêu|Diễn\s*giải)\s*:?\s*(.+)$", tj)
                if md:
                    candidates.append(strip_md(md.group(1))); j += 1; continue
                if not is_non_item_header_or_noise(tj) and clean_value(tj) is None:
                    # Ignore page metadata / separators / document metadata fields.
                    if (not tj.startswith('#')
                        and not re.match(r"(?i)^(page|metadata|content|category|created_at|updated_at|file_name|search_folder|s3_key|status|symbol|year|period)\s*:?", tj)
                        and not HEADING_RE.search(tj)
                        and not STOP_RE.search(tj)):
                        candidates.append(tj)
            j += 1
        if cur is not None or prev is not None:
            # Last semantic-looking candidate is usually the row label in this serialization.
            label = ''
            for cand in reversed(candidates):
                c = strip_md(cand)
                if len(c) >= 4 and not re.match(r"(?i)^(mã số|thuyết minh|20\d{2})", c) and not is_non_item_header_or_noise(c):
                    label = c; break
            if not label and leading_label:
                label = leading_label
            if label and not is_non_item_header_or_noise(label):
                out.append(_row(label, cur, prev, code=code, note=note, pattern_id='SP_INCOME_CODE_LED_MIXED', line_no=i+1, raw_lines=raw, confidence=0.97))
        i = max(i + 1, j if j > i + 1 else i + 1)
    return out


def extract_year_section_rows(lines, start, end, current_year=None, previous_year=None):
    """Handle layouts split into one complete current-year section and one previous-year section.

    Example: **Năm báo cáo: 2025 (VND)** followed by rows with `Số liệu: ...`,
    then a matching 2024 section. Rows are joined by normalized semantic label;
    form code and note columns are retained only as provenance.
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
            code = implicit; note = None; value = None; raw = [lines[i]]
            j = i + 1
            while j < he:
                bj = _bullet_info(lines[j])
                if not bj: j += 1; continue
                ind2, txt = bj
                if ind2 <= indent: break
                # If we already have a value and encounter another child label, stop scanning
                if value is not None and not re.match(r"(?i)^(?:mã\s*số|thuyết\s*minh|số\s*liệu)\s*:", txt):
                    break
                raw.append(lines[j])
                mm = re.match(r"(?i)^Mã\s*số\s*:\s*(.+)$", txt)
                if mm and code is None: code = strip_md(mm.group(1))
                mn = re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.*)$", txt)
                if mn and note is None:
                    nv = strip_md(mn.group(1)); note = nv or note
                mv = re.match(r"(?i)^Số\s*liệu\s*:\s*(.+)$", txt)
                if mv and value is None:
                    vv = clean_value(mv.group(1))
                    if vv is not None: value = vv
                j += 1
            if value is not None and not is_non_item_header_or_noise(label):
                sec_rows.append({"label": label, "code": code, "note": note, "value": value, "line": i+1, "raw": raw})
        sections[year] = sec_rows
    if current_year not in sections and previous_year not in sections:
        return []
    merged={}
    for year, arr in sections.items():
        for x in arr:
            key=(_norm_dedupe_label(x["label"]),)
            z=merged.setdefault(key,{"label":x["label"],"code":x.get("code"),"note":x.get("note"),"current":None,"previous":None,"line":x["line"],"raw":[]})
            z["raw"] += x["raw"]
            if x.get("note") and not z.get("note"): z["note"]=x["note"]
            if year==current_year: z["current"]=x["value"]
            if year==previous_year: z["previous"]=x["value"]
    return [_row(z["label"],z["current"],z["previous"],code=z["code"],note=z["note"],pattern_id="SP_INCOME_YEAR_SECTIONS",line_no=z["line"],raw_lines=z["raw"]) for z in merged.values() if z["current"] is not None or z["previous"] is not None]


def extract_label_list_column_major(lines, start, end, current_year=None, previous_year=None):
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
        "SP_INCOME_PLAIN_TEXT_CODE_NOTE_VALUES": 8,
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
    vector_layout = extract_vector_column_major(lines, start, end)
    rows += vector_layout.get("rows") or []
    if vector_layout.get("detected"):
        # The ordinary plain-code collector is still useful for the row-wise
        # prefix before a detached vector block.  Suppressing it after the
        # vector boundary prevents code/note columns from becoming labels.
        plain_end = int(vector_layout.get("label_start") or end)
        rows += extract_plain_text_code_rows(lines, start, min(end, plain_end))
    else:
        rows += extract_plain_text_code_rows(lines, start, end)
    interleaved_rows, replaced_labels = extract_interleaved_formula_pairs(
        lines,
        start,
        end,
        rows,
    )
    if replaced_labels:
        # The generic plain-code collector sees the first two numeric tokens
        # as a normal pair and may therefore retain the wrong comparative
        # value.  Replace only the same semantic labels confirmed by the
        # formula-constrained collector; unrelated rows remain untouched.
        rows = [
            row for row in rows
            if fold(row.get("indicator", "")) not in replaced_labels
        ]
        rows += interleaved_rows
    return dedupe([
        row for row in rows
        if not is_non_item_header_or_noise(row.get("indicator"))
    ])


def extract_income_fallback(
    markdown_text: str,
    current_year: int | None = None,
    previous_year: int | None = None,
    fallback_unit: Optional[str] = None,
    locator_result: Optional[dict] = None,
):
    period = resolve_report_years(
        markdown_text,
        source_name="input",
        current_year=current_year,
        previous_year=previous_year,
    )
    current_year = period["current_year"]
    previous_year = period["previous_year"]
    lines, start, end, score = choose_income_scope(markdown_text, current_year, previous_year)
    locator = dict(locator_result or {}) if locator_result else None
    if locator is not None:
        accepted, reason = StatementLocator.evaluate_scope(
            locator,
            start + 1,
            end,
        )
        baseline_unhealthy = (end - start) < 8 or score < -500
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
            "baseline_start": start + 1,
            "baseline_end": end,
        }
        if accepted:
            selected = locator["selected_scope"]
            start = max(0, int(selected["start_line"]) - 1)
            end = min(len(lines), int(selected["end_line"]))
            score = selected.get("score", score)
    rows = _extract_rows_for_scope(lines, start, end, current_year, previous_year)

    # Defensive candidate failover. If the selected heading produces no observations,
    # try other structurally viable headings before declaring `no_structural_rows`.
    # This protects against OCR/TOC variations without weakening statement boundaries.
    if not rows:
        notes_start = _find_notes_start(lines)
        raw_cands = [c for c in _heading_candidates(lines, current_year, previous_year) if c["score"] > -1000]
        alts = [_candidate_viability(lines, c, current_year, previous_year, notes_start) for c in raw_cands if c["i"] != start]
        alts.sort(key=lambda x: (x["adjusted_score"], x["span"]), reverse=True)
        for cand in alts:
            alt_rows = _extract_rows_for_scope(lines, cand["i"], cand["end"], current_year, previous_year)
            if alt_rows:
                start, end, score, rows = cand["i"], cand["end"], cand["adjusted_score"], alt_rows
                break

    unit_ctx = detect_statement_unit("\n".join(lines[start:end]), fallback_unit=fallback_unit)
    for r in rows:
        u = row_unit_override(r.get("indicator"), unit_ctx)
        r["unit"] = u.unit
        r["unit_source"] = u.source

    return {
        "rows": rows,
        "scope_start_line": start + 1 if start < len(lines) else None,
        "scope_end_line": end,
        "scope_score": score,
        "unit": unit_ctx.unit,
        "unit_source": unit_ctx.source,
        "locator": locator,
    }


def augment_income_rows(markdown_text: str, existing_rows=None, current_year: int | None = None, previous_year: int | None = None):
    existing_rows = list(existing_rows or [])
    fallback = extract_income_fallback(markdown_text, current_year, previous_year)["rows"]
    return dedupe(existing_rows + fallback)
