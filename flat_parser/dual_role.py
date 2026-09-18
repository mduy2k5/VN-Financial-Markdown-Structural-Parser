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

    # Dòng bảng/pipe tự chứa giữ giá trị trên cùng dòng nguồn.
    if field.pattern_id in {
        "SP_MARKDOWN_TABLE_ROW",
        "SP_PIPE_DELIMITED_INLINE_ROW",
        "SP_LABEL_VALUE_INLINE",
    }:
        return all(abs(d) <= 1 for d in deltas)

    # Serialize wrapper/child kỳ chỉ hợp lệ khi TẤT CẢ giá trị nằm ngay cạnh
    # dòng section. Điều này chấp nhận:
    #   C - NỢ PHẢI TRẢ -> Chỉ tiêu -> Số cuối năm/Số đầu năm
    # nhưng loại section cấu trúc vô tình lấy giá trị từ descendant semantic xa.
    if all(0 <= d <= 2 for d in deltas):
        return True
    return bool(field.code) and all(0 <= d <= 4 for d in deltas)



def expand_dual_role_rows(fields: list[ResolvedField], catalog):
    """
    Dòng doanh nghiệp như:
      C - NỢ PHẢI TRẢ | 300 | ...values...
      D - VỐN CHỦ SỞ HỮU | 400 | ...values...

    mở context section nhưng payload số thuộc node TOTAL_*.
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
        # Nếu alias đã chọn node tổng, không mở rộng lại. Chuyển đổi dual-role
        # chỉ dành cho dòng section mang payload tổng dạng số.
        if f.node_id != section_id:
            out.append(f)
            continue

        # Giữ occurrence section nhưng bỏ payload trực tiếp.
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
