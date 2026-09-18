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
    # Giữ các hậu tố như 2a / 21b.
            m2=re.fullmatch(r'(\d+)([A-Za-z]+)',p)
            if m2: norm.append(str(int(m2.group(1)))+m2.group(2).lower())
            else: norm.append(p.upper())
    return '.'.join(norm)


def _page_map(lines:list[str])->dict[int,int]:
    page=None; out={}
    for i,raw in enumerate(lines,start=1):
    # Hỗ trợ cả metadata `page: 15` và dòng hiển thị `# Page 15`.
        pm=PAGE_RE.match(raw)
        if pm: page=int(pm.group(1))
        else:
            pm2=re.match(r'^\s*#\s*Page\s+(\d+)\s*$',raw,re.I)
            if pm2: page=int(pm2.group(1))
        if page is not None: out[i]=page
    return out


def _candidate_from_line(raw:str):
    """Trả về ``(id, title, level, kind)`` cho heading thuyết minh semantic.

    Chấp nhận heading Markdown, heading in đậm và heading đánh số dạng plain.
    Cố ý loại bullet để dòng dữ liệu như `* Số cuối năm:` không mở section.
    """
    if BULLET_PREFIX_RE.match(raw): return None
    indent = len(raw) - len(raw.lstrip(' '))
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
    # Loại câu văn dài vô tình bắt đầu bằng một chữ số.
        if len(title)>220 and level==0: return None
        stripped = raw.strip()
        if level:
            style = 'markdown_heading'
        elif re.match(r'^\s*(?:\*\*|__)', raw) and re.search(r'(?:\*\*|__)\s*$', raw):
            style = 'full_bold'
        elif re.match(r'^\s*\d[^)]*[.)-]?\s+(?:\*\*|__).*?(?:\*\*|__)\s*$', raw):
            style = 'numbered_full_title_bold'
        elif '**' in raw or '__' in raw:
            style = 'inline_markup'
        else:
            style = 'plain'
        return (nm.group('id'),title,level or 2,'numbered',style,indent,stripped)
    rm=ROMAN_SECTION_RE.match(body)
    if rm:
        return (rm.group('id'),rm.group('title').strip(),level or 1,'roman','markdown_heading' if level else 'plain',indent,raw.strip())
    return None


def sectionize_notes(text:str,scope:NotesScope)->list[NoteSection]:
    if not scope.found or scope.start_line is None: return []
    lines=text.splitlines(); page_map=_page_map(lines)
    start=max(1,scope.start_line); end=min(len(lines),scope.end_line or len(lines))
    candidates=[]
    for line_no in range(start,end+1):
        c=_candidate_from_line(lines[line_no-1])
        if c:
            candidates.append((line_no,*c))
    filtered=[]
    for candidate in candidates:
        line_no,nid,title,level,kind,style,indent,stripped=candidate
        if kind == 'numbered':
    # Tiêu đề đánh số in đậm toàn dòng là dạng không phải heading mạnh nhất
    # trong nguồn (ví dụ `**8.1. Theo ...**`). Giữ lại cả khi tiêu đề viết
    # kiểu title case thay vì toàn chữ hoa.
            if style == 'full_bold':
                filtered.append(candidate)
                continue
            prev_line = lines[filtered[-1][0]-1] if filtered else ''
            prev_blank = not prev_line.strip()
            title_folded = fold_text(title)
            title_is_upper = title == title.upper() and any(ch.isalpha() for ch in title)
            prev_id = filtered[-1][1] if filtered else None
            current_id = normalize_note_id(nid)
            is_nested = indent > 0 and not (prev_id and current_id.startswith(normalize_note_id(prev_id) + '.'))
            has_colon = ':' in title
            if re.match(r'^\s*\d+\)', stripped) or has_colon or style == 'inline_markup' or is_nested:
                continue
            if style == 'numbered_full_title_bold' and prev_id and current_id == normalize_note_id(prev_id):
                continue
    # Child đánh số in đậm toàn dòng như `2. **Công ty liên doanh**` thường
    # theo sau một thuyết minh số cấp cao và là item trong danh sách công bố.
    # Thuyết minh đánh số thật dùng kiểu trang/heading mới; ngoại lệ cho parent
    # La Mã vẫn cho phép dạng `V. ...` -> `1. **Tiền...**` hoạt động.
            if (
                style == 'numbered_full_title_bold'
                and prev_id
                and re.fullmatch(r'\d+(?:\.[0-9A-Za-z()]+)*', normalize_note_id(prev_id) or '')
                and re.fullmatch(r'\d+', current_id or '')
            ):
                continue
            if indent > 0 and not (prev_id and current_id.startswith(normalize_note_id(prev_id) + '.')):
                continue
            if indent == 0 and not (prev_blank or title_is_upper or 'tiep theo' in title_folded or (style == 'numbered_full_title_bold' and (not prev_id or current_id != normalize_note_id(prev_id)))):
                continue
        filtered.append(candidate)
    candidates=filtered
    if not candidates:
        pages=sorted({page_map.get(x) for x in range(start,end+1) if page_map.get(x) is not None})
        return [NoteSection(note_id_raw=None,note_id_normalized=None,title_raw='Thuyết minh Báo cáo tài chính',title_normalized=fold_text('Thuyết minh Báo cáo tài chính'),source_start_line=start,source_end_line=end,pages=pages,metadata={'sectionizer':'whole_scope_fallback'})]

    # Giữ thứ tự nguồn. Candidate đánh số mở section mới; heading La Mã cũng
    # được giữ vì chúng đại diện cho nhóm công bố lớn.
    sections=[]
    for i,(line_no,nid,title,level,kind,style,indent,stripped) in enumerate(candidates):
        next_line=candidates[i+1][0]-1 if i+1<len(candidates) else end
        pages=sorted({page_map.get(x) for x in range(line_no,next_line+1) if page_map.get(x) is not None})
        logical_id=normalize_note_id(nid)
        instance_id=f"{logical_id or 'LINE'}@L{line_no}"
        sections.append(NoteSection(note_id_raw=nid,note_id_normalized=logical_id,title_raw=title,title_normalized=fold_text(title),source_start_line=line_no,source_end_line=next_line,section_instance_id=instance_id,pages=pages,metadata={'heading_level':level,'sectionizer':'structural_heading_v23_1','heading_kind':kind,'heading_style':style,'indent':indent}))
    return sections
