from __future__ import annotations

import re

from .document import descendants
from .guide import UniversalGuide
from .models import FieldObservation, StructuralNode
from .primitives import extract_periods, extract_values, whole_text_period
from .textnorm import fold


CODE_KEYS = {"ma so", "code"}
NOTE_KEYS = {"thuyet minh", "so lieu thuyet minh"}


def _parse_pipe_inline(node: StructuralNode, guide: UniversalGuide):
    text = node.text
    segments = [x.strip() for x in text.split("|")]

    first_segment = segments[0]
    if ":" in first_segment:
        _, first_data = first_segment.split(":", 1)
        data_segments = [first_data.strip()] + segments[1:]
    else:
        data_segments = segments[1:]

    values = []
    period_values = []
    code = None
    note = None
    numeric_values = []

    for segment in data_segments:
        if not segment:
            continue

        vals = extract_values(segment, node.line_no, guide, mask_periods=True)
        periods = extract_periods(segment, node.line_no, guide)
        role_m = re.search(r"\(([^()]+)\)", segment)
        explicit_role = role_m.group(1).strip() if role_m else None

        if periods and vals:
            vals[0].role = explicit_role or periods[0].role
            period_values.append((periods[0], vals[0]))
            continue

        if vals:
            vals[0].role = explicit_role
            numeric_values.extend(vals)

    # Typical BCTC row: label | code | note/blank | current | previous
    if len(numeric_values) >= 3:
        first = numeric_values[0]
        if (
            first.role is None
            and first.normalized_candidate is not None
            and first.normalized_candidate == first.normalized_candidate.to_integral()
            and 0 <= first.normalized_candidate < 1000
            and len(first.raw_value.strip("()")) <= 3
        ):
            code = first.raw_value
            numeric_values = numeric_values[1:]

    values = numeric_values
    return values, period_values, code, note


def _bounded_descendants(
    anchor: StructuralNode,
    nodes: list[StructuralNode],
    semantic_anchor_indices: set[int],
    max_depth: int = 6,
):
    """
    Traverse descendants but DO NOT cross into another semantic record.

    If descendant B is itself an alias-resolved canonical anchor, B and its
    subtree belong to B, not to A. This is the core v0.4.2 boundary rule.
    """
    out = []
    queue = [(idx, 1) for idx in anchor.children]

    while queue:
        idx, depth = queue.pop(0)
        if depth > max_depth:
            continue

        node = nodes[idx]

        if idx in semantic_anchor_indices:
            # Semantic child boundary: do not consume it and do not enter subtree.
            continue

        out.append(node)

        for child_idx in node.children:
            queue.append((child_idx, depth + 1))

    return out



