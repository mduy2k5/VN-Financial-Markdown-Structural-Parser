from __future__ import annotations

from .models import ResolvedField
from .semantic_catalog import SemanticCatalog


def map_first_value_per_period(
    fields: list[ResolvedField],
    catalog: SemanticCatalog,
):
    """
    Default dedup policy:
      - first non-null/raw value found for each node_id + period_key wins;
      - later duplicates never overwrite an existing period;
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
            },
        )

        value_obj = target.setdefault("value", {})
        actions = []
        accepted_any = False

        for v in field.values:
            lock_key = v.period_key
            if lock_key in st["periods"]:
                actions.append({
                    "action": "skip_existing_period",
                    "period_key": lock_key,
                    "raw_value": v.raw_value,
                    "source_line": field.source_line,
                })
                continue

            st["periods"].add(lock_key)
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

        # Extraction meta is append-only provenance; canonical value itself is first-wins.
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

    return canonical, accepted, duplicate_log
