from __future__ import annotations

from .models import ResolvedField
from .semantic_catalog import SemanticCatalog


def _value_signature(value) -> tuple[str, str]:
    """So sánh payload trùng bằng giá trị đã chuẩn hóa nếu có."""

    if value.normalized_candidate is not None:
        return "normalized", str(value.normalized_candidate)
    return "raw", (value.raw_value or "").strip().casefold()


def map_first_value_per_period(
    fields: list[ResolvedField],
    catalog: SemanticCatalog,
):
    """Tạo node canonical và vẫn giữ bằng chứng trùng lặp.

    Chính sách loại trùng mặc định:
      - giá trị non-null/raw đầu tiên của mỗi node_id + period_key được giữ;
      - occurrence sau không ghi đè một kỳ đã có;
      - occurrence xung đột được ghi làm bằng chứng cần xem xét;
      - occurrence sau có thể điền kỳ còn thiếu ở occurrence đầu;
      - thuyết minh/mã đầu tiên cũng được giữ.

    Cách này an toàn hơn ghi đè cả node mà vẫn giữ nguyên quy tắc "giá trị đầu tiên".
    """
    canonical = catalog.clone_schema()
    node_map = {x["node_id"]: x for x in canonical["nodes"]}

    state = {}
    accepted = []
    duplicate_log = []

    for field in sorted(fields, key=lambda x: x.source_line):
        target = node_map.get(field.node_id)
        if target is None:
            continue

        st = state.setdefault(
            field.node_id,
            {
                "periods": set(),
                "note_set": False,
                "code_set": False,
                "first_line": field.source_line,
                "has_any_payload": False,
                "raw_by_period": {},
                "conflict_periods": [],
            },
        )

        value_obj = target.setdefault("value", {})
        actions = []
        accepted_any = False

        if field.source_context:
            target.setdefault("source_context", field.source_context)

        for v in field.values:
            lock_key = v.period_key
            if lock_key in st["periods"]:
                existing = st["raw_by_period"].get(lock_key)
                incoming = _value_signature(v)
                if existing is not None and existing["signature"] != incoming:
                    conflict = {
                        "period_key": lock_key,
                        "first_source_line": existing["source_line"],
                        "conflicting_source_line": field.source_line,
                        "first_raw_value": existing["raw_value"],
                        "conflicting_raw_value": v.raw_value,
                    }
                    if conflict not in st["conflict_periods"]:
                        st["conflict_periods"].append(conflict)
                    actions.append({
                        "action": "conflict_existing_period",
                        **conflict,
                    })
                else:
                    actions.append({
                        "action": "skip_existing_period",
                        "period_key": lock_key,
                        "raw_value": v.raw_value,
                        "source_line": field.source_line,
                    })
                continue

            st["periods"].add(lock_key)
            st["raw_by_period"][lock_key] = {
                "signature": _value_signature(v),
                "raw_value": v.raw_value,
                "source_line": field.source_line,
            }
            st["has_any_payload"] = True
            accepted_any = True

            if lock_key == "current":
                value_obj["current"] = v.raw_value
            elif lock_key == "previous":
                value_obj["previous"] = v.raw_value
            else:
                additional = value_obj.get("additional")
                if not isinstance(additional, dict):
                    additional = {}
                additional[lock_key] = v.raw_value
                value_obj["additional"] = additional

            actions.append({
                "action": "accept_first_period_value",
                "period_key": lock_key,
                "raw_value": v.raw_value,
                "source_line": field.source_line,
            })

        if field.note is not None:
            if not st["note_set"]:
                value_obj["note"] = field.note
                st["note_set"] = True
                st["has_any_payload"] = True
                accepted_any = True
                actions.append({"action": "accept_first_note", "value": field.note})
            else:
                actions.append({"action": "skip_existing_note", "value": field.note})

        # Mã biểu mẫu là metadata, không phải khóa mapping semantic.
        code_accepted = False
        if field.code is not None and not st["code_set"]:
            st["code_set"] = True
            code_accepted = True
            accepted_any = True
            actions.append({"action": "accept_first_code", "value": field.code})
        elif field.code is not None:
            actions.append({"action": "skip_existing_code", "value": field.code})

        # Chỉ giữ raw_text từ occurrence payload đầu tiên được nhận.
        if accepted_any and not value_obj.get("raw_text"):
            value_obj["raw_text"] = field.source_label

        if accepted_any:
            accepted.append(field)

        duplicate_log.append({
            "node_id": field.node_id,
            "source_line": field.source_line,
            "source_label": field.source_label,
            "actions": actions,
        })

        # Extraction meta là provenance chỉ ghi thêm; giá trị canonical dùng
        # occurrence đầu tiên, còn phương án xung đột vẫn nằm trong audit
        # occurrence và khiến báo cáo canonical cần xem xét.
        meta = target.setdefault("extraction_meta", {
            "policy": "first_value_per_period_wins",
            "occurrences": [],
        })
        meta["occurrences"].append({
            "source_line": field.source_line,
            "source_label": field.source_label,
            "pattern_id": field.pattern_id,
            "pattern_name": field.pattern_name,
            "alias_method": field.alias_method,
            "confidence": field.confidence,
            "code_candidate": field.code,
            "note_candidate": field.note,
            "source_context": field.source_context,
            "values": [
                {
                    "period_key": v.period_key,
                    "period_label": v.period_label,
                    "raw_value": v.raw_value,
                    "normalized_candidate": v.normalized_candidate,
                    "is_dash": (v.raw_value.strip() in {"-", "–", "—", "−"}),
                    "unit": v.unit,
                    "role": v.role,
                    "provenance": v.provenance,
                    "source_line": v.source_line,
                }
                for v in field.values
            ],
            "actions": actions,
        })

    conflict_nodes = [
        node_id for node_id, state_item in state.items()
        if state_item.get("conflict_periods")
    ]
    canonical.setdefault("diagnostics", {})["semantic_dedup"] = {
        "policy": "first_value_per_period_wins_with_conflict_audit",
        "conflicting_nodes": conflict_nodes,
        "conflict_count": sum(
            len(state_item.get("conflict_periods") or [])
            for state_item in state.values()
        ),
    }
    if conflict_nodes:
        # Giữ giá trị nguồn đầu tiên để tương thích, nhưng nêu rõ trạng thái
        # mơ hồ. Toàn bộ bằng chứng xung đột vẫn nằm trong extraction_meta và
        # lớp source-observation.
        canonical["status"] = "review_required"
        for node_id in conflict_nodes:
            node = node_map.get(node_id)
            if node is None:
                continue
            node["mapping"] = {
                "status": "review_required",
                "target_id": node_id,
                "method": "semantic_dedup_conflict",
                "confidence": None,
            }

    return canonical, accepted, duplicate_log