def _sequential_local_attributes(
    anchor: StructuralNode,
    nodes: list[StructuralNode],
    semantic_anchor_indices: set[int],
    guide: UniversalGuide,
    max_nodes: int = 8,
):
    """
    Fallback for Markdown serialization like:

        **TỔNG TÀI SẢN**
        * Số cuối năm: ...
        * Số đầu năm: ...

    The plain/bold label is not a bullet parent, so indentation tree has no
    relationship. Scan only the immediately following local nodes and stop
    at the next semantic anchor or unrelated business node.
    """
    period_values = []
    note = None
    code = None
    unit = None
    positional_atoms = []

    start = anchor.node_index + 1
    end = min(len(nodes), start + max_nodes)

    for i in range(start, end):
        n = nodes[i]

        # Page break / large structural jump is a hard stop.
        if n.line_no - anchor.line_no > 8:
            break

        if i in semantic_anchor_indices:
            break

        if n.pattern_id == "SP_PERIOD_VALUE_ATTRIBUTE":
            p = whole_text_period(n.lhs or "", n.line_no, guide)
            if p and n.values:
                period_values.append((p, n.values[0]))
                unit = unit or n.unit or n.inherited_unit
                continue

        # Generic date-bearing local attribute, e.g.
        #   Số liệu ngày 31/12/2025 (VND): 86...
        # It need not be classified as SP_PERIOD_VALUE_ATTRIBUTE as long as
        # it contains exactly one reporting period and one value.
        if n.values and len(n.values) == 1:
            ps = extract_periods(n.lhs or n.text or "", n.line_no, guide)
            if len(ps) == 1:
                period_values.append((ps[0], n.values[0]))
                unit = unit or n.unit or n.inherited_unit
                continue

        if (
            n.pattern_id == "SP_LABEL_VALUE_INLINE"
            and n.lhs
            and fold(n.lhs) in {"tong", "tong cong", "total", "tong so"}
            and n.values
        ):
            positional_atoms.extend(n.values)
            unit = unit or n.unit or n.inherited_unit
            continue

        if n.pattern_id == "SP_NAMED_ATTRIBUTE" and n.lhs:
            key = fold(n.lhs)
            if key in NOTE_KEYS:
                note = note or (n.rhs.strip() if n.rhs else None)
                continue
            if key in CODE_KEYS:
                code = code or (n.rhs.strip() if n.rhs else None)
                continue

        # Wrapper serialization:
        #   C - NỢ PHẢI TRẢ
        #   * Chỉ tiêu: 300
        #       * Số cuối năm: ...
        #       * Số đầu năm: ...
        if n.lhs and fold(n.lhs) in {"chi tieu", "ma so", "code"}:
            if n.rhs:
                code = code or n.rhs.strip()
            for child_idx in n.children:
                child = nodes[child_idx]
                if child.pattern_id == "SP_PERIOD_VALUE_ATTRIBUTE":
                    p = whole_text_period(child.lhs or "", child.line_no, guide)
                    if p and child.values:
                        period_values.append((p, child.values[0]))
                        unit = unit or child.unit or child.inherited_unit
            if period_values:
                continue

        # Display formulas such as "(270=100+200)" / "(440 = 300 + 400)"
        # are structural metadata, not financial payload and should not break
        # the local record.
        formula_text = (n.text or "").strip().strip("()")
        if re.fullmatch(r"\d{2,3}\s*=\s*\d{2,3}(?:\s*[+\-]\s*\d{2,3})+", formula_text):
            continue

        if n.pattern_id == "SP_VALUE_ONLY_POSITIONAL" and n.values:
            positional_atoms.extend(n.values)
            unit = unit or n.unit or n.inherited_unit
            continue

        # Any other non-attribute node ends the local record.
        break

    # Plain sequential row packet. Interpret from the tail because financial
    # values are the last two atoms, while the leading atoms are usually
    # form-code and optional note reference. Examples:
    #   label / 100 / current / previous
    #   label / 110 / 5 / current / previous
    # The code/note are metadata only and never mapping keys.
    positional_values = []
    if not period_values and len(positional_atoms) >= 2:
        atoms = list(positional_atoms)
        if len(atoms) >= 3:
            prefix = atoms[:-2]
            positional_values = atoms[-2:]
            if prefix:
                first = prefix[0]
                raw = first.raw_value.strip()
                if re.fullmatch(r"\d{2,3}(?:\.\d+)?", raw):
                    code = code or raw
                elif re.fullmatch(r"\d+(?:\.\d+)+", raw):
                    note = note or raw
            if len(prefix) >= 2:
                raw = prefix[1].raw_value.strip()
                if re.fullmatch(r"\d+(?:\.\d+)*", raw):
                    note = note or raw
        else:
            positional_values = atoms[:2]

    # Preserve positional-column order from a nearby explicit header.
    # Some OCR output serializes "Số đầu năm" before "Số cuối năm".
    if not period_values and len(positional_values) == 2:
        recent_periods = []
        for prev in nodes[max(0, anchor.node_index - 140):anchor.node_index]:
            f = fold(prev.text or "")
            if not any(k in f for k in ("so dau nam", "so cuoi nam", "dau nam", "cuoi nam")):
                continue
            pp = whole_text_period(prev.text or "", prev.line_no, guide)
            if pp:
                recent_periods.append(pp)
        if len(recent_periods) >= 2:
            pair = recent_periods[-2:]
            folded = [fold(x.raw_period) for x in pair]
            if any("dau nam" in x for x in folded) and any("cuoi nam" in x for x in folded):
                period_values = list(zip(pair, positional_values))
                positional_values = []

    return period_values, note, code, unit, positional_values


DETACHED_TOTAL_NODE_IDS = {
    "TOTAL_ASSETS",
    "TOTAL_LIABILITIES",
    "TOTAL_EQUITY",
    "TOTAL_LIABILITIES_AND_EQUITY",
}


