from __future__ import annotations

import re
from typing import Optional

from .note_ir import NoteBlock, NoteRow, NoteValue
from .sectionizer import fold_text
try:
    from ..common.ground_truth_quality import period_role as quality_period_role
    from ..common.report_period import resolve_report_years
except ImportError:
    from common.ground_truth_quality import period_role as quality_period_role
    from common.report_period import resolve_report_years

SEP_CELL_RE = re.compile(r'^:?-{3,}:?$')
DASHES = {'-', '–', '—', '−'}


def split_pipe_cells(raw: str) -> list[str]:
    s = raw.strip()
    if s.startswith('|'): s = s[1:]
    if s.endswith('|'): s = s[:-1]
    return [x.strip() for x in s.split('|')]


def is_separator_row(cells: list[str]) -> bool:
    return len(cells) >= 2 and all((not c) or SEP_CELL_RE.fullmatch(c) for c in cells)


def _strip_md(s: str) -> str:
    return re.sub(r'[*_`]', '', s or '').strip()


def parse_number(raw: str):
    s = _strip_md(raw).replace('−', '-').strip()
    if not s or s in DASHES: return None
    neg = s.startswith('(') and ')' in s
    s = s.strip().strip('()').replace(' ', '')
    if not re.fullmatch(r'-?\d[\d.,]*', s): return None
    try:
        if re.fullmatch(r'-?\d{1,3}(?:\.\d{3})+', s): x = int(s.replace('.', ''))
        elif re.fullmatch(r'-?\d{1,3}(?:,\d{3})+', s): x = int(s.replace(',', ''))
        elif re.fullmatch(r'-?\d+', s): x = int(s)
        elif re.fullmatch(r'-?\d+[.,]\d+', s):
            tail = re.split(r'[.,]', s)[-1]
            x = int(re.sub(r'[.,]', '', s)) if len(tail) == 3 else float(s.replace(',', '.'))
        else: x = int(re.sub(r'[.,]', '', s))
        return -abs(x) if neg else x
    except Exception:
        return None


def _row_role(label: str, *, current_year: int | None = None, previous_year: int | None = None) -> str:
    f = fold_text(label)
    # ``cong`` is not sufficient evidence for a total: ``cong ty`` and
    # ``cong cu`` are ordinary business labels.  Prefer the explicit
    # ``tong`` prefix and the standalone ``cong`` row.
    if f == 'cong' or f.startswith('tong '): return 'total'
    if any(x in f for x in ('cuoi nam', '31 12', 'so du cuoi', f'tai ngay 31 thang 12 nam {current_year}')): return 'closing'
    if any(x in f for x in ('dau nam', '01 01', 'so du dau', f'tai ngay 1 thang 1 nam {current_year}', f'tai ngay 31 thang 12 nam {previous_year}')): return 'opening'
    if any(x in f for x in ('mua trong nam', 'tang trong nam', 'giam trong nam', 'thanh ly', 'khau hao trong nam', 'trich lap', 'hoan nhap')): return 'movement'
    return 'detail'


def _infer_period_role(header: str, *, current_year: int | None = None, previous_year: int | None = None) -> Optional[str]:
    """Use the shared period policy, including a distinct YTD/quarter role."""

    role = quality_period_role(header, current_year, previous_year)
    return role if role in {"current", "previous", "quarter"} else None


def _infer_measure(header: str) -> Optional[str]:
    f = fold_text(header)
    if 'du phong' in f: return 'provision'
    if 'gia tri ghi so' in f or 'gia tri thuan' in f or 'con lai' in f: return 'carrying_amount'
    if 'gia goc' in f or 'nguyen gia' in f: return 'cost'
    if 'gia tri' in f: return 'value'
    return None


def _is_data_row(cells: list[str]) -> bool:
    if len(cells) < 2: return False
    numeric = sum(1 for x in cells[1:] if parse_number(x) is not None or _strip_md(x) in DASHES)
    return numeric >= max(1, (len(cells) - 1 + 1) // 2)


def _compose_headers(header_rows: list[list[str]], width: int) -> list[str]:
    out = []
    for col in range(width):
        parts = []
        for row in header_rows:
            val = _strip_md(row[col] if col < len(row) else '')
            if not val: continue
            # Unit-only rows are retained in header provenance but do not become semantic header labels.
            if fold_text(val) in {'trieu dong', 'dong', 'vnd', 'nghin dong'}: continue
            if not parts or fold_text(parts[-1]) != fold_text(val): parts.append(val)
        out.append(' / '.join(parts))
    return out


def parse_markdown_tables(
    section_text: str,
    base_line: int,
    block_prefix: str,
    *,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> list[NoteBlock]:
    if current_year is None or previous_year is None:
        period = resolve_report_years(
            section_text,
            source_name="input",
            current_year=current_year,
            previous_year=previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
    lines = section_text.splitlines(); out=[]; i=0; block_no=0
    while i < len(lines):
        if '|' not in lines[i] or i+1 >= len(lines): i += 1; continue
        first = split_pipe_cells(lines[i]); sep = split_pipe_cells(lines[i+1])
        if not is_separator_row(sep): i += 1; continue
        raw_rows=[]; j=i+2
        while j < len(lines) and '|' in lines[j]:
            cells=split_pipe_cells(lines[j])
            if cells and not is_separator_row(cells): raw_rows.append((j,cells))
            j += 1
        width=max([len(first)] + [len(c) for _,c in raw_rows])
        header_rows=[first]
        data_start=0
        # Multi-row headers: consume leading non-data rows after separator.
        for ridx, (_, cells) in enumerate(raw_rows):
            if _is_data_row(cells):
                data_start=ridx; break
            header_rows.append(cells); data_start=ridx+1
        headers=_compose_headers(header_rows,width)
        block_no += 1
        block=NoteBlock(block_id=f'{block_prefix}:table_{block_no}', form='table', semantic_shape='unknown',
            source_start_line=base_line+i, source_end_line=base_line+max(i+1,j-1), headers_raw=headers,
            headers_normalized=[fold_text(x) for x in headers], rows=[],
            metadata={'parser':'markdown_pipe_table_v23_1','raw_header_rows':header_rows})
        for local_idx,cells in raw_rows[data_start:]:
            if not _is_data_row(cells): continue
            label=_strip_md(cells[0]); values=[]
            for cidx, raw in enumerate(cells[1:], start=1):
                hdr=headers[cidx] if cidx < len(headers) else ''
                values.append(NoteValue(raw=raw, normalized=parse_number(raw), period_label=hdr or None,
                    period_role=_infer_period_role(hdr, current_year=current_year, previous_year=previous_year), measure=_infer_measure(hdr), source_line=base_line+local_idx, source_column=cidx))
            block.rows.append(NoteRow(label_raw=label,label_normalized=fold_text(label),values=values,row_role=_row_role(label, current_year=current_year, previous_year=previous_year),
                source_line=base_line+local_idx,raw_cells=cells))
        if block.rows: out.append(block)
        i=j
    return out
