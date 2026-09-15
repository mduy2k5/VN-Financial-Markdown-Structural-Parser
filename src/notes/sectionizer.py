from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .note_ir import NoteSection
from .scanner import NotesScope

HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*?)\s*$')
BULLET_PREFIX_RE = re.compile(r'^\s*(?:\*|-|\+)\s+')
NOTE_ID_RE = re.compile(
    r'^\s*(?P<id>'
    r'(?:[IVXLCDM]+\.)?\d+[A-Za-z]?(?:\.[0-9A-Za-z]+)*(?:\([A-Za-z0-9]+\))?'
    r'|[IVXLCDM]+\.\d+(?:\.[0-9A-Za-z]+)*(?:\([A-Za-z0-9]+\))?'
    r')\s*[.)-]?\s*(?P<title>.*)$', re.I)
ROMAN_SECTION_RE = re.compile(r'^\s*(?P<id>[IVXLCDM]+)\.\s*(?P<title>.+)$', re.I)
PAGE_RE = re.compile(r'^\s*page\s*:\s*(\d+)\s*$', re.I)


def fold_text(value: str) -> str:
    s = unicodedata.normalize('NFD', value or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('đ','d').replace('Đ','D').lower()
    return ' '.join(re.sub(r'[^a-z0-9]+',' ',s).split())


def _strip_md(value: str) -> str:
    s=(value or '').strip()
    s=re.sub(r'^\s*#{1,6}\s*','',s)
    s=s.replace('**','').replace('__','').replace('`','').strip()
    return s


def normalize_note_id(raw: Optional[str]) -> Optional[str]:
    if not raw: return None
    s=raw.strip().rstrip('.')
    s=re.sub(r'\s+','',s)
    parts=s.split('.')
    norm=[]
    for p in parts:
        m=re.fullmatch(r'(\d+)(\([A-Za-z0-9]+\))?',p)
        if m:
            norm.append(str(int(m.group(1)))+(m.group(2) or ''))
        else:
            # preserve suffixes such as 2a / 21b
            m2=re.fullmatch(r'(\d+)([A-Za-z]+)',p)
            if m2: norm.append(str(int(m2.group(1)))+m2.group(2).lower())
            else: norm.append(p.upper())
    return '.'.join(norm)


def _page_map(lines:list[str])->dict[int,int]:
    page=None; out={}
    for i,raw in enumerate(lines,start=1):
        # Support both metadata `page: 15` and visible `# Page 15`.
        pm=PAGE_RE.match(raw)
        if pm: page=int(pm.group(1))
        else:
            pm2=re.match(r'^\s*#\s*Page\s+(\d+)\s*$',raw,re.I)
            if pm2: page=int(pm2.group(1))
        if page is not None: out[i]=page
    return out


def _candidate_from_line(raw:str):
    """Return (id,title,level,kind) for semantic note headings.

    Accept Markdown heading, bold heading and plain numbered heading. Bullet rows are
    intentionally excluded so data lines like `* Số cuối năm:` cannot open sections.
    """
    if BULLET_PREFIX_RE.match(raw): return None
    hm=HEADING_RE.match(raw)
    level=len(hm.group(1)) if hm else 0
    body=_strip_md(hm.group(2) if hm else raw)
    if not body: return None
    folded=fold_text(body)
    if 'thuyet minh bao cao tai chinh' in folded or 'ban thuyet minh bao cao tai chinh' in folded:
        return None
    nm=NOTE_ID_RE.match(body)
    if nm:
        title=nm.group('title').strip(' .:-')
        if not title: return None
        # Reject long prose sentences accidentally starting with a number.
        if len(title)>220 and level==0: return None
        return (nm.group('id'),title,level or 2,'numbered')
    rm=ROMAN_SECTION_RE.match(body)
    if rm:
        return (rm.group('id'),rm.group('title').strip(),level or 1,'roman')
    return None


def sectionize_notes(text:str,scope:NotesScope)->list[NoteSection]:
    if not scope.found or scope.start_line is None: return []
    lines=text.splitlines(); page_map=_page_map(lines)
    start=max(1,scope.start_line); end=min(len(lines),scope.end_line or len(lines))
    candidates=[]
    for line_no in range(start,end+1):
        c=_candidate_from_line(lines[line_no-1])
        if c:
            nid,title,level,kind=c
            candidates.append((line_no,nid,title,level,kind))
    if not candidates:
        pages=sorted({page_map.get(x) for x in range(start,end+1) if page_map.get(x) is not None})
        return [NoteSection(note_id_raw=None,note_id_normalized=None,title_raw='Thuyết minh Báo cáo tài chính',title_normalized=fold_text('Thuyết minh Báo cáo tài chính'),source_start_line=start,source_end_line=end,pages=pages,metadata={'sectionizer':'whole_scope_fallback'})]

    # Keep source order. A numbered candidate starts a new section; Roman headings are
    # retained too because they represent major disclosure families.
    sections=[]
    for i,(line_no,nid,title,level,kind) in enumerate(candidates):
        next_line=candidates[i+1][0]-1 if i+1<len(candidates) else end
        pages=sorted({page_map.get(x) for x in range(line_no,next_line+1) if page_map.get(x) is not None})
        sections.append(NoteSection(note_id_raw=nid,note_id_normalized=normalize_note_id(nid),title_raw=title,title_normalized=fold_text(title),source_start_line=line_no,source_end_line=next_line,pages=pages,metadata={'heading_level':level,'sectionizer':'structural_heading_v23_1','heading_kind':kind}))
    return sections