def _recover_detached_total_payload(
    anchor: StructuralNode,
    nodes: list[StructuralNode],
    selected,
):
    """
    Recover payload when a financial total label is detached from its values.

    Supported general structural forms:

    1) Heading + standalone multi-period payload
       TOTAL L+E
       1,192... (2025), 978... (2024)

    2) Heading + generic keyed values
       TOTAL ASSETS
       Số liệu: current
       Số liệu (Trình bày lại): previous

    3) Heading + following unlabeled Markdown table block
       TOTAL ASSETS
       | ...period headers... |
       | detail ... |
       | TOTAL VALUE CURRENT | TOTAL VALUE PREVIOUS |

       When the total heading precedes a detached table block, the total is the
       terminal row of that block, not necessarily the nearest row. This is
       common in OCR/LLM serialization where labels are emitted before the
       value matrix.

    Returns (period_values, positional_values, unit, evidence) or None.
    """
    if selected.node_id not in DETACHED_TOTAL_NODE_IDS:
        return None

    start = anchor.node_index + 1
    lookahead = nodes[start:min(len(nodes), start + 80)]
    if not lookahead:
        return None

    # Ignore separators/page-number noise while preserving locality.
    def is_noise(n: StructuralNode):
        f = fold(n.text or "")
        if f in {"---", "—", "-", ""}:
            return True
        if re.fullmatch(r"\d{1,3}", (n.text or "").strip()):
            return True
        return False

    nearby = []
    for n in lookahead:
        if n.line_no - anchor.line_no > 40:
            break
        nearby.append(n)

    # ---------------------------------------------------------------
    # Form 1: direct standalone multi-period payload.
    # ---------------------------------------------------------------
    for n in nearby[:5]:
        if is_noise(n):
            continue
        if (
            n.pattern_id == "SP_MULTI_PERIOD_INLINE"
            and len(n.periods) >= 2
            and len(n.values) >= 2
        ):
            return (
                list(zip(n.periods[:2], n.values[:2])),
                [],
                n.unit or n.inherited_unit,
                "detached_total_multi_period",
            )
        # A strong unrelated semantic-looking label ends this direct form.
        if n.label_text and n.pattern_id not in {
            "SP_VALUE_ONLY_POSITIONAL",
            "SP_LABEL_VALUE_INLINE",
        }:
            break

    # ---------------------------------------------------------------
    # Form 2: two generic keyed values immediately after the total.
    # We intentionally keep them positional. The resolver maps first/second
    # value using the statement's current/previous context.
    # ---------------------------------------------------------------
    keyed = []
    keyed_unit = None
    for n in nearby[:6]:
        if is_noise(n):
            continue
        if (
            n.pattern_id == "SP_LABEL_VALUE_INLINE"
            and n.lhs
            and n.values
            and fold(n.lhs).startswith(("so lieu", "gia tri"))
        ):
            keyed.append(n.values[0])
            keyed_unit = keyed_unit or n.unit or n.inherited_unit
            if len(keyed) == 2:
                return ([], keyed, keyed_unit, "detached_total_generic_keyed_pair")
            continue
        if keyed:
            break
        if n.pattern_id == "SP_MARKDOWN_TABLE_ROW":
            break
        if n.label_text and n.pattern_id != "SP_VALUE_ONLY_POSITIONAL":
            break

    # ---------------------------------------------------------------
    # Form 3: detached table block.
    # The first table row must be physically close to the total heading.
    # Once a table block starts, use its terminal row carrying two period
    # values. This avoids the unsafe "nearest row" behavior.
    # ---------------------------------------------------------------
    table_rows = []
    started = False

    # IMPORTANT: line-distance is only a gate for the START of the detached
    # table. Once the table begins, consume the entire contiguous table block.
    # Do not reuse the generic 40-line nearby window here: long balance-sheet
    # tables can easily exceed 40 source lines, and truncating them makes the
    # penultimate detail row look like the terminal total row (BWE family).
    table_scan = nodes[start:min(len(nodes), start + 240)]
    for n in table_scan:
        if not started:
            if is_noise(n):
                continue
            if n.pattern_id == "SP_MARKDOWN_TABLE_ROW":
                if n.line_no - anchor.line_no > 6:
                    break
                started = True
                table_rows.append(n)
                continue
            # Allow no arbitrary prose before a detached table.
            break
        else:
            if n.pattern_id == "SP_MARKDOWN_TABLE_ROW":
                table_rows.append(n)
                continue
            break

    if table_rows:
        for n in reversed(table_rows):
            if len(n.periods) >= 2 and len(n.values) >= 2:
                return (
                    list(zip(n.periods[:2], n.values[:2])),
                    [],
                    n.unit or n.inherited_unit,
                    "detached_total_terminal_table_row",
                )

    return None


