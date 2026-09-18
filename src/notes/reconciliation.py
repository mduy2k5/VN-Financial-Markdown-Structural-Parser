from __future__ import annotations

from typing import Optional

from .note_ir import NoteDocument, ReconciliationResult
from .sectionizer import fold_text


def _is_note_total_label(label: str) -> bool:
    """Cho biết nhãn thuyết minh đã chuẩn hóa có thể là tổng hợp lệ hay không.

    Giữ quy tắc thận trọng. Đặc biệt, token ``cong`` cũng xuất hiện trong các
    nhãn thông thường như ``cong ty`` và không được nâng dòng chi tiết thành
    tổng để đối chiếu.
    """
    f = fold_text(label or '').strip()
    if f == 'cong' or f.startswith('tong '):
        return True
    return any(token in f for token in (
        'gia tri con lai',
        'doanh thu thuan',
        'tong chi phi',
        'chi phi thue tndn hien hanh',
    ))


def _sign_convention_match(primary_value, note_value, primary_label: str, note_label: str) -> bool:
    """Nhận diện cùng độ lớn nhưng trái dấu do cách trình bày.

    Báo cáo kết quả kinh doanh dùng quy ước chi phí có dấu trong phép cộng,
    còn thuyết minh đối chiếu thuế thường in chi phí dưới dạng số dương. Đây
    là bằng chứng của cùng một khoản, không phải quyền thay đổi giá trị chính.
    """
    if not isinstance(primary_value, (int, float)) or not isinstance(note_value, (int, float)):
        return False
    if primary_value == note_value or abs(primary_value) != abs(note_value):
        return False
    labels = ' '.join(fold_text(x or '') for x in (primary_label, note_label))
    return any(token in labels for token in ('chi phi', 'thue', 'du phong'))


def _baseline_row_node(row: dict) -> dict:
    """Chuyển row observation đã lưu sang view node chính tối giản dùng ở đây."""
    if isinstance(row.get("value"), dict):
        return row
    observations = row.get("observations") or []
    if not observations:
        return row
    node = dict(row)
    value = {}
    for observation in observations:
        period_key = observation.get("period_key")
        if period_key == "prior":
            period_key = "previous"
        if period_key in {"current", "previous"}:
            value[period_key] = observation.get("value")
    if value:
        node["value"] = value
    return node


def _primary_node_index(primary: Optional[dict]) -> dict[str, dict]:
    out = {}
    if not primary or not isinstance(primary, dict):
        return out

    def consume(prefix, obj):
        canonical = obj.get("canonical") if isinstance(obj, dict) and isinstance(obj.get("canonical"), dict) else obj
        if not isinstance(canonical, dict):
            return
        for n in canonical.get("nodes") or []:
            nid = n.get("node_id")
            if nid:
                out[f"{prefix}:{nid}"] = n

    if isinstance(primary.get("nodes"), list):
        consume("UNKNOWN", primary)
    else:
        for key, obj in primary.items():
            if key == "statements" and isinstance(obj, dict):
                for statement_key, statement in obj.items():
                    if not isinstance(statement, dict):
                        continue
                    for row in statement.get("rows") or []:
                        if isinstance(row, dict) and row.get("row_id"):
                            out[f"{statement_key}:{row['row_id']}"] = _baseline_row_node(row)
                continue
            if isinstance(obj, dict):
                consume(key, obj)
    return out


def _best_note_totals(sections):
    """Trả về candidate tổng đơn giản theo role kỳ, kèm tham chiếu nguồn."""
    out = {}
    if not isinstance(sections, (list, tuple)):
        sections = [sections]
    for section in sections:
        if section is None:
            continue
        for block in section.blocks:
            for row in block.rows:
                is_total = row.row_role == "total" or _is_note_total_label(row.label_normalized)
                if not is_total:
                    continue
                for val in row.values:
                    if val.normalized is None:
                        continue
                    role = val.period_role
                    if role in {"current", "previous"}:
                        out.setdefault(role, []).append((
                            val.normalized,
                            f"{section.ref}:{block.block_id}:{row.source_line}",
                            row.label_normalized,
                        ))
    return out


