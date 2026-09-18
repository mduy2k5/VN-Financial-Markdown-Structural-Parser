from __future__ import annotations

from .models import ResolvedField
from .semantic_catalog import SemanticCatalog


def _value_signature(value) -> tuple[str, str]:
    """Compare duplicate payloads by normalized value where available."""

    if value.normalized_candidate is not None:
        return "normalized", str(value.normalized_candidate)
    return "raw", (value.raw_value or "").strip().casefold()


def map_first_value_per_period(
    fields: list[ResolvedField],
    catalog: SemanticCatalog,
):
    """
    Default dedup policy:
      - first non-null/raw value found for each node_id + period_key wins;
      - later duplicates never overwrite an existing period;
      - conflicting later duplicates are recorded as review evidence;
      - later occurrence may fill a period that was missing in the first occurrence;
      - first note/code also wins.

    This is safer than whole-node overwrite while still honoring "first value found".
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

        # form code is metadata, not semantic mapping key.
        code_accepted = False
        if field.code is not None and not st["code_set"]:
            st["code_set"] = True
            code_accepted = True
            accepted_any = True
            actions.append({"action": "accept_first_code", "value": field.code})
        elif field.code is not None:
            actions.append({"action": "skip_existing_code", "value": field.code})

        # Keep raw_text from first accepted payload occurrence only.
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

        # Extraction meta is append-only provenance; canonical value itself is
        # first-wins, while conflicting alternatives remain in the occurrence
        # audit and make the canonical statement review-required.
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
        # Keep the first source value for backward compatibility, but make the
        # ambiguity explicit.  The complete conflicting evidence remains in
        # extraction_meta and the source-observation layer.
        canonical["status"] = "review_required"

    return canonical, accepted, duplicate_log