def collect_observation(
    anchor: StructuralNode,
    nodes: list[StructuralNode],
    selected,
    candidates,
    guide: UniversalGuide,
    *,
    semantic_anchor_indices: set[int] | None = None,
):
    semantic_anchor_indices = semantic_anchor_indices or set()

    values = []
    period_values = []
    note = anchor.note
    code = anchor.code
    unit = anchor.unit or anchor.inherited_unit
    evidence = [f"anchor_pattern:{anchor.pattern_id}"]

    # Self-contained structures.
    if anchor.pattern_id == "SP_MARKDOWN_TABLE_ROW":
        if anchor.periods and len(anchor.periods) == len(anchor.values):
            period_values = list(zip(anchor.periods, anchor.values))
        else:
            values = list(anchor.values)
        evidence.append("table_self_contained")

    elif anchor.pattern_id == "SP_PIPE_DELIMITED_INLINE_ROW":
        values, period_values, pipe_code, pipe_note = _parse_pipe_inline(anchor, guide)
        code = code or pipe_code
        note = note or pipe_note
        evidence.append("pipe_self_contained")

    elif anchor.pattern_id == "SP_MULTI_PERIOD_INLINE":
        if len(anchor.periods) >= 2 and len(anchor.values) >= 2:
            period_values = list(zip(anchor.periods, anchor.values))
        evidence.append("multi_period_inline")

    elif anchor.pattern_id == "SP_CODE_NOTE_PERIOD_INLINE_ROW":
        # Values were already stripped of code/note metadata by document.py.
        # Resolver assigns first/second payload to current/previous statement context.
        values = list(anchor.values)
        code = code or anchor.code
        note = note or anchor.note
        evidence.append("code_note_period_inline_self_contained")

    elif anchor.pattern_id == "SP_LABEL_VALUE_INLINE":
        values = list(anchor.values)
        if anchor.inherited_period and values:
            period_values = [(anchor.inherited_period, v) for v in values]
            values = []
        evidence.append("inline_value")

    # Prefer an explicit direct summary child over deeper details.
    local_summary_found = False
    for child_idx in anchor.children:
        child = nodes[child_idx]
        if (
            child.pattern_id == "SP_LABEL_VALUE_INLINE"
            and child.lhs
            and fold(child.lhs) in {"tong", "tong cong", "total", "tong so"}
            and child.values
        ):
            local_summary_found = True
            if anchor.inherited_period:
                for v in child.values:
                    period_values.append((anchor.inherited_period, v))
            else:
                values.extend(child.values)
            unit = unit or child.unit or child.inherited_unit
    if local_summary_found:
        evidence.append("direct_generic_summary_child")

    # For container/child structures, traverse only within this semantic record.
    bounded = _bounded_descendants(
        anchor,
        nodes,
        semantic_anchor_indices=semantic_anchor_indices - {anchor.node_index},
        max_depth=6,
    )

    for d in bounded:
        if local_summary_found and d.pattern_id != "SP_NAMED_ATTRIBUTE":
            continue
        if d.pattern_id == "SP_NAMED_ATTRIBUTE" and d.lhs:
            key = fold(d.lhs)
            if key in NOTE_KEYS:
                if selected.kind != "section":
                    note = note or (d.rhs.strip() if d.rhs else None)
            elif key in CODE_KEYS:
                code = code or (d.rhs.strip() if d.rhs else None)
            elif key == "so tien" and d.values:
                values.extend(d.values)
            continue

        if d.pattern_id == "SP_PERIOD_VALUE_ATTRIBUTE":
            p = whole_text_period(d.lhs or "", d.line_no, guide)
            if p and d.values:
                period_values.append((p, d.values[0]))
            continue

        if d.pattern_id == "SP_PERIOD_CONTAINER":
            continue

        # Repeated generic total children are positional period columns:
        #   TỔNG TÀI SẢN
        #       Tổng: current
        #       Tổng: previous
        # This is common when the LLM drops the date labels but preserves row
        # order from the statement header.
        if (
            d.parent_index == anchor.node_index
            and d.pattern_id == "SP_LABEL_VALUE_INLINE"
            and d.lhs
            and fold(d.lhs) in {"tong", "tong cong", "total", "tong so"}
            and d.values
        ):
            values.extend(d.values)
            unit = unit or d.unit or d.inherited_unit
            continue

        # Generic direct-child period payload. Some OCR/LLM serializers wrap a
        # total as:
        #   TỔNG NGUỒN VỐN
        #       Tổng cộng: value (2025); value (2024)
        # The child is not a canonical semantic anchor, but it still carries
        # the parent record's period values.
        if (
            d.parent_index == anchor.node_index
            and d.periods
            and d.values
            and len(d.periods) == len(d.values)
        ):
            period_values.extend(zip(d.periods, d.values))
            unit = unit or d.unit or d.inherited_unit
            continue

        # Generic direct-child numeric payload. This covers values serialized as
        # bullets with a unit annotation such as "12.410... (Không rõ đơn vị)".
        # Semantic child anchors are excluded by the bounded-descendant walk.
        if (
            d.parent_index == anchor.node_index
            and d.values
            and not d.lhs
            and not d.periods
            and d.pattern_id in {"SP_LABEL_CONTAINER", "SP_VALUE_ONLY_POSITIONAL"}
        ):
            values.extend(d.values)
            unit = unit or d.unit or d.inherited_unit
            continue

        # direct child under inherited period, but only if it is not a semantic anchor
        if d.pattern_id == "SP_LABEL_VALUE_INLINE" and d.inherited_period and d.values:
            if d.parent_index == anchor.node_index:
                for v in d.values:
                    period_values.append((d.inherited_period, v))
            continue

        # A1/BAB serialization: repeated keyed children are positional columns.
        # Example:
        #   Tiền gửi tại NHNN
        #       5.2: 1.219.788
        #       5.2: 798.225
        # Here 5.2 is a note/reference key, while the two values correspond to
        # current/previous column context.
        if (
            d.pattern_id == "SP_LABEL_VALUE_INLINE"
            and d.parent_index == anchor.node_index
            and d.values
            and d.lhs
            and re.fullmatch(r"\d+(?:\.\d+)+", d.lhs.strip())
        ):
            note = note or d.lhs.strip()
            values.extend(d.values)
            continue

        if d.pattern_id == "SP_VALUE_ONLY_POSITIONAL" and d.values:
            values.extend(d.values)

        if unit is None and (d.unit or d.inherited_unit):
            unit = d.unit or d.inherited_unit

    # Sequential fallback for plain/non-parent labels whose attributes are
    # serialized as immediately following bullets (e.g. TOTAL_ASSETS in ABB).
    if not period_values and not values:
        seq_periods, seq_note, seq_code, seq_unit, seq_values = _sequential_local_attributes(
            anchor,
            nodes,
            semantic_anchor_indices - {anchor.node_index},
            guide,
        )
        if seq_periods or seq_values:
            period_values.extend(seq_periods)
            values.extend(seq_values)
            if selected.kind != "section":
                note = note or seq_note
            code = code or seq_code
            unit = unit or seq_unit
            evidence.append("sequential_local_attribute_fallback")

    # Explicit financial totals may have their value payload detached from the
    # semantic label. Run this after normal collection so it only acts as a
    # targeted total-level recovery. A recovered payload overrides formula/code
    # artifacts accidentally tokenized from the total label itself.
    detached = _recover_detached_total_payload(anchor, nodes, selected)
    if detached and not period_values:
        detached_period_values, detached_values, detached_unit, detached_evidence = detached
        if detached_period_values or detached_values:
            period_values = detached_period_values
            values = detached_values
            unit = unit or detached_unit
            evidence.append(detached_evidence)

    if period_values:
        values = []

    return FieldObservation(
        anchor_node_index=anchor.node_index,
        line_no=anchor.line_no,
        source_label=anchor.label_text or anchor.text,
        selected=selected,
        all_candidates=candidates,
        pattern_id=anchor.pattern_id,
        pattern_name=anchor.pattern_name,
        values=values,
        period_values=period_values,
        note=note,
        code=code,
        unit=unit,
        evidence=evidence + [
            f"semantic_boundaries={len(semantic_anchor_indices)}",
            f"bounded_descendants={len(bounded)}",
        ],
    )
