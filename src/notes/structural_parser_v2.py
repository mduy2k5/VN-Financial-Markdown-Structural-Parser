from __future__ import annotations

"""Tree-preserving structural parser for Notes.

The legacy Notes parser is intentionally kept in ``structural_parser.py``.
This module has a narrower contract: every numeric bullet leaf becomes a
``NoteValue`` and no value is discarded merely because it is not labelled as
current/previous.  Period, measure, movement and hierarchy are dimensions of
the value, not assumptions about a two-column primary statement.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

from .dimension_inference import infer_movement_role
from .note_ir import NoteBlock, NoteRow, NoteValue
from .sectionizer import fold_text
from .structural_parser import (
    BULLET_RE,
    KV_RE,
    _indent_width,
    _period_role,
    _row_role,
    _split_numeric_unit,
    _strip_md,
)
from .table_parser import parse_number


DASHES = {"-", "–", "—", "−"}
METADATA_LABELS = {
    "page",
    "page number",
    "trang",
    "year",
    "status",
    "symbol",
    "stt",
    "id",
    "_id",
    "statement type",
    "statement_type",
}


_INLINE_UNIT_PATTERN = (
    r"triệu\s*(?:đồng|vnd|vnđ)?|nghìn\s*(?:đồng|vnd|vnđ)?|"
    r"đồng|vnd|vnđ"
)
_INLINE_PERIOD_VALUE_RE = re.compile(
    r"(?P<raw>\(?-?[\d][\d., ]*\)?|[-–—−])\s*"
    # OCR/LLM Markdown often puts the unit in its own parentheses before
    # the parenthesized period: ``123 (đồng) (Ngày 31 ... 2025)``.
    r"(?:\(\s*(?P<unit_paren>" + _INLINE_UNIT_PATTERN + r")\s*\)"
    r"|(?P<unit_plain>" + _INLINE_UNIT_PATTERN + r"))?\s*"
    r"\(\s*(?P<period>(?:\d{1,2}[./-]\d{1,2}[./-]20\d{2}|"
    r"(?:ngày\s+|ngay\s+)?\d{1,2}\s+(?:tháng|thang)\s+\d{1,2}\s+"
    r"(?:năm|nam)\s+20\d{2}|20\d{2})"
    r"(?:\s*,[^)]*)?)\s*\)",
    re.I,
)


_EXPLICIT_DATE_OR_YEAR_RE = re.compile(
    r"(?:\b20\d{2}\b|\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b|"
    r"\b(?:ngày|ngay)\s+\d{1,2}\s+(?:tháng|thang)\s+\d{1,2}\s+"
    r"(?:năm|nam)\s+20\d{2}\b)",
    re.I,
)


@dataclass
class _InlineValue:
    raw: str
    period_label: str
    period_role: str | None
    unit: str | None
    source_column: int


def _inline_period_values(
    raw_value: str,
    *,
    current_year: int | None,
    previous_year: int | None,
) -> list[_InlineValue]:
    """Parse only number/date pairs that are explicit in one source line.

    The date marker is required on purpose.  A prose sentence containing two
    numbers must stay narrative instead of being promoted to financial data.
    """

    matches = list(_INLINE_PERIOD_VALUE_RE.finditer(raw_value or ""))
    if not matches:
        return []
    remainder = _INLINE_PERIOD_VALUE_RE.sub("", raw_value or "")
    remainder = re.sub(r"[\s,;]+", "", remainder)
    if remainder:
        return []

    result: list[_InlineValue] = []
    for column, match in enumerate(matches, start=1):
        period_label = match.group("period").strip()
        period_role = _period_role(
            period_label,
            current_year=current_year,
            previous_year=previous_year,
        )
        if period_role is None:
            # The common period helper recognizes the full Vietnamese form;
            # retry a stable wrapper for a bare date/year emitted by Markdown.
            period_role = _period_role(
                f"Năm kết thúc {period_label}",
                current_year=current_year,
                previous_year=previous_year,
            )
        result.append(_InlineValue(
            raw=match.group("raw").strip(),
            period_label=period_label,
            period_role=period_role,
            unit=(match.group("unit_paren") or match.group("unit_plain") or None),
            source_column=column,
        ))
    return result


def _nested_label_value(label: str, raw_value: str) -> tuple[str, str, str | None]:
    """Unwrap ``Triệu VND: Nợ đủ tiêu chuẩn: 123`` without losing context."""

    if fold_text(label) not in {"trieu vnd", "trieu dong", "nghin vnd", "nghin dong"}:
        return label, raw_value, None
    match = re.match(r"(?P<label>.+?)\s*:\s*(?P<value>\(?-?[\d][\d., ]*\)?|[-–—−])\s*$", raw_value or "")
    if not match:
        return label, raw_value, None
    return match.group("label").strip(), match.group("value").strip(), label


def _token_label(body: str) -> str:
    match = KV_RE.match(body)
    if match:
        return _strip_md(match.group("label")).rstrip(":").strip()
    return _strip_md(body).rstrip(":").strip()


def _infer_measure(label: str) -> str | None:
    folded = fold_text(label)
    if "gia tri ghi so" in folded or "gia tri thuan" in folded or "con lai" in folded:
        return "carrying_amount"
    if "gia goc" in folded or "nguyen gia" in folded:
        return "cost"
    if "du phong" in folded:
        return "provision"
    if "gia tri" in folded:
        return "value"
    return None


def _is_metadata_leaf(label: str, full_path: list[str]) -> bool:
    folded = fold_text(label)
    if folded in METADATA_LABELS:
        return True
    path = {fold_text(x) for x in full_path}
    return bool(path & {"metadata", "frontmatter", "source metadata"})


def _movement_role(label: str) -> str | None:
    """Extend the shared movement vocabulary without changing primary parsers."""

    role = infer_movement_role(label)
    if role:
        return role
    folded = fold_text(label)
    if "so phai nop" in folded or "dieu chinh trong nam" in folded:
        return "addition"
    if "so da nop" in folded or "da nop trong nam" in folded:
        return "payment"
    if "co tuc duoc chia" in folded:
        return "distribution"
    if "loi nhuan thuoc ve" in folded:
        return "profit_attribution"
    return None


def _build_tokens(section_text: str, base_line: int, occupied_lines: set[int]) -> list[dict]:
    tokens: list[dict] = []
    for idx, raw in enumerate(section_text.splitlines()):
        line = base_line + idx
        if line in occupied_lines:
            continue
        match = BULLET_RE.match(raw)
        if not match:
            continue
        tokens.append({
            "idx": idx,
            "line": line,
            "indent": _indent_width(match.group("indent")),
            "body": _strip_md(match.group("body")),
            "raw": raw,
            "parent": None,
        })

    stack: list[int] = []
    for pos, token in enumerate(tokens):
        while stack and tokens[stack[-1]]["indent"] >= token["indent"]:
            stack.pop()
        token["parent"] = stack[-1] if stack else None
        token["pos"] = pos
        stack.append(pos)
    return tokens


def _ancestors(tokens: list[dict], pos: int) -> list[int]:
    out: list[int] = []
    parent = tokens[pos]["parent"]
    while parent is not None:
        out.append(parent)
        parent = tokens[parent]["parent"]
    out.reverse()
    return out


def _period_context(
    tokens: list[dict],
    pos: int,
    *,
    current_year: int | None,
    previous_year: int | None,
) -> tuple[str | None, str | None, int | None]:
    """Find the nearest exact period label, including a panel ancestor."""

    candidates = [pos] + list(reversed(_ancestors(tokens, pos)))
    for candidate in candidates:
        label = _token_label(tokens[candidate]["body"])
        role = _structural_period_role(
            label,
            current_year=current_year,
            previous_year=previous_year,
        )
        if role:
            return role, label, candidate
    return None, None, None


def _structural_period_role(
    label: str,
    *,
    current_year: int | None,
    previous_year: int | None,
) -> str | None:
    """Return a period role only for a period marker, not a measure heading.

    ``ground_truth_quality.period_role`` intentionally recognizes ``lũy kế``
    as a non-primary reporting window.  In a Notes tree, however, labels such
    as ``Giá trị khấu hao lũy kế`` are measures/sections, not period panels.
    Treating those labels as periods removes the parent from
    ``hierarchy_path`` and assigns the measure name as the value's period.

    A cumulative window is still accepted when it is explicitly introduced
    as a window (``Lũy kế từ đầu năm``, ``YTD``...) or carries an actual date
    or year.  This keeps the correction narrow and avoids changing the shared
    period semantics used by the primary statements.
    """

    folded = fold_text(_strip_md(label)).strip(" :")
    if "luy ke" in folded and not (
        folded.startswith((
            "luy ke",
            "cumulative",
            "year to date",
            "ytd",
        ))
        or _EXPLICIT_DATE_OR_YEAR_RE.search(folded)
    ):
        return None
    return _period_role(
        label,
        current_year=current_year,
        previous_year=previous_year,
    )


def _base_hierarchy(
    tokens: list[dict],
    pos: int,
    *,
    current_year: int | None,
    previous_year: int | None,
) -> tuple[list[str], list[str]]:
    """Return ``(period-free path, full path)`` for one numeric leaf."""

    path_positions = _ancestors(tokens, pos)
    full_path = [_token_label(tokens[x]["body"]) for x in path_positions]
    base_path = []
    for ancestor, label in zip(path_positions, full_path):
        if _structural_period_role(
            label,
            current_year=current_year,
            previous_year=previous_year,
        ):
            continue
        base_path.append(label)
    return base_path, full_path


def _row_role_for_value(
    label: str,
    movement_role: str | None,
    *,
    current_year: int | None,
    previous_year: int | None,
) -> str:
    if movement_role == "opening":
        return "opening"
    if movement_role == "closing":
        return "closing"
    if movement_role:
        return "movement"
    return _row_role(label, current_year=current_year, previous_year=previous_year)


def parse_bullet_structures_v2(
    section_text: str,
    base_line: int,
    block_prefix: str,
    *,
    occupied_lines: set[int] | None = None,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> list[NoteBlock]:
    """Parse every numeric bullet leaf while retaining all Notes dimensions.

    Rows are grouped by the period-free hierarchy path and leaf label.  This
    pairs repeated measures across date/panel ancestors when they are truly
    the same source item, while retaining movement rows and unpaired values.
    """

    occupied_lines = occupied_lines or set()
    tokens = _build_tokens(section_text, base_line, occupied_lines)
    if not tokens:
        return []

    groups: dict[tuple[tuple[str, ...], str], list[NoteRow]] = {}
    row_roots: dict[int, int] = {}
    row_lines: defaultdict[int, list[int]] = defaultdict(list)

    for pos, token in enumerate(tokens):
        match = KV_RE.match(token["body"])
        if not match:
            continue

        label = _strip_md(match.group("label")).rstrip(":").strip()
        raw_value, unit = _split_numeric_unit(match.group("value"))
        label, raw_value, nested_unit = _nested_label_value(label, raw_value)
        unit = unit or nested_unit

        base_path, full_path = _base_hierarchy(
            tokens,
            pos,
            current_year=current_year,
            previous_year=previous_year,
        )
        if _is_metadata_leaf(label, full_path):
            continue
        period_role, period_label, period_position = _period_context(
            tokens,
            pos,
            current_year=current_year,
            previous_year=previous_year,
        )
        movement_role = _movement_role(" > ".join(full_path + [label]))
        measure = _infer_measure(label)
        row_role = _row_role_for_value(
            label,
            movement_role,
            current_year=current_year,
            previous_year=previous_year,
        )

        inline_values = _inline_period_values(
            raw_value,
            current_year=current_year,
            previous_year=previous_year,
        )
        if inline_values:
            value_specs = [
                (x.raw, parse_number(x.raw), x.period_label, x.period_role, x.unit, x.source_column)
                for x in inline_values
            ]
        else:
            normalized = parse_number(raw_value)
            if normalized is None and raw_value not in DASHES:
                continue
            value_specs = [(raw_value, normalized, period_label, period_role, unit, None)]

        key = (tuple(fold_text(x) for x in base_path), fold_text(label))
        candidates = groups.setdefault(key, [])

        def _can_extend(candidate: NoteRow, candidate_role: str | None) -> bool:
            """Pair current/previous panels, but never collapse same-period rows."""

            if not candidate.values:
                return True
            roles = {value.period_role for value in candidate.values}
            if candidate_role is None:
                # No period evidence means repeated source rows are distinct;
                # keeping them separate is safer than inventing a pairing.
                return False
            return candidate_role not in roles

        root = pos
        while tokens[root]["parent"] is not None:
            root = tokens[root]["parent"]

        touched_rows: set[int] = set()
        for raw_item, normalized, item_period_label, item_period_role, item_unit, source_column in value_specs:
            effective_period_role = item_period_role or period_role
            effective_period_label = item_period_label or period_label
            row = next(
                (
                    candidate
                    for candidate in candidates
                    if _can_extend(candidate, effective_period_role)
                ),
                None,
            )
            if row is None:
                row = NoteRow(
                    label_raw=label,
                    label_normalized=fold_text(label),
                    values=[],
                    row_role=row_role,
                    hierarchy_path=base_path,
                    source_line=token["line"],
                    raw_cells=[label],
                    metadata={
                        "parser": "notes_tree_values_v2",
                        "full_hierarchy_preserved": True,
                        "period_ancestor_lines": [],
                        "raw_source_lines": [],
                        "value_sequence": [],
                    },
                )
                candidates.append(row)
                row_roots[id(row)] = root

            value = NoteValue(
                raw=raw_item,
                normalized=normalized,
                period_label=effective_period_label,
                period_role=effective_period_role,
                movement_role=movement_role,
                measure=measure,
                unit=item_unit or unit,
                source_line=token["line"],
                source_column=source_column,
                source_context=full_path + [label],
            )
            row.values.append(value)
            row.raw_cells.append(raw_item)
            touched_rows.add(id(row))
            row.metadata["value_sequence"].append({
                "raw": raw_item,
                "period_label": effective_period_label,
                "period_role": effective_period_role,
                "source_column": source_column,
            })

        for row in candidates:
            if id(row) not in touched_rows:
                continue
            row.metadata["raw_source_lines"].append(token["raw"])
            row_lines[id(row)].append(token["line"])
            if period_position is not None:
                row.metadata.setdefault("period_ancestor_lines", []).append(tokens[period_position]["line"])
            if nested_unit:
                row.metadata["nested_unit_label"] = nested_unit

    if not groups:
        return []

    # Keep separate source blocks by top-level bullet root. A row that spans
    # two period panels belongs to the first root but its source range covers
    # both panels, so block occupancy never leaves the second value behind as
    # narrative text.
    rows_by_root: defaultdict[int, list[NoteRow]] = defaultdict(list)
    for rows_for_key in groups.values():
        for row in rows_for_key:
            rows_by_root[row_roots[id(row)]].append(row)

    blocks: list[NoteBlock] = []
    for block_no, (root, keyed_rows) in enumerate(rows_by_root.items(), start=1):
        rows = list(keyed_rows)
        root_line = tokens[root]["line"]
        source_lines = [root_line]
        for row in keyed_rows:
            source_lines.extend(row_lines[id(row)])
        block = NoteBlock(
            block_id=f"{block_prefix}:bullet_tree_{block_no}",
            form="bullet_list",
            semantic_shape="movement" if any(v.movement_role for r in rows for v in r.values) else "breakdown",
            source_start_line=min(source_lines),
            source_end_line=max(source_lines),
            rows=rows,
            metadata={
                "parser": "notes_tree_values_v2",
                "value_granularity": "numeric_leaf",
                "periods_are_dimensions": True,
                "unpaired_values_preserved": True,
                "root_label": _token_label(tokens[root]["body"]),
                "row_count": len(rows),
            },
        )
        blocks.append(block)

    return blocks
