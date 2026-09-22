from __future__ import annotations

import re
from collections import defaultdict

from .note_ir import NoteBlock, NoteRow, NoteValue
from .sectionizer import fold_text
from .table_parser import parse_number
from .dimension_inference import infer_movement_role
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


_MOVEMENT_STRUCTURE_CUES = (
    'thay doi', 'so dau nam', 'so cuoi nam', 'trich lap', 'thanh ly',
    'nhuong ban', 'su dung du phong', 'ket chuyen', 'hoan nhap',
    'giam du phong', 'tang du phong', 'mua trong nam', 'tang trong nam',
    'giam trong nam',
)
_MOVEMENT_ACTION_CUES = tuple(x for x in _MOVEMENT_STRUCTURE_CUES if x not in {'so dau nam', 'so cuoi nam'})


def _outer_period_marker(
    text: str,
    *,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> tuple[str | None, str | None]:
    """Nhận diện kỳ của một panel movement ở ngoài cây bullet.

    Notes movement thường được OCR/LLM chuyển thành hai panel văn bản:
    ``... trong năm nay như sau`` và ``... trong năm trước như sau``. Đây là
    kỳ của toàn panel, không phải kỳ của các nhãn con ``Số đầu năm``/
    ``Số cuối năm``.
    """

    folded = fold_text(_strip_md(text)).strip(' :')
    if not folded:
        return None, None
    current = 'nam nay' in folded and (
        'thay doi' in folded or 'nhu sau' in folded or folded in {'nam nay', 'ky nay'}
    )
    previous = 'nam truoc' in folded and (
        'thay doi' in folded or 'nhu sau' in folded or folded in {'nam truoc', 'ky truoc'}
    )
    if current_year is not None and str(current_year) in folded and (
        'thay doi' in folded or 'nhu sau' in folded or folded == f'nam {current_year}'
    ):
        return 'current', f'Năm {current_year}'
    if previous_year is not None and str(previous_year) in folded and (
        'thay doi' in folded or 'nhu sau' in folded or folded == f'nam {previous_year}'
    ):
        return 'previous', f'Năm {previous_year}'
    if current:
        return 'current', 'Năm nay'
    if previous:
        return 'previous', 'Năm trước'
    return None, None


def _line_period_context(
    raw_lines: list[str],
    *,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> dict[int, tuple[str | None, str | None]]:
    """Gán context kỳ cho từng dòng bullet theo panel văn bản gần nhất."""

    context: dict[int, tuple[str | None, str | None]] = {}
    role: str | None = None
    label: str | None = None
    for idx, raw in enumerate(raw_lines):
        marker_role = marker_label = None
        match = BULLET_RE.match(raw)
        if match:
            body = _strip_md(match.group('body'))
            folded = fold_text(body).strip(' :')
            if folded in {'nam nay', 'ky nay'}:
                marker_role, marker_label = 'current', 'Năm nay'
            elif folded in {'nam truoc', 'ky truoc'}:
                marker_role, marker_label = 'previous', 'Năm trước'
        else:
            marker_role, marker_label = _outer_period_marker(
                raw,
                current_year=current_year,
                previous_year=previous_year,
            )
        if marker_role:
            role, label = marker_role, marker_label
        context[idx] = (role, label)
    return context


def _movement_root_positions(toks: list[dict], children: dict[int, list[int]]) -> set[int]:
    """Trả về các root bullet thuộc một movement structure."""

    def root_of(pos: int) -> int:
        current = pos
        while toks[current]['parent'] is not None:
            current = toks[current]['parent']
        return current

    roots: set[int] = set()
    for pos, token in enumerate(toks):
        folded = fold_text(token['body'])
        if any(cue in folded for cue in _MOVEMENT_STRUCTURE_CUES):
            roots.add(root_of(pos))
    return roots


def _parse_movement_bullets(
    raw_lines: list[str],
    toks: list[dict],
    children: dict[int, list[int]],
    base_line: int,
    block_prefix: str,
    *,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> tuple[list[NoteBlock], set[int]]:
    """Parse movement bullets without collapsing the movement axis into period.

    A movement disclosure has two independent axes:

    - panel year: ``năm nay``/``năm trước``;
    - movement role: opening, addition, disposal, usage, closing.

    The generic bullet parser previously used ``Số đầu năm`` and ``Số cuối
    năm`` as the only period markers. That paired repeated labels such as
    ``Tổng cộng`` across unrelated movement groups and lost their parent
    context. This parser keeps one source row per numeric bullet and carries
    the parent path and movement role into the IR.
    """

    all_text = ' '.join(fold_text(_strip_md(x)) for x in raw_lines)
    cue_hits = sum(1 for cue in _MOVEMENT_ACTION_CUES if cue in all_text)
    if cue_hits < 1:
        return [], set()

    roots = _movement_root_positions(toks, children)
    if not roots:
        return [], set()

    eligible: set[int] = set()

    def root_of(pos: int) -> int:
        current = pos
        while toks[current]['parent'] is not None:
            current = toks[current]['parent']
        return current

    for pos in range(len(toks)):
        if root_of(pos) in roots:
            eligible.add(pos)

    period_context = _line_period_context(
        raw_lines,
        current_year=current_year,
        previous_year=previous_year,
    )

    def hierarchy_path(pos: int) -> list[str]:
        path: list[str] = []
        parent = toks[pos]['parent']
        while parent is not None:
            parent_match = KV_RE.match(toks[parent]['body'])
            if parent_match:
                parent_label = _strip_md(parent_match.group('label'))
            else:
                parent_label = _strip_md(toks[parent]['body']).rstrip(':').strip()
            path.append(parent_label)
            parent = toks[parent]['parent']
        return list(reversed(path))

    rows: list[NoteRow] = []
    for pos in sorted(eligible):
        token = toks[pos]
        match = KV_RE.match(token['body'])
        if not match:
            continue
        label = _strip_md(match.group('label'))
        raw_value, unit = _split_numeric_unit(match.group('value'))
        normalized = parse_number(raw_value)
        if normalized is None and raw_value not in {'-', '–', '—', '−'}:
            continue

        path = hierarchy_path(pos)
        movement_role = infer_movement_role(' > '.join(path + [label]))
        period_role, period_label = period_context.get(token['idx'], (None, None))
        row_role = _row_role(label, current_year=current_year, previous_year=previous_year)
        if movement_role in {'opening', 'closing'}:
            row_role = movement_role
        elif movement_role:
            row_role = 'movement'

        value = NoteValue(
            raw=raw_value,
            normalized=normalized,
            period_label=period_label,
            period_role=period_role,
            movement_role=movement_role,
            unit=unit,
            source_line=token['line'],
        )
        rows.append(NoteRow(
            label_raw=label,
            label_normalized=fold_text(label),
            values=[value],
            row_role=row_role,
            hierarchy_path=path,
            source_line=token['line'],
            raw_cells=[label, raw_value],
            metadata={
                'movement_role': movement_role,
                'period_context': period_label,
            },
        ))

    if not rows:
        return [], set()

    source_lines = [toks[pos]['line'] for pos in eligible]
    block = NoteBlock(
        block_id=f'{block_prefix}:bullet_movement_1',
        form='bullet_list',
        semantic_shape='movement',
        source_start_line=min(source_lines),
        source_end_line=max(source_lines),
        rows=rows,
        metadata={
            'parser': 'bullet_movement_hierarchy_v24_0',
            'hierarchy_preserved': True,
            'period_axis': 'outer_panel',
            'movement_axis': 'parent_role',
        },
    )
    return [block], eligible


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

    movement_blocks, movement_used = _parse_movement_bullets(
        raw_lines,
        toks,
        children,
        base_line,
        block_prefix,
        current_year=current_year,
        previous_year=previous_year,
    )
    blocks.extend(movement_blocks)
    used.update(movement_used)

    # A) Ghép các dòng nhãn:giá trị giữa container kỳ hiện tại/trước đây.
    period_groups = []
    for pos, t in enumerate(toks):
        if pos in used:
            continue
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
            if cp in used:
                continue
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
