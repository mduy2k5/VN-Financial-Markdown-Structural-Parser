from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Optional


HEADING_RE = re.compile(r"(?i)B[ÁA]O\s+C[ÁA]O\s+L[ƯU]U\s+CHUY[ỂEÊ]N\s+TI[ỀEÊ]N\s+T[ỆE](?:\s+H[ỢO]P\s+NH[ẤA]T)?")
METHOD_DIRECT_RE = re.compile(r"(?i)ph[ươu]ơng\s+ph[áa]p\s+tr[ựu]c\s+ti[ếe]p")
METHOD_INDIRECT_RE = re.compile(r"(?i)ph[ươu]ơng\s+ph[áa]p\s+gi[áa]n\s+ti[ếe]p")
NOTES_RE = re.compile(r"(?i)^(?:(?:B[ẢA]N\s+)?THUY[ẾE]T\s+MINH\s+B[ÁA]O\s+C[ÁA]O\s+T[ÀA]I\s+CH[ÍI]NH|B0?5\s*/\s*TCTD|B0?9\s*[-–]?\s*DN)(?:\b|$)")

SECTION_PATTERNS = {
    "operating": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+kinh\s+doanh"),
    "investing": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+[đd][ầa]u\s+t[ưu]"),
    "financing": re.compile(r"(?i)l[ưu]u\s+chuy[ểeê]n\s+ti[ềeê]n\s+(?:thu[ầa]n\s+)?t[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\s+t[àa]i\s+ch[íi]nh"),
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
    if s in {"-", "–", "—", "..."}:
        return 0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("() ").replace(" ", "")
    s = re.sub(r"(?i)(?:tri[eệ]u|ngh[iì]n|vnd|vnđ|đ[oồ]ng)$", "", s).strip()
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
    f = fold(text)
    return (
        f.startswith("ma so") or f.startswith("thuyet minh") or
        f.startswith("nam nay") or f.startswith("nam truoc") or
        f.startswith("ky nay") or f.startswith("ky truoc") or
        f in {"chi tieu", "ma so", "thuyet minh", "nam nay", "nam truoc"}
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
        "luu chuyen tien thuan trong", "tien va cac khoan tuong duong tien tai thoi diem dau",
        "tien va tuong duong tien dau", "dieu chinh anh huong cua thay doi ty gia",
        "anh huong cua thay doi ty gia", "tien va cac khoan tuong duong tien tai thoi diem cuoi",
        "tien va tuong duong tien cuoi",
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


def choose_cashflow_scope(text: str):
    lines = text.splitlines()
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
    # Supports `label: **1.234** (Năm 2025) | **(2.345)** (Năm 2024)` and comma-separated variants.
    clean = strip_md(text)
    vals = {}
    # capture a value before a year marker
    pat = re.compile(r"(?P<val>\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*(?:triệu\s*VND|VND|VNĐ|đồng)?\s*\(\s*Năm\s*(?P<year>20\d{2})\s*\)", re.I)
    for m in pat.finditer(clean):
        vals[int(m.group("year"))] = parse_number(m.group("val"))
    if vals:
        return vals.get(current_year), vals.get(previous_year)
    # Value before `(Năm nay)` / `(Năm trước)` -- common in LLM Markdown.
    role_pat = re.compile(r"(?P<val>\(?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\)?|-)\s*(?:triệu\s*đồng|triệu\s*VND|VND|VNĐ|đồng)?\s*\(\s*Năm\s*(?P<role>nay|trước)\s*\)", re.I)
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
    scoped_text = "\n".join(scoped_lines)
    method, method_method = detect_method(scoped_text)
    sector, sector_method = detect_sector(scoped_text)

    rows = []
    section = None
    pending = None

    def flush_pending():
        nonlocal pending
        if pending:
            _emit(rows, pending.get("label"), pending.get("current"), pending.get("previous"),
                  pending.get("section"), method, pending.get("code"), pending.get("note"),
                  pending.get("line"), pending.get("pattern", "CF_PERIOD_CHILDREN"))
        pending = None

    for rel, raw in enumerate(scoped_lines, start=1):
        abs_line = s + rel
        clean = _clean_bullet(raw)
        if not clean:
            continue
        f = fold(clean)

        # section headers
        matched_section = None
        for sec, pat in SECTION_PATTERNS.items():
            if pat.search(clean):
                matched_section = sec
                break
        if matched_section and not re.search(r"(?i)thu[ầa]n", clean):
            flush_pending()
            section = matched_section
            continue

        # Child metadata/value lines.
        m = re.match(r"(?i)^Mã\s*số\s*:\s*([^|]+)$", clean)
        if m and pending:
            pending["code"] = strip_md(m.group(1)); continue
        m = re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.+)$", clean)
        if m and pending:
            pending["note"] = strip_md(m.group(1)); continue
        m = re.match(r"(?i)^(?:Năm\s*nay|Kỳ\s*này)\s*:\s*(.+)$", clean)
        if m and pending:
            pending["current"] = parse_number(m.group(1)); continue
        m = re.match(r"(?i)^(?:Năm\s*trước|Kỳ\s*trước)\s*:\s*(.+)$", clean)
        if m and pending:
            pending["previous"] = parse_number(m.group(1)); continue

        # Pipe table row: label | code? | note? | current | previous
        if raw.count("|") >= 3:
            cells = [strip_md(x) for x in raw.strip().strip("|").split("|")]
            if len(cells) >= 4 and not any(fold(x) in {"chi tieu", "nam nay", "nam truoc"} for x in cells[:2]):
                nums = [(idx, parse_number(c)) for idx, c in enumerate(cells)]
                numeric = [(idx, val) for idx, val in nums if val is not None]
                if len(numeric) >= 2:
                    code = next((c for c in cells[:-2] if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+", c, re.I)), None)
                    # Label is the descriptive text cell, not necessarily the first cell.
                    text_cells = [c for c in cells[:-2] if re.search(r"[A-Za-zÀ-ỹ]", c) and not _looks_metadata_line(c)]
                    label = max(text_cells, key=len) if text_cells else cells[0]
                    _emit(rows, label, numeric[-2][1], numeric[-1][1], section, method, code, None, abs_line, "CF_PIPE_TABLE")
                    continue

        # Inline year values on one line.
        cur, prev = _extract_inline_periods(clean, current_year, previous_year)
        if cur is not None or prev is not None:
            flush_pending()
            label = clean
            # cut value payload from label
            label = re.split(r"(?i):\s*(?:\*\*)?\(?-?\d|\s+(?:\(?-?\d{1,3}[.,]\d{3})", label, maxsplit=1)[0]
            code = None
            mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
            if mc:
                code, label = mc.group(1), mc.group(2)
            _emit(rows, label, cur, prev, section, method, code, None, abs_line, "CF_INLINE_PERIODS")
            continue

        # New semantic row candidate. Heading totals with inline values are handled above.
        if _looks_metadata_line(clean):
            continue
        # Skip document boilerplate and obvious non-row lines.
        if any(k in f for k in ("bao cao tai chinh hop nhat", "cho nam tai chinh ket thuc", "don vi tinh", "nguoi lap", "ke toan truong", "tong giam doc")):
            continue

        # If this is a section total label without values yet, keep as pending.
        flush_pending()
        code = None
        label = clean
        mc = re.match(r"^([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)[.)]?\s+(.+)$", label, re.I)
        if mc:
            code, label = mc.group(1), mc.group(2)
        pending = {
            "label": label,
            "code": code,
            "note": None,
            "current": None,
            "previous": None,
            "section": _section_from_label(label, section),
            "line": abs_line,
            "pattern": "CF_PERIOD_CHILDREN",
            "indent": _line_indent(raw),
        }
    flush_pending()

    # Deduplicate same semantic observation emitted by overlapping layouts.
    dedup = []
    seen = set()
    for r in rows:
        key = (fold(r.source_label), r.section, r.method, r.code or "", r.current, r.previous)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)

    return {
        **scope,
        "rows": [r.to_dict() for r in dedup],
        "method": method,
        "method_method": method_method,
        "sector": sector,
        "sector_method": sector_method,
    }
