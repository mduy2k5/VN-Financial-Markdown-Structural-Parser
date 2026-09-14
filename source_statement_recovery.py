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


FP_HEADING = re.compile(r"(?i)(?:BẢNG\s+CÂN\s+ĐỐI\s+KẾ\s+TOÁN|BÁO\s+CÁO\s+TÌNH\s+HÌNH\s+TÀI\s+CHÍNH)(?:\s+HỢP\s+NHẤT)?")
NEXT_STATEMENT = re.compile(r"(?i)^(?:BÁO\s+CÁO\s+KẾT\s+QUẢ\s+HOẠT\s+ĐỘNG(?:\s+KINH\s+DOANH)?|BÁO\s+CÁO\s+LƯU\s+CHUYỂN\s+TIỀN\s+TỆ|THUYẾT\s+MINH\s+BÁO\s+CÁO\s+TÀI\s+CHÍNH)")
NOTES_ONLY_FP = re.compile(r"(?i)THÔNG\s+TIN\s+BỔ\s+SUNG.*(?:BẢNG\s+CÂN\s+ĐỐI|TÌNH\s+HÌNH\s+TÀI\s+CHÍNH)")


def choose_financial_position_scope(text: str):
    lines = text.splitlines()
    cand = []
    for i, line in enumerate(lines):
        c = clean(line)
        if FP_HEADING.search(c) and not NOTES_ONLY_FP.search(c) and len(c) <= 120 and FP_HEADING.match(c):
            # Continuation headings are valid but primary starts should rank higher.
            end = len(lines)
            for j in range(i + 1, min(len(lines), i + 1400)):
                cj = clean(lines[j])
                if NEXT_STATEMENT.search(cj):
                    end = j
                    break
            sample = "\n".join(lines[i:min(end, i + 1000)])
            f = fold(sample)
            score = 0
            score += 80 * sum(k in f for k in ("tai san", "no phai tra", "von chu so huu"))
            score += 80 if "tong cong tai san" in f or "tong tai san" in f else 0
            score += 40 if re.search(r"(?i)B\s*0?2\s*/\s*TCTD|B\s*0?1\s*[-–]?\s*DN", sample[:2500]) else 0
            score += min(240, len(re.findall(r"(?i)(?:Số\s+cuối\s+năm|Số\s+đầu\s+năm|Tại\s+ngày\s+31[./-]12[./-]20\d{2})\s*:", sample)) * 4)
            score += min(220, len(re.findall(r"\|[^\n]+\|[^\n]+\|[^\n]+\|", sample)) * 3)
            score += min(220, len(re.findall(r"\(?-?\d{1,3}(?:[.,]\d{3}){1,}\)?", sample)) // 3)
            if "tiep theo" not in fold(c):
                score += 120
            if i < 250:
                score -= 150
            cand.append((score, i, end))
    if not cand:
        return {"scope_start_line": None, "scope_end_line": None, "scope_score": 0}
    max_score = max(x[0] for x in cand)
    # A later continuation page can contain more numeric rows than the first page.  Treat nearby
    # candidates with comparable evidence as one statement chain and start from the earliest one.
    eligible = [x for x in cand if x[0] >= max_score - 180]
    score, s, e = min(eligible, key=lambda x: x[1])
    # Extend over continuation headings until next *different* statement / notes.
    for j in range(e, min(len(lines), e + 1200)):
        cj = clean(lines[j])
        if NEXT_STATEMENT.search(cj):
            e = j
            break
    return {"scope_start_line": s + 1, "scope_end_line": e, "scope_score": score}


_YEAR_VALUE_PATTERNS = [
    # `Tại ngày 31.12.2025: 123`
    re.compile(r"(?i)^(?:Tại\s+ngày\s+)?31[./-]12[./-](20\d{2})(?:\s*\([^)]*\))?\s*:\s*(.+)$"),
    re.compile(r"(?i)^(?:Năm\s*)?(20\d{2})(?:\s*\([^)]*\))?\s*:\s*(.+)$"),
]


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


def _split_code_label(label: str):
    label = clean(label)
    m = re.match(r"^([0-9]{1,4}(?:\.[0-9]+)?|[IVXLC]+)[.)-]?\s+(.+)$", label, re.I)
    if m:
        return m.group(1), clean(m.group(2))
    return None, label


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


def extract_generic_statement_rows(text: str, start_line: int, end_line: int, current_year=2025, previous_year=2024,
                                   statement: str = "GENERIC") -> list[RecoveredRow]:
    lines = text.splitlines()
    s = max(0, start_line - 1)
    e = min(len(lines), end_line)
    scoped = lines[s:e]
    rows: list[RecoveredRow] = []

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
        rows.append(RecoveredRow(label=label, current=cur, previous=prev, code=code,
                                 source_line=s + idx + 1, pattern=f"{statement}_RAW_PIPE"))

    # Inline rows with explicit period annotations.
    for idx, raw in enumerate(scoped):
        c = clean(raw)
        if not _valid_label(c) or ":" not in c:
            continue
        cur, prev = _inline_year_values(c, current_year, previous_year)
        if cur is None and prev is None:
            continue
        label = c.split(":", 1)[0]
        code, label = _split_code_label(label)
        rows.append(RecoveredRow(label=label, current=cur, previous=prev, code=code,
                                 source_line=s + idx + 1, pattern=f"{statement}_RAW_INLINE_YEARS"))

    # Parent + metadata/value children.  This handles `Số cuối năm`, `Số đầu năm`, `Tại ngày ...`, and year children.
    for idx, raw in enumerate(scoped):
        c = clean(raw)
        if not _valid_label(c):
            continue
        # Do not choose a value/meta child as its own parent.
        if re.match(r"(?i)^(?:Mã\s*số|Thuyết\s*minh|Số\s*cuối\s*năm|Số\s*đầu\s*năm|Tại\s+ngày|Năm\s*20\d{2}|20\d{2})\s*:", c):
            continue
        if re.fullmatch(r"\(?-?[\d.,]+\)?|-", c):
            continue
        code, label = _split_code_label(c.rstrip(":"))
        current = previous = None
        note = None
        child_code = code
        found = False
        parent_indent = len(raw) - len(raw.lstrip(" \t"))
        for j in range(idx + 1, min(len(scoped), idx + 12)):
            cr = scoped[j]
            cc = clean(cr)
            if not cc:
                continue
            child_indent = len(cr) - len(cr.lstrip(" \t"))
            # Once a new sibling/parent label appears, stop.  Markdown bullets with equal or shallower indentation are siblings.
            if j > idx + 1 and re.search(r"[A-Za-zÀ-ỹ]", cc) and not re.match(r"(?i)^(?:Mã\s*số|Thuyết\s*minh|Số\s*cuối\s*năm|Số\s*đầu\s*năm|Tại\s+ngày|Năm\s*20\d{2}|20\d{2})\s*:", cc):
                if child_indent <= parent_indent + 4:
                    break
            m = re.match(r"(?i)^Mã\s*số\s*:\s*(.+)$", cc)
            if m:
                child_code = clean(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Thuyết\s*minh\s*:\s*(.+)$", cc)
            if m:
                note = clean(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Số\s*cuối\s*năm\s*:\s*(.+)$", cc)
            if m:
                current = parse_number(m.group(1)); found = True; continue
            m = re.match(r"(?i)^Số\s*đầu\s*năm\s*:\s*(.+)$", cc)
            if m:
                previous = parse_number(m.group(1)); found = True; continue
            matched = False
            for yp in _YEAR_VALUE_PATTERNS:
                my = yp.match(cc)
                if my:
                    y = int(my.group(1)); val = parse_number(my.group(2))
                    if y == current_year: current = val
                    elif y == previous_year: previous = val
                    found = matched = True
                    break
            if matched:
                continue
        if found and (current is not None or previous is not None):
            rows.append(RecoveredRow(label=label, current=current, previous=previous, code=child_code, note=note,
                                     source_line=s + idx + 1, pattern=f"{statement}_RAW_CHILDREN"))

    # Deduplicate and merge complementary periods.  Code is retained in the key when present to disambiguate repeated generic labels.
    merged: dict[tuple, RecoveredRow] = {}
    order = []
    for r in rows:
        key = (fold(r.label), clean(r.code or ""))
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


def _source_id(statement: str, label: str, code: str, line: Optional[int]) -> str:
    h = hashlib.sha1(f"{fold(label)}|{clean(code)}|{line or 0}".encode("utf-8")).hexdigest()[:14]
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

        key = (fl, code, r.current, r.previous)
        if key in seen_source:
            continue
        seen_source.add(key)
        node = {
            "node_id": _source_id(statement, r.label, code, r.source_line),
            "canonical_name": clean(r.label),
            "kind": "source_observation",
            "semantic_role": "recovered_source_row",
            "sector": canonical.get("sector"),
            "method": canonical.get("method"),
            "section": r.section,
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
                }],
            },
        }
        nodes.append(node)
        by_lc.setdefault((fl, code), []).append(node)
        by_l.setdefault(fl, []).append(node)
        added += 1

    canonical.setdefault("diagnostics", {})["source_statement_recovery"] = {
        "statement": statement, "rows_recovered": len(rows), "added_nodes": added,
        "filled_existing_nodes": filled, "conflicts": conflicts,
        "policy": "source_scope_structural_recovery_v13",
    }
    return canonical
