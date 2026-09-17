from __future__ import annotations

import re

from .guide import UniversalGuide
from .models import SourceLine, StructuralNode, TableContext
from .preprocess import is_table_separator, split_pipe_cells
from .primitives import (
    explicit_note,
    extract_periods,
    extract_unit,
    extract_values,
    whole_text_period,
    VALUE_TOKEN_RE,
)
from .textnorm import strip_numbering, strip_financial_prefix, strip_inline_financial_metadata, fold


COLON_RE = re.compile(r"^([^:：]{1,180})\s*[:：]\s*(.*)$")


def _parse_code_note_period_inline_row(text: str, line_no: int, guide: UniversalGuide):
    """Parse compact OCR/LLM financial rows such as:

        Các khoản phải thu ngắn hạn 130 4.260.806.610.198 2.252.910.212.253
        Chi phí trả trước ngắn hạn 151 13 32.309.453.139 24.815.192.830

    Returns ``(label, code, note, payload_values)`` or ``None``.  The parser is
    deliberately conservative: it only accepts a 3-digit statement code
    immediately before one/two trailing financial values, with an optional
    small note reference between code and values.
    """
    body = strip_inline_financial_metadata(
        strip_financial_prefix(strip_numbering(text or ""))
    ).strip()
    if not body or ":" in body or "|" in body:
        return None
    if extract_periods(body, line_no, guide):
        return None

    matches = list(VALUE_TOKEN_RE.finditer(body))
    if len(matches) < 3:
        return None

    def raw(m):
        return body[m.start():m.end()].strip()

    def is_code(tok: str):
        return bool(re.fullmatch(r"\d{3}", tok)) and 100 <= int(tok) <= 699

    def looks_financial(tok: str):
        t = tok.strip()
        if t in {"-", "–", "—", "−"}:
            return True
        u = t.strip("() ").replace("-", "")
        return bool(
            re.fullmatch(r"\d{4,}", u)
            or re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", u)
        )

    # Prefer two trailing financial columns (current/previous).
    payload_match_count = 2 if looks_financial(raw(matches[-1])) and looks_financial(raw(matches[-2])) else 1
    if payload_match_count == 1 and not looks_financial(raw(matches[-1])):
        return None

    payload_start = len(matches) - payload_match_count
    prefix_matches = matches[:payload_start]
    if not prefix_matches:
        return None

    code_match = prefix_matches[-1]
    note = None

    # Optional note reference sits between statement code and payload.
    if len(prefix_matches) >= 2:
        maybe_note = raw(prefix_matches[-1])
        maybe_code = raw(prefix_matches[-2])
        if is_code(maybe_code) and re.fullmatch(r"\d{1,2}", maybe_note):
            code_match = prefix_matches[-2]
            note = maybe_note

    code = raw(code_match)
    if not is_code(code):
        return None

    label = body[:code_match.start()].strip(" -–—.:;()")
    label = strip_inline_financial_metadata(strip_financial_prefix(strip_numbering(label)))
    if len(label) < 3 or not re.search(r"[A-Za-zÀ-ỹ]", label):
        return None

    # Reject obvious headers/formulas/metadata even if they accidentally contain numbers.
    f = fold(label)
    if any(x in f for x in (
        "mau so", "cong thuc", "ngay ", "dia chi", "cho nam tai chinh",
        "bao cao tinh hinh tai chinh", "thong tu", "trang ", "page ",
    )):
        return None

    payload_text = body[matches[payload_start].start():]
    payload_values = extract_values(payload_text, line_no, guide, mask_periods=True)
    if len(payload_values) < payload_match_count:
        return None
    payload_values = payload_values[-payload_match_count:]
    return label, code, note, payload_values


def _split_top_level_colon(text: str):
    """Split key:value only when the colon is outside parentheses."""
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch in ":：" and depth == 0:
            return text[:i].strip(), text[i + 1:].strip()
    return None


