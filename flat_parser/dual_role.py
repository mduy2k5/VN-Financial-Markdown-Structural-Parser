from __future__ import annotations

from copy import deepcopy

from .models import ResolvedField
from .textnorm import fold


DUAL_ROLE_TOTALS = {
    "no phai tra": ("LIABILITY", "TOTAL_LIABILITIES"),
    "von chu so huu": ("EQUITY", "TOTAL_EQUITY"),
}



def _has_local_total_payload(field: ResolvedField) -> bool:
    if not field.values:
        return False

    deltas = [v.source_line - field.source_line for v in field.values]

    # Self-contained table/pipe rows keep values on the same source line.
    if field.pattern_id in {
        "SP_MARKDOWN_TABLE_ROW",
        "SP_PIPE_DELIMITED_INLINE_ROW",
        "SP_LABEL_VALUE_INLINE",
    }:
        return all(abs(d) <= 1 for d in deltas)

    # Wrapper/period-child serialization is valid only when ALL values are
    # immediately local to the section row. This accepts:
    #   C - NỢ PHẢI TRẢ -> Chỉ tiêu -> Số cuối năm/Số đầu năm
    # but rejects a structural section that accidentally collected values
    # from distant semantic descendants.
    if all(0 <= d <= 2 for d in deltas):
        return True
    return bool(field.code) and all(0 <= d <= 4 for d in deltas)



def expand_dual_role_rows(fields: list[ResolvedField], catalog):
    """
    Enterprise rows such as:
      C - NỢ PHẢI TRẢ | 300 | ...values...
      D - VỐN CHỦ SỞ HỮU | 400 | ...values...

    open section context but numeric payload belongs to TOTAL_* node.
    """
    out = []
    log = []

    for f in fields:
        label = fold(f.source_label)
        matched = None
        for key, pair in DUAL_ROLE_TOTALS.items():
            if label == key:
                matched = pair
                break

        if not matched:
            if f.kind == "section" and f.values:
                section_only = deepcopy(f)
                section_only.values = []
                section_only.warnings = list(section_only.warnings) + ["section_payload_suppressed"]
                out.append(section_only)
            else:
                out.append(f)
            continue

        if not _has_local_total_payload(f):
            section_only = deepcopy(f)
            section_only.values = []
            section_only.warnings = list(section_only.warnings) + ["nonlocal_section_payload_suppressed"]
            out.append(section_only)
            continue

        section_id, total_id = matched
        # If alias resolution already selected the total node, do not expand
        # it again.  Dual-role conversion is only for a section row carrying
        # a numeric total payload.
        if f.node_id != section_id:
            out.append(f)
            continue

        # Retain section occurrence without direct payload.
        section_copy = deepcopy(f)
        section_copy.node_id = section_id
        if section_id in catalog.nodes:
            section_copy.canonical_name = catalog.nodes[section_id].canonical_name
            section_copy.kind = catalog.nodes[section_id].kind
            section_copy.sector = catalog.nodes[section_id].sector
        section_copy.values = []
        section_copy.note = None

        total_copy = deepcopy(f)
        total_copy.node_id = total_id
        total_copy.alias_method = f"{f.alias_method}+dual_role"
        if total_id in catalog.nodes:
            total_copy.canonical_name = catalog.nodes[total_id].canonical_name
            total_copy.kind = catalog.nodes[total_id].kind
            total_copy.sector = catalog.nodes[total_id].sector

        out.extend([section_copy, total_copy])
        log.append({
            "source_line": f.source_line,
            "source_label": f.source_label,
            "action": "expand_dual_role",
            "section_node_id": section_id,
            "total_node_id": total_id,
        })

    return out, log
