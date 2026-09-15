from __future__ import annotations

import re

from .note_ir import NoteBlock
from .dimension_inference import infer_dimensions
from .table_parser import parse_markdown_tables


def extract_blocks(section_text: str, base_line: int, block_prefix: str) -> list[NoteBlock]:
    tables = parse_markdown_tables(section_text, base_line, block_prefix)
    tables = [infer_dimensions(x) for x in tables]

    # Preserve non-table narrative chunks between tables. This keeps source fidelity
    # without attempting to turn prose into invented structured disclosures.
    lines = section_text.splitlines()
    covered = set()
    for b in tables:
        for line_no in range(b.source_start_line, b.source_end_line + 1):
            covered.add(line_no)

    narrative = []
    start = None
    buf = []
    nblock = 0
    for offset, raw in enumerate(lines):
        abs_line = base_line + offset
        if abs_line in covered:
            if buf:
                nblock += 1
                text = "\n".join(buf).strip()
                if text:
                    narrative.append(NoteBlock(
                        block_id=f"{block_prefix}:narrative_{nblock}",
                        form="paragraph",
                        semantic_shape="narrative",
                        source_start_line=start,
                        source_end_line=abs_line - 1,
                        text=text,
                        metadata={"parser": "narrative_preserve_v1"},
                    ))
                buf = []
                start = None
            continue
        clean = raw.strip()
        if not clean or clean.startswith("---") or re.match(r"^\s*page\s*:", clean, re.I):
            if buf:
                buf.append(raw)
            continue
        if start is None:
            start = abs_line
        buf.append(raw)

    if buf and start is not None:
        nblock += 1
        text = "\n".join(buf).strip()
        if text:
            narrative.append(NoteBlock(
                block_id=f"{block_prefix}:narrative_{nblock}",
                form="paragraph",
                semantic_shape="narrative",
                source_start_line=start,
                source_end_line=base_line + len(lines) - 1,
                text=text,
                metadata={"parser": "narrative_preserve_v1"},
            ))

    return sorted(tables + narrative, key=lambda x: (x.source_start_line, x.block_id))