def _table_label_and_metadata(
    line: SourceLine,
    ctx: TableContext,
    guide: UniversalGuide,
):
    cells = split_pipe_cells(line.clean)
    headers = list(ctx.header_cells)

    label = None
    code = None
    note = None
    period_values = []
    raw_values = []

    def hfold(s):
        from .textnorm import fold
        return fold(s)

    def clean_cell(s):
        return s.strip()

    # ---------------------------------------------------------------
    # Robust period-column anchoring.
    # ---------------------------------------------------------------
    # Many OCR/LLM Markdown tables lose the explicit "Chỉ tiêu" header or an
    # empty Thuyết minh cell. Column-by-column zip then shifts code/note into
    # current/previous. Financial period columns, however, are almost always the
    # rightmost columns. Anchor them from the right first, then infer metadata
    # from the prefix.
    header_periods = []
    for i, h in enumerate(headers):
        ps = extract_periods(h, line.line_no, guide)
        if ps:
            header_periods.append((i, ps[0]))

    if header_periods:
        period_count = len(header_periods)
        if len(cells) >= period_count:
            period_cells = cells[-period_count:]
            prefix_cells = cells[:-period_count]

            # Pair rightmost source cells with period headers in header order.
            for (_, p), cell in zip(header_periods, period_cells):
                vals = extract_values(cell, line.line_no, guide, mask_periods=False)
                if vals:
                    period_values.append((p, vals[0]))

            # Remove structural empty cells from metadata prefix.
            prefix = [clean_cell(x) for x in prefix_cells if clean_cell(x)]

            # Label = first prefix cell that is not a bare code/value token.
            label_idx = None
            for i, cell in enumerate(prefix):
                vals = extract_values(cell, line.line_no, guide, mask_periods=False)
                # Small textual labels can contain numbering/markdown but should
                # not be treated as a pure financial value.
                if not vals or any(ch.isalpha() for ch in cell):
                    label = strip_numbering(cell)
                    label_idx = i
                    break

            if label_idx is not None:
                remaining = prefix[:label_idx] + prefix[label_idx + 1:]
            else:
                remaining = prefix

            has_code_header = any('ma so' in hfold(h) for h in headers)
            has_note_header = any('thuyet minh' in hfold(h) for h in headers)

            # Explicit form-code column is metadata only.
            if has_code_header:
                for i, cell in enumerate(list(remaining)):
                    raw = cell.strip('*_ ')
                    if re.fullmatch(r'\d{2,3}[a-zA-Z]?', raw):
                        code = raw
                        remaining.pop(i)
                        break

            # Any remaining prefix token belongs to note when table declares a
            # note column. Without a code header, a numeric prefix can still be
            # a note reference rather than a current-period value.
            if has_note_header and remaining:
                note = remaining[0].strip('*_ ')

            if label is not None:
                label = strip_inline_financial_metadata(
                    strip_financial_prefix(strip_numbering(label))
                )

            return label, code, note, period_values, raw_values, cells

    # ---------------------------------------------------------------
    # Legacy/fallback path for tables without recognizable period headers.
    # ---------------------------------------------------------------
    for i, cell in enumerate(cells):
        header = headers[i] if i < len(headers) else ""
        hf = hfold(header)

        if not cell:
            continue
        if any(x in hf for x in ("ma so", "mã số")):
            code = cell
            continue
        if "thuyet minh" in hf:
            note = cell
            continue

        periods = extract_periods(header, line.line_no, guide)
        vals = extract_values(cell, line.line_no, guide, mask_periods=False)
        if periods and vals:
            period_values.append((periods[0], vals[0]))
            continue

        if label is None and not vals:
            label = strip_numbering(cell)

    if label is None:
        for cell in cells:
            vals = extract_values(cell, line.line_no, guide, mask_periods=False)
            if cell and not vals:
                label = strip_numbering(cell)
                break

    if not period_values:
        for cell in cells:
            vals = extract_values(cell, line.line_no, guide, mask_periods=False)
            if vals:
                raw_values.extend(vals)

    if label is not None:
        label = strip_inline_financial_metadata(
            strip_financial_prefix(strip_numbering(label))
        )
    return label, code, note, period_values, raw_values, cells