def _sections_for_source_ref(doc: NoteDocument, source_ref: str):
    exact = [section for section in doc.sections if section.ref == source_ref]
    if exact:
        return exact
    if source_ref.startswith("NOTE:"):
        logical = source_ref.removeprefix("NOTE:").split("@L", 1)[0]
        return [section for section in doc.sections if section.note_id_normalized == logical]
    return []


def reconcile_notes(doc: NoteDocument, primary: Optional[dict] = None) -> list[ReconciliationResult]:
    """Đối chiếu không phá hủy dữ liệu.

    Chính sách:
      - giá trị báo cáo chính vẫn có thẩm quyền;
      - tổng thuyết minh bằng nhau được xác nhận;
      - xung đột chỉ được báo cáo, không ghi đè;
      - không sửa giá trị chính đang thiếu ở đây. Việc khôi phục phải là quyết
        định rõ ràng ở bước sau dựa trên liên kết chính xác và đối chiếu chính xác.
    """
    index = _primary_node_index(primary)
    results = []

    for link in doc.links:
        if link.confidence < 0.95 or link.target_ref not in index:
            continue
        sections = _sections_for_source_ref(doc, link.source_ref)
        if not sections:
            continue
        totals = _best_note_totals(sections)
        node = index[link.target_ref]
        pv = node.get("value") or {}

        for period in ("current", "previous"):
            primary_value = pv.get(period)
            candidates = totals.get(period, [])
            if not candidates:
                results.append(ReconciliationResult(
                    source_ref=link.source_ref,
                    target_ref=link.target_ref,
                    status="no_note_total",
                    period=period,
                    primary_value=primary_value,
                    evidence=["explicit_link_but_no_simple_total"],
                ))
                continue

            # Ưu tiên khớp chính xác. Một tổng chi phí/thuế có cùng độ lớn cũng
            # được xác nhận khi báo cáo chính dùng quy ước chi phí có dấu còn
            # thuyết minh in số dương.
            exact = [x for x in candidates if primary_value is not None and x[0] == primary_value]
            sign_normalized = False
            if exact:
                note_value = exact[0][0]
                status = "confirmed"
                evidence = ["explicit_link", "exact_amount_match", exact[0][1]]
            else:
                sign_exact = [
                    x for x in candidates
                    if _sign_convention_match(primary_value, x[0], node.get("label"), x[2])
                ] if primary_value is not None else []
                if len(sign_exact) == 1:
                    note_value = sign_exact[0][0]
                    status = "confirmed"
                    sign_normalized = True
                    evidence = [
                        "explicit_link",
                        "absolute_amount_match",
                        "sign_convention_difference",
                        sign_exact[0][1],
                    ]
                elif len(candidates) == 1:
                    note_value = candidates[0][0]
                    if primary_value is None:
                        status = "recoverable_candidate"
                        evidence = ["explicit_link", "unique_note_total", "primary_missing", candidates[0][1]]
                    else:
                        status = "conflict"
                        evidence = ["explicit_link", "unique_note_total_mismatch", candidates[0][1]]
                else:
                    note_value = None
                    status = "ambiguous_note_totals"
                    evidence = ["explicit_link", f"candidate_count:{len(candidates)}"]

            diff = None
            if isinstance(primary_value, (int, float)) and isinstance(note_value, (int, float)):
                diff = note_value - primary_value

            metadata = {"policy": "PRIMARY_GT_NOTES_non_destructive_v1"}
            if sign_normalized:
                metadata.update({
                    "comparison_basis": "absolute_amount",
                    "raw_difference": diff,
                })
                diff = 0

            results.append(ReconciliationResult(
                source_ref=link.source_ref,
                target_ref=link.target_ref,
                status=status,
                period=period,
                primary_value=primary_value,
                note_value=note_value,
                difference=diff,
                unit_status="not_scaled",
                evidence=evidence,
                metadata=metadata,
            ))

    doc.reconciliation = results
    return results
