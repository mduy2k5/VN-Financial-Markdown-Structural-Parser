from __future__ import annotations

from copy import deepcopy

from .models import ResolvedField


def _compatible_occurrences(a: ResolvedField, b: ResolvedField) -> bool:
    if a.node_id != b.node_id:
        return False
    if a.source_label.strip().casefold() != b.source_label.strip().casefold():
        return False
    # Giữ phạm vi gộp cục bộ: dòng lặp theo vị trí thường nằm gần nhau.
    return abs(a.source_line - b.source_line) <= 8


def consolidate_resolved_fields(
    fields: list[ResolvedField],
    context,
) -> tuple[list[ResolvedField], list[dict]]:
    """
    Gộp các occurrence một giá trị lặp lại trước khi loại trùng canonical.

    Dạng serialize thường gặp:
      Tiền gửi tại các TCTD khác: 25.819.775
      Tiền gửi tại các TCTD khác: 12.454.527

    trong context hai cột [hiện tại, trước đây].

    Occurrence đầu -> hiện tại
    occurrence thứ hai -> trước đây
    """
    fields = sorted(fields, key=lambda x: x.source_line)
    out = []
    log = []
    i = 0

    while i < len(fields):
        cur = deepcopy(fields[i])

        if (
            i + 1 < len(fields)
            and _compatible_occurrences(cur, fields[i + 1])
            and len(cur.values) == 1
            and len(fields[i + 1].values) == 1
        ):
            nxt = deepcopy(fields[i + 1])
            v1 = cur.values[0]
            v2 = nxt.values[0]

            # Chỉ gộp khi CẢ HAI occurrence đến từ suy luận theo vị trí.
            # Kỳ explicit/inherited đã có ngữ nghĩa đáng tin và không được
            # viết lại chỉ vì các nhãn giống nhau nằm gần nhau.
            if (
                v1.period_key in {"current", "previous"}
                and v2.period_key in {"current", "previous"}
                and v1.provenance in {"positional_context", "consolidated_repeated_label"}
                and v2.provenance in {"positional_context", "consolidated_repeated_label"}
            ):
                v1.period_key = "current"
                v1.period_label = context.current_label
                v1.role = "current"
                v1.provenance = "consolidated_repeated_label"

                v2.period_key = "previous"
                v2.period_label = context.previous_label
                v2.role = "previous"
                v2.provenance = "consolidated_repeated_label"

                cur.values = [v1, v2]
                cur.warnings = list(cur.warnings) + ["merged_repeated_label_rows"]
                log.append({
                    "node_id": cur.node_id,
                    "source_lines": [cur.source_line, nxt.source_line],
                    "action": "merge_repeated_label_rows",
                })
                out.append(cur)
                i += 2
                continue

        out.append(cur)
        i += 1

    return out, log