def build_nodes(
    lines: list[SourceLine],
    table_line_map: dict[int, TableContext],
    guide: UniversalGuide,
) -> list[StructuralNode]:
    nodes: list[StructuralNode] = []
    bullet_stack: list[int] = []

    # Header/separator table lines are not data nodes.
    skip_table_lines = set()
    seen_table_ids = set()
    for ctx in table_line_map.values():
        if ctx.table_id in seen_table_ids:
            continue
        seen_table_ids.add(ctx.table_id)
        skip_table_lines.add(ctx.header_line)
        skip_table_lines.add(ctx.separator_line)

    for line in lines:
        if line.is_blank:
            continue
        if line.line_no in skip_table_lines:
            continue

        table_ctx = table_line_map.get(line.line_no)
        representation = "table_row" if table_ctx else ("bullet" if line.is_bullet else "plain")

        node = StructuralNode(
            node_index=len(nodes),
            line_no=line.line_no,
            raw_text=line.raw,
            text=line.clean,
            indent=line.indent,
            is_bullet=line.is_bullet,
            bullet_marker=line.bullet_marker,
            representation=representation,
        )

        if table_ctx:
            node.table_id = table_ctx.table_id
            node.table_header = table_ctx.header_cells
            (
                node.label_text,
                node.code,
                node.note,
                period_values,
                node.values,
                node.table_cells,
            ) = _table_label_and_metadata(line, table_ctx, guide)
            # Store paired table values through temporary period/value arrays.
            for p, v in period_values:
                node.periods.append(p)
                node.values.append(v)
                v.role = p.role

        else:
            # Non-table pipe row: label lives in the first segment/cell.
            if line.has_pipe:
                first_segment = line.clean.split("|", 1)[0].strip()
                if ":" in first_segment:
                    node.label_text = strip_inline_financial_metadata(
                        strip_financial_prefix(strip_numbering(first_segment.split(":", 1)[0].strip()))
                    )
                else:
                    node.label_text = strip_inline_financial_metadata(
                        strip_financial_prefix(strip_numbering(first_segment))
                    )
            else:
                split = _split_top_level_colon(line.clean)
                if split:
                    lhs_raw, rhs_raw = split
                    node.lhs = strip_numbering(lhs_raw)
                    node.rhs = rhs_raw
                    node.label_text = strip_inline_financial_metadata(
                        strip_financial_prefix(node.lhs)
                    )
                else:
                    node.label_text = strip_inline_financial_metadata(
                        strip_financial_prefix(strip_numbering(line.clean))
                    )

            node.periods = extract_periods(line.clean, line.line_no, guide)
            node.unit = extract_unit(line.clean, guide)
            node.note = explicit_note(line.clean, guide)

            # For colon syntax, values should come from rhs to avoid label/item numbers.
            if node.rhs is not None:
                node.values = extract_values(
                    node.rhs,
                    line.line_no,
                    guide,
                    mask_periods=True,
                )
            else:
                node.values = extract_values(
                    line.clean,
                    line.line_no,
                    guide,
                    mask_periods=True,
                )

            # Compact statement row: label + code + [note] + current + previous.
            # Hydrate before alias matching so the semantic label is clean and
            # the code/note never compete with period values.
            compact = _parse_code_note_period_inline_row(line.clean, line.line_no, guide)
            if compact:
                compact_label, compact_code, compact_note, compact_values = compact
                node.label_text = compact_label
                node.code = node.code or compact_code
                node.note = node.note or compact_note
                node.values = compact_values

        # Bullet hierarchy only. Plain/table nodes never become bullet parents.
        if line.is_bullet and representation == "bullet":
            while bullet_stack:
                parent = nodes[bullet_stack[-1]]
                if parent.indent < node.indent:
                    break
                bullet_stack.pop()

            if bullet_stack:
                node.parent_index = bullet_stack[-1]
                nodes[bullet_stack[-1]].children.append(node.node_index)

            bullet_stack.append(node.node_index)

        nodes.append(node)

    return nodes


def descendants(nodes: list[StructuralNode], idx: int, max_depth: int = 6):
    out = []
    queue = [(idx, 0)]
    seen = set()
    while queue:
        current, depth = queue.pop(0)
        if current in seen or depth >= max_depth:
            continue
        seen.add(current)
        for child_idx in nodes[current].children:
            child = nodes[child_idx]
            out.append(child)
            queue.append((child_idx, depth + 1))
    return out


def ancestors(nodes: list[StructuralNode], idx: int):
    out = []
    current = nodes[idx]
    seen = set()
    while current.parent_index is not None and current.parent_index not in seen:
        seen.add(current.parent_index)
        current = nodes[current.parent_index]
        out.append(current)
    return out


