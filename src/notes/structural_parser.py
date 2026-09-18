from __future__ import annotations

import re
from collections import defaultdict

from .note_ir import NoteBlock, NoteRow, NoteValue
from .sectionizer import fold_text
from .table_parser import parse_number
try:
    from ..common.ground_truth_quality import period_role as quality_period_role
except ImportError:
    from common.ground_truth_quality import period_role as quality_period_role

BULLET_RE = re.compile(r'^(?P<indent>\s*)(?:\*|-|\+)\s+(?P<body>.+?)\s*$')
KV_RE = re.compile(r'^(?P<label>.+?)\s*:\s*(?P<value>.+?)\s*$')
UNIT_WORD_RE = re.compile(r'\b(?:đồng|vnd|triệu\s+đồng|nghìn\s+đồng|tỷ\s+đồng|usd|eur)\b', re.I)
PERIOD_CONTAINER = {
    'so cuoi nam': 'current',
    'cuoi nam': 'current',
    'nam nay': 'current',
    'so dau nam': 'previous',
    'dau nam': 'previous',
    'nam truoc': 'previous',
}


def _strip_md(s: str) -> str:
    s = (s or '').strip()
    s = re.sub(r'^\s*#{1,6}\s*', '', s)
    s = re.sub(r'^\s*(?:\*\*|__)(.*?)(?:\*\*|__)\s*$', r'\1', s)
    s = s.replace('**', '').replace('__', '').replace('`', '').strip()
    return s


def _indent_width(raw: str) -> int:
    return len(raw.expandtabs(4)) - len(raw.expandtabs(4).lstrip(' '))


def _split_numeric_unit(raw: str):
    s = _strip_md(raw).strip().rstrip('.;')
    unit = None
    m = UNIT_WORD_RE.search(s)
    if m:
        unit = m.group(0)
        s = (s[:m.start()] + s[m.end():]).strip()
        # Khi bỏ đơn vị trong ngoặc (ví dụ ``58.066 (triệu đồng)``), không để lại
        # dấu câu nhân tạo trong giá trị raw trung thành với nguồn.
        s = re.sub(r"\(\s*\)", "", s).strip()
    return s, unit


def _period_role(text: str, *, current_year: int | None = None, previous_year: int | None = None):
    f = fold_text(_strip_md(text)).strip(' :')
    for key, role in PERIOD_CONTAINER.items():
        if f == key or f.startswith(key + ' '):
            return role
    role = quality_period_role(f, current_year, previous_year)
    return role if role in {'current', 'previous', 'quarter'} else None


def _row_role(label: str, *, current_year: int | None = None, previous_year: int | None = None):
    f = fold_text(label)
    # Không xem mọi lần xuất hiện của ``cong`` là tổng. Nhãn OCR như
    # ``Chuyển lỗ từ công ty con`` có cùng token nhưng là dòng chi tiết.
    # Dòng tổng thường được giới thiệu rõ bằng ``Tổng`` hoặc nhãn đứng riêng
    # ``Cộng``.
    if f == 'cong' or f.startswith('tong '):
        return 'total'
    if any(x in f for x in ('so cuoi nam', 'cuoi nam', f'31 12 {current_year}')):
        return 'closing'
    if any(x in f for x in ('so dau nam', 'dau nam', f'01 01 {current_year}', f'31 12 {previous_year}')):
        return 'opening'
    if any(x in f for x in ('tang trong nam', 'giam trong nam', 'mua trong nam', 'trich lap', 'hoan nhap', 'thanh ly', 'ghi nhan vao')):
        return 'movement'
    return 'detail'


