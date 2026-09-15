from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Optional


NOTES_TITLE_RE = re.compile(
    r"(?i)^\s*(?:#{1,6}\s*)?(?:BẢN\s+)?THUYẾT\s+MINH"
    r"(?:\s+VỀ)?\s+BÁO\s+CÁO\s+TÀI\s+CHÍNH"
)
NOTES_CONT_RE = re.compile(
    r"(?i)^\s*(?:#{1,6}\s*)?(?:BẢN\s+)?THUYẾT\s+MINH.*(?:TIẾP\s+THEO|\(TIẾP\s+THEO\))"
)
PAGE_META_RE = re.compile(r"^\s*page\s*:\s*(\d+)\s*$", re.I)
STATEMENT_META_RE = re.compile(r"^\s*statement_type\s*:\s*([A-Za-z_]+)\s*$", re.I)
PAGE_DELIM_RE = re.compile(r"^\s*---\s*$")
PRIMARY_HEADING_RE = re.compile(
    r"(?i)^\s*(?:#{1,6}\s*)?(?:BÁO\s+CÁO|BẢNG)\s+"
    r"(?:TÌNH\s+HÌNH\s+TÀI\s+CHÍNH|CÂN\s+ĐỐI\s+KẾ\s+TOÁN|"
    r"KẾT\s+QUẢ\s+HOẠT\s+ĐỘNG\s+KINH\s+DOANH|LƯU\s+CHUYỂN\s+TIỀN\s+TỆ)"
)


@dataclass
class NotesScope:
    found: bool
    start_line: Optional[int]
    end_line: Optional[int]
    confidence: float
    evidence: list[str]
    sticky: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _fold(value: Any) -> str:
    s = "" if value is None else str(value)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _frontmatter_notes_ranges(lines: list[str]) -> list[tuple[int, int, int | None]]:
    """Return line ranges whose page frontmatter explicitly says statement_type: notes."""
    ranges: list[tuple[int, int, int | None]] = []
    i = 0
    n = len(lines)
    while i < n:
        if not PAGE_DELIM_RE.match(lines[i]):
            i += 1
            continue
        j = i + 1
        page = None
        stype = None
        while j < n and not PAGE_DELIM_RE.match(lines[j]):
            pm = PAGE_META_RE.match(lines[j])
            if pm:
                page = int(pm.group(1))
            sm = STATEMENT_META_RE.match(lines[j])
            if sm:
                stype = sm.group(1).casefold()
            j += 1
        if j >= n:
            break
        content_start = j + 1
        k = content_start
        while k < n and not PAGE_DELIM_RE.match(lines[k]):
            k += 1
        if stype == "notes":
            ranges.append((content_start + 1, k, page))
        i = max(k, j + 1)
    return ranges


def detect_notes_scope(text: str, scanner_result: Optional[dict] = None) -> NotesScope:
    """Detect one sticky Notes scope.

    Once Notes starts, report-like headings inside the Notes area do not terminate the
    scope. This is deliberate: audited reports often repeat primary-statement names in
    explanatory note headings and test fixtures intentionally contain such decoys.
    """
    lines = text.splitlines()
    evidence: list[str] = []

    # 1) Prefer an already-detected NOTES range from the project's statement scanner.
    if scanner_result:
        note_ranges = [
            r for r in scanner_result.get("ranges", [])
            if str(r.get("statement_type")) == "NOTES"
        ]
        if note_ranges:
            r = min(note_ranges, key=lambda x: int(x.get("start_line") or 10**9))
            start = int(r.get("start_line") or 1)
            # Sticky policy: scanner end is only a lower bound. Notes extends to document end.
            evidence.append("project_statement_scanner:NOTES")
            return NotesScope(True, start, len(lines), float(r.get("confidence") or 0.90), evidence)

    # 2) Explicit page metadata is strongest when present.
    meta_ranges = _frontmatter_notes_ranges(lines)
    if meta_ranges:
        start = min(x[0] for x in meta_ranges)
        evidence.append("page_frontmatter:statement_type=notes")
        return NotesScope(True, start, len(lines), 0.995, evidence)

    # 3) Heading-based fallback. Reject likely TOC lines and require the first real title.
    starts = []
    for idx, raw in enumerate(lines, start=1):
        if not NOTES_TITLE_RE.search(raw):
            continue
        folded = _fold(raw)
        if "muc luc" in _fold("\n".join(lines[max(0, idx-8):idx+3])):
            continue
        if re.search(r"\b\d+\s*[-–]\s*\d+\s*$", raw):
            continue
        starts.append(idx)

    if not starts:
        return NotesScope(False, None, None, 0.0, ["notes_title_not_found"])

    start = starts[0]
    evidence.append("notes_title_heading")
    if any(NOTES_CONT_RE.search(lines[x-1]) for x in starts[1:]):
        evidence.append("notes_continuation_heading")
    return NotesScope(True, start, len(lines), 0.94, evidence)


def primary_heading_decoys_in_scope(text: str, scope: NotesScope) -> list[dict]:
    if not scope.found or scope.start_line is None:
        return []
    lines = text.splitlines()
    out = []
    for idx in range(scope.start_line, (scope.end_line or len(lines)) + 1):
        raw = lines[idx - 1]
        if PRIMARY_HEADING_RE.search(raw):
            out.append({"line": idx, "text": raw.strip(), "classification": "note_internal_decoy"})
    return out
