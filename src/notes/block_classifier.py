from __future__ import annotations
import re
from .note_ir import NoteBlock
from .dimension_inference import infer_dimensions
from .table_parser import parse_markdown_tables
from .structural_parser import parse_bullet_structures


def extract_blocks(
    section_text: str,
    base_line: int,
    block_prefix: str,
    *,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> list[NoteBlock]:
    tables = [
        infer_dimensions(x, current_year=current_year, previous_year=previous_year)
        for x in parse_markdown_tables(
            section_text,
            base_line,
            block_prefix,
            current_year=current_year,
            previous_year=previous_year,
        )
    ]
    occupied=set()
    for b in tables:
        occupied.update(range(b.source_start_line,b.source_end_line+1))
    bullets = [
        infer_dimensions(x, current_year=current_year, previous_year=previous_year)
        for x in parse_bullet_structures(
            section_text,
            base_line,
            block_prefix,
            occupied_lines=occupied,
            current_year=current_year,
            previous_year=previous_year,
        )
    ]
    for b in bullets:
        occupied.update(range(b.source_start_line,b.source_end_line+1))

    lines=section_text.splitlines(); narrative=[]; start=None; buf=[]; nblock=0
    for offset,raw in enumerate(lines):
        abs_line=base_line+offset
        if abs_line in occupied:
            if buf:
                nblock+=1; txt='\n'.join(buf).strip()
                if txt: narrative.append(NoteBlock(block_id=f'{block_prefix}:narrative_{nblock}',form='paragraph',semantic_shape='narrative',source_start_line=start,source_end_line=abs_line-1,text=txt,metadata={'parser':'narrative_preserve_v23_1'}))
                buf=[]; start=None
            continue
        clean=raw.strip()
        if not clean or clean.startswith('---') or re.match(r'^\s*page\s*:',clean,re.I):
            if buf: buf.append(raw)
            continue
        if start is None: start=abs_line
        buf.append(raw)
    if buf and start is not None:
        nblock+=1; txt='\n'.join(buf).strip()
        if txt: narrative.append(NoteBlock(block_id=f'{block_prefix}:narrative_{nblock}',form='paragraph',semantic_shape='narrative',source_start_line=start,source_end_line=base_line+len(lines)-1,text=txt,metadata={'parser':'narrative_preserve_v23_1'}))
    return sorted(tables+bullets+narrative,key=lambda x:(x.source_start_line,x.block_id))
