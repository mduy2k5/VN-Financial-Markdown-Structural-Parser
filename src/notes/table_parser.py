from __future__ import annotations

import re
from typing import Optional

from .note_ir import NoteBlock, NoteRow, NoteValue
from .sectionizer import fold_text


SEP_CELL_RE = re.compile(r"^:?-{3,}:?$")
NUM_RE = re.compile(r"^\(?\s*[-+]?\d[\d.,\s]*\)?$")
DASHES = {"-", "–", "—", "−"}


def split_pipe_cells(raw: str) -> list[str]:
    s = raw.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [x.strip() for x in s.split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return len(cells) >= 2 and all((not c) or SEP_CELL_RE.fullmatch(c) for c in cells)


def parse_number(raw: str):
    s = (raw or "").strip().replace("−", "-")
    s = re.sub(r"[*_`]", "", s).strip()
    if not s or s in DASHES:
        return None
    neg = s.startswith("(") and ")" in s
    s = s.strip().strip("()").replace(" ", "")
    if not re.fullmatch(r"-?\d[\d.,]*", s):
        return None
    try:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
            x = int(s.replace(".", ""))
        elif re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", s):
            x = int(s.replace(",", ""))
        elif re.fullmatch(r"-?\d+", s):
            x = int(s)
        elif re.fullmatch(r"-?\d+[.,]\d+", s):
            # Financial reports overwhelmingly use one separator as decimal only
            # when the tail is not a 3-digit thousands group.
            tail = re.split(r"[.,]", s)[-1]
            if len(tail) == 3:
                x = int(re.sub(r"[.,]", "", s))
            else:
                x = float(s.replace(",", "."))
        else:
            x = int(re.sub(r"[.,]", "", s))
        return -abs(x) if neg else x
    except Exception:
        return None


def _row_role(label: str) -> str:
    f = fold_text(label)
    if any(x in f for x in ("tong cong", "cong", "tong doanh thu", "tong gia von", "tong chi phi")):
        return "total"
    if any(x in f for x in ("cuoi nam", "31 12", "so du cuoi")):
        return "closing"
    if any(x in f for x in ("dau nam", "01 01", "so du dau")):
        return "opening"
    if any(x in f for x in ("mua trong nam", "tang trong nam", "giam trong nam", "thanh ly", "khau hao trong nam", "trich lap", "hoan nhap")):
        return "movement"
    return "detail"


def _infer_period_role(header: str) -> Optional[str]:
    f = fold_text(header)
    # Opening-balance labels such as 01/01/2025 belong to the comparative/previous
    # slot even though they contain the current calendar year. Resolve specific
    # opening-period semantics before generic year tokens.
    if any(x in f for x in ("01 01 2025", "dau nam", "nam truoc", "gia tri 2024", "2024")):
        return "previous"
    if any(x in f for x in ("31 12 2025", "cuoi nam", "nam nay", "gia tri 2025", "2025")):
        return "current"
    return None


def _infer_measure(header: str) -> Optional[str]:
    f = fold_text(header)
    if "du phong" in f:
        return "provision"
    if "gia tri ghi so" in f or "gia tri thuan" in f or "con lai" in f:
        return "carrying_amount"
    if "gia goc" in f or "nguyen gia" in f:
        return "cost"
    if "gia tri" in f:
        return "value"
    return None


def parse_markdown_tables(section_text: str, base_line: int, block_prefix: str) -> list[NoteBlock]:
    lines = section_text.splitlines()
    out: list[NoteBlock] = []
    i = 0
    block_no = 0
    while i < len(lines):
        if "|" not in lines[i]:
            i += 1
            continue

        # A Markdown table requires a separator on the immediately following row.
        if i + 1 >= len(lines):
            i += 1
            continue
        header = split_pipe_cells(lines[i])
        sep = split_pipe_cells(lines[i + 1])
        if not is_separator_row(sep):
            i += 1
            continue

        rows_raw = []
        j = i + 2
        while j < len(lines) and "|" in lines[j]:
            cells = split_pipe_cells(lines[j])
            if cells and not is_separator_row(cells):
                rows_raw.append((j, cells))
            j += 1

        block_no += 1
        block = NoteBlock(
            block_id=f"{block_prefix}:table_{block_no}",
            form="table",
            semantic_shape="unknown",
            source_start_line=base_line + i,
            source_end_line=base_line + max(i + 1, j - 1),
            headers_raw=header,
            headers_normalized=[fold_text(x) for x in header],
            rows=[],
            metadata={"parser": "markdown_pipe_table_v1"},
        )

        value_headers = header[1:]
        for local_idx, cells in rows_raw:
            if not cells:
                continue
            label = re.sub(r"[*_`]", "", cells[0]).strip()
            values = []
            for cidx, raw in enumerate(cells[1:], start=1):
                hdr = value_headers[cidx - 1] if cidx - 1 < len(value_headers) else ""
                values.append(NoteValue(
                    raw=raw,
                    normalized=parse_number(raw),
                    period_label=hdr or None,
                    period_role=_infer_period_role(hdr),
                    measure=_infer_measure(hdr),
                    source_line=base_line + local_idx,
                    source_column=cidx,
                ))
            block.rows.append(NoteRow(
                label_raw=label,
                label_normalized=fold_text(label),
                values=values,
                row_role=_row_role(label),
                source_line=base_line + local_idx,
                raw_cells=cells,
            ))
        out.append(block)
        i = j
    return out
