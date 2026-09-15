from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .note_ir import NoteSection
from .scanner import NotesScope


HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*?)\s*$")
NOTE_ID_RE = re.compile(
    r"^\s*(?P<id>"
    r"(?:[IVXLCDM]+\.)?\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))?"
    r"|[IVXLCDM]+\.\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))?"
    r")\s*[.)-]?\s*(?P<title>.*)$",
    re.I,
)
ROMAN_SECTION_RE = re.compile(r"^\s*(?P<id>[IVXLCDM]+)\.\s*(?P<title>.+)$", re.I)
PAGE_RE = re.compile(r"^\s*page\s*:\s*(\d+)\s*$", re.I)


def fold_text(value: str) -> str:
    s = unicodedata.normalize("NFD", value or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def normalize_note_id(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip().rstrip(".")
    s = re.sub(r"\s+", "", s)
    parts = s.split(".")
    norm = []
    for p in parts:
        m = re.fullmatch(r"(\d+)(\([A-Za-z0-9]+\))?", p)
        if m:
            num = str(int(m.group(1)))
            norm.append(num + (m.group(2) or ""))
        else:
            norm.append(p.upper())
    return ".".join(norm)


def _page_map(lines: list[str]) -> dict[int, int]:
    page = None
    out = {}
    for i, raw in enumerate(lines, start=1):
        pm = PAGE_RE.match(raw)
        if pm:
            page = int(pm.group(1))
        if page is not None:
            out[i] = page
    return out


def sectionize_notes(text: str, scope: NotesScope) -> list[NoteSection]:
    if not scope.found or scope.start_line is None:
        return []

    lines = text.splitlines()
    page_map = _page_map(lines)
    start = max(1, scope.start_line)
    end = min(len(lines), scope.end_line or len(lines))

    candidates: list[tuple[int, str | None, str, int]] = []
    for line_no in range(start, end + 1):
        raw = lines[line_no - 1]
        hm = HEADING_RE.match(raw)
        if not hm:
            continue
        level = len(hm.group(1))
        body = hm.group(2).strip()
        folded = fold_text(body)

        # Skip repeated document-level Notes continuation heading.
        if "thuyet minh bao cao tai chinh" in folded or "thuyet minh ve bao cao" in folded:
            continue

        nm = NOTE_ID_RE.match(body)
        if nm:
            nid = nm.group("id")
            title = nm.group("title").strip(" .:-") or body
            candidates.append((line_no, nid, title, level))
            continue

        # Roman top-level sections (I. / II. / III. / VIII. / IX.) are valid note sections.
        rm = ROMAN_SECTION_RE.match(body)
        if rm:
            candidates.append((line_no, rm.group("id"), rm.group("title").strip(), level))

    # If no numbered headings exist, preserve the whole notes scope as one section.
    if not candidates:
        pages = sorted({page_map.get(x) for x in range(start, end + 1) if page_map.get(x) is not None})
        return [NoteSection(
            note_id_raw=None,
            note_id_normalized=None,
            title_raw="Thuyết minh Báo cáo tài chính",
            title_normalized=fold_text("Thuyết minh Báo cáo tài chính"),
            source_start_line=start,
            source_end_line=end,
            pages=pages,
            metadata={"sectionizer": "whole_scope_fallback"},
        )]

    sections: list[NoteSection] = []
    for i, (line_no, nid, title, level) in enumerate(candidates):
        next_line = candidates[i + 1][0] - 1 if i + 1 < len(candidates) else end
        pages = sorted({
            page_map.get(x) for x in range(line_no, next_line + 1)
            if page_map.get(x) is not None
        })
        sections.append(NoteSection(
            note_id_raw=nid,
            note_id_normalized=normalize_note_id(nid),
            title_raw=title,
            title_normalized=fold_text(title),
            source_start_line=line_no,
            source_end_line=next_line,
            pages=pages,
            metadata={"heading_level": level, "sectionizer": "heading_v1"},
        ))
    return sections