def parse_bullet_structures(
    section_text: str,
    base_line: int,
    block_prefix: str,
    *,
    occupied_lines=None,
    current_year: int | None = None,
    previous_year: int | None = None,
):
    """Lấy cấu trúc bullet/key-value chung mà không dùng semantic theo ngành.

    Các dạng chính:
      A) container kỳ -> các child nhãn:giá trị lặp lại
      B) nhãn semantic -> child hiện tại/trước đây
      C) dòng bullet key:value phẳng (fallback một giá trị)

    Không scale giá trị. Giữ nguyên hierarchy nguồn và role kỳ.
    """
    occupied_lines = occupied_lines or set()
    raw_lines = section_text.splitlines()
    toks = []
    for i, raw in enumerate(raw_lines):
        abs_line = base_line + i
        if abs_line in occupied_lines:
            continue
        m = BULLET_RE.match(raw)
        if not m:
            continue
        toks.append({
            'idx': i,
            'line': abs_line,
            'indent': _indent_width(m.group('indent')),
            'body': _strip_md(m.group('body')),
            'raw': raw,
        })

    if not toks:
        return []

    # Tìm bullet parent gần nhất theo thụt lề.
    stack = []
    for pos, t in enumerate(toks):
        while stack and toks[stack[-1]]['indent'] >= t['indent']:
            stack.pop()
        t['parent'] = stack[-1] if stack else None
        t['pos'] = pos
        stack.append(pos)

    children = defaultdict(list)
    for pos, t in enumerate(toks):
        if t['parent'] is not None:
            children[t['parent']].append(pos)

    blocks = []
    used = set()
    block_no = 0

    # A) Ghép các dòng nhãn:giá trị giữa container kỳ hiện tại/trước đây.
    period_groups = []
    for pos, t in enumerate(toks):
        role = _period_role(t['body'], current_year=current_year, previous_year=previous_year)
        if not role:
            continue
        items = []
        for cp in children.get(pos, []):
            c = toks[cp]
            km = KV_RE.match(c['body'])
            if not km:
                continue
            label = _strip_md(km.group('label'))
            raw_val, unit = _split_numeric_unit(km.group('value'))
            num = parse_number(raw_val)
            if num is None and raw_val not in {'-', '–', '—', '−'}:
                continue
            items.append((fold_text(label), label, raw_val, num, unit, c['line'], cp))
        if items:
            period_groups.append((pos, role, items))

    # Gom các container kỳ liền kề/sibling theo parent rồi ghép nhãn.
    by_parent = defaultdict(list)
    for pg in period_groups:
        by_parent[toks[pg[0]]['parent']].append(pg)
    for parent, groups in by_parent.items():
        currents = [g for g in groups if g[1] == 'current']
        previouses = [g for g in groups if g[1] == 'previous']
        if not currents and not previouses:
            continue
        cmap = {}
        pmap = {}
        for _, _, items in currents:
            for x in items: cmap.setdefault(x[0], x)
        for _, _, items in previouses:
            for x in items: pmap.setdefault(x[0], x)
        labels = list(dict.fromkeys(list(cmap) + list(pmap)))
        if not labels:
            continue
        rows = []
        source_lines = []
        for key in labels:
            c = cmap.get(key); p = pmap.get(key)
            src = c or p
            vals = []
            if c:
                vals.append(NoteValue(raw=c[2], normalized=c[3], period_label='Số cuối năm', period_role='current', unit=c[4], source_line=c[5]))
                used.add(c[6]); source_lines.append(c[5])
            if p:
                vals.append(NoteValue(raw=p[2], normalized=p[3], period_label='Số đầu năm', period_role='previous', unit=p[4], source_line=p[5]))
                used.add(p[6]); source_lines.append(p[5])
            rows.append(NoteRow(label_raw=src[1], label_normalized=key, values=vals, row_role=_row_role(src[1], current_year=current_year, previous_year=previous_year), source_line=src[5], raw_cells=[src[1]] + [v.raw for v in vals]))
        for pos, _, _ in currents + previouses:
            used.add(pos); source_lines.append(toks[pos]['line'])
        block_no += 1
        blocks.append(NoteBlock(
            block_id=f'{block_prefix}:bullet_period_{block_no}', form='bullet_list', semantic_shape='breakdown',
            source_start_line=min(source_lines), source_end_line=max(source_lines), rows=rows,
            metadata={'parser': 'bullet_period_pair_v23_1'}
        ))

    # B) Dòng parent semantic có child hiện tại/trước đây trực tiếp.
    for pos, t in enumerate(toks):
        if pos in used or _period_role(t['body'], current_year=current_year, previous_year=previous_year) or KV_RE.match(t['body']):
            continue
        vals = []
        child_positions = []
        for cp in children.get(pos, []):
            c = toks[cp]
            km = KV_RE.match(c['body'])
            if not km:
                continue
            role = _period_role(km.group('label'), current_year=current_year, previous_year=previous_year)
            if not role:
                continue
            raw_val, unit = _split_numeric_unit(km.group('value'))
            num = parse_number(raw_val)
            if num is None and raw_val not in {'-', '–', '—', '−'}:
                continue
            vals.append(NoteValue(raw=raw_val, normalized=num, period_label=_strip_md(km.group('label')), period_role=role, unit=unit, source_line=c['line']))
            child_positions.append(cp)
        if vals:
            block_no += 1
            row = NoteRow(label_raw=t['body'], label_normalized=fold_text(t['body']), values=vals, row_role=_row_role(t['body'], current_year=current_year, previous_year=previous_year), source_line=t['line'], raw_cells=[t['body']] + [v.raw for v in vals])
            blocks.append(NoteBlock(
                block_id=f'{block_prefix}:bullet_row_{block_no}', form='bullet_list', semantic_shape='breakdown',
                source_start_line=t['line'], source_end_line=max([t['line']] + [toks[x]['line'] for x in child_positions]), rows=[row],
                metadata={'parser': 'bullet_semantic_period_children_v23_1'}
            ))
            used.add(pos); used.update(child_positions)

    # C) Dòng key:value một giá trị theo quy tắc bảo thủ, chưa thuộc cấu trúc đã lấy.
    singles = []
    for pos, t in enumerate(toks):
        if pos in used:
            continue
        km = KV_RE.match(t['body'])
        if not km:
            continue
        label = _strip_md(km.group('label'))
        if _period_role(label, current_year=current_year, previous_year=previous_year):
            continue
        raw_val, unit = _split_numeric_unit(km.group('value'))
        num = parse_number(raw_val)
        if num is None and raw_val not in {'-', '–', '—', '−'}:
            continue
    # Fallback một kỳ được cố ý đặt chặt. Nếu không có đơn vị tài chính rõ,
    # `key:value` thường là STT, số điện thoại, phần trăm, ID hoặc metadata bố
    # cục thay vì observation tài chính.
        if not unit:
            continue
        if fold_text(label) in {'page', 'year', 'status', 'symbol', 'stt', 'so luong don vi'}:
            continue
        singles.append((t, label, raw_val, num, unit))
        used.add(pos)
    if singles:
        block_no += 1
        rows = [NoteRow(
            label_raw=lab, label_normalized=fold_text(lab),
            values=[NoteValue(raw=rv, normalized=num, unit=unit, source_line=t['line'])],
            row_role=_row_role(lab, current_year=current_year, previous_year=previous_year), source_line=t['line'], raw_cells=[lab, rv]
        ) for t, lab, rv, num, unit in singles]
        blocks.append(NoteBlock(
            block_id=f'{block_prefix}:bullet_single_{block_no}', form='bullet_list', semantic_shape='breakdown',
            source_start_line=min(x[0]['line'] for x in singles), source_end_line=max(x[0]['line'] for x in singles), rows=rows,
            metadata={'parser': 'bullet_key_value_v23_1'}
        ))

    return blocks