def hydrate_keyed_record_wrappers(nodes: list[StructuralNode]) -> None:
    """
    Promote OCR/LLM keyed records such as:

      * Mã số: 400
          * Tên chỉ tiêu: D. VỐN CHỦ SỞ HỮU
          * Thuyết minh: -
          * 31/12/2025: ...
          * 01/01/2025: ...

    into a semantic anchor whose label is the `Tên chỉ tiêu` value.  The raw
    source tree and provenance are preserved; only semantic fields on the
    wrapper node are hydrated.
    """
    from .textnorm import fold

    for node in nodes:
        if not node.children:
            continue

        name = None
        code = node.code
        note = node.note

        # The wrapper itself may be `Mã số: 400`.
        if node.lhs and fold(node.lhs) in {"ma so", "chi tieu", "code"}:
            code = code or (node.rhs.strip() if node.rhs else None)

        for child_idx in node.children:
            child = nodes[child_idx]
            if not child.lhs:
                continue
            key = fold(child.lhs)
            if key in {"ten chi tieu", "ten khoan muc", "khoan muc"} and child.rhs:
                name = child.rhs.strip()
            elif key in {"ma so", "chi tieu", "code"} and child.rhs:
                code = code or child.rhs.strip()
            elif key in {"thuyet minh", "so lieu thuyet minh"} and child.rhs:
                raw_note = child.rhs.strip()
                if raw_note not in {"-", "–", "—"}:
                    note = note or raw_note

        if name:
            node.label_text = strip_inline_financial_metadata(
                strip_financial_prefix(strip_numbering(name))
            )
            node.code = code
            node.note = note
            node.pattern_evidence.append("hydrated_keyed_record_wrapper")


def hydrate_column_major_statement_blocks(nodes: list[StructuralNode], guide: UniversalGuide):
    """
    Rehydrate OCR column-major blocks:
      [N labels]
      Thuyết minh / Mã số / Số cuối năm / Số đầu năm
      [optional code column]
      [N current values]
      [N previous values]
    """
    hydrated = []

    for i in range(len(nodes) - 3):
        header_nodes = nodes[i:i+4]
        header_folds = [fold(x.text or "") for x in header_nodes]
        allowed_headers = {"thuyet minh", "ma so", "so cuoi nam", "so dau nam"}
        if not (
            all(x in allowed_headers for x in header_folds)
            and any(x == "so cuoi nam" for x in header_folds)
            and any(x == "so dau nam" for x in header_folds)
            and any(x in {"ma so", "thuyet minh"} for x in header_folds)
        ):
            continue

        # Labels are the semantic-looking nodes immediately before the header,
        # back to the nearest root/context boundary.
        label_nodes = []
        j = i - 1
        while j >= 0 and len(label_nodes) < 100:
            n = nodes[j]
            ff = fold(n.label_text or n.text or "")
            if ff in {"tai san", "nguon von"}:
                break
            if n.pattern_id == "SP_CONTEXT_CARRIER":
                break
            if n.values and n.pattern_id == "SP_VALUE_ONLY_POSITIONAL":
                break
            if n.label_text and not re.fullmatch(r"[-–—−]?\(?[\d.,]+\)?", (n.text or "").strip()):
                label_nodes.append(n)
            j -= 1

        label_nodes.reverse()
        N = len(label_nodes)
        if N < 3:
            continue

        # Numeric-only run after the header.
        k = i + 4
        atom_nodes = []
        while k < len(nodes):
            n = nodes[k]
            if n.pattern_id == "SP_VALUE_ONLY_POSITIONAL" and n.values:
                atom_nodes.append(n)
                k += 1
                continue
            break

        if len(atom_nodes) < 2 * N:
            continue

        payload = atom_nodes[-2*N:]
        current_nodes = payload[:N]
        previous_nodes = payload[N:]

        p_cur = whole_text_period("Số cuối năm", nodes[i].line_no, guide)
        p_prev = whole_text_period("Số đầu năm", nodes[i].line_no, guide)
        if not p_cur or not p_prev:
            continue

        for label_node, cur_node, prev_node in zip(label_nodes, current_nodes, previous_nodes):
            if not cur_node.values or not prev_node.values:
                continue
            label_node.values = [cur_node.values[0], prev_node.values[0]]
            label_node.periods = [p_cur, p_prev]
            label_node.representation = "column_major_hydrated"
            hydrated.append({
                "label_line": label_node.line_no,
                "label": label_node.label_text,
                "current_line": cur_node.line_no,
                "previous_line": prev_node.line_no,
            })

    return hydrated
