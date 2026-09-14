from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .alias_matcher import choose_candidate
from .mapping_strategy import match_candidates_for_strategy
from .canonical_mapper import map_first_value_per_period
from .models import ResolvedField, ResolvedValue, StructuralNode
from .semantic_catalog import SemanticCatalog


def _synthetic_nodes(rows):
    nodes = []
    for idx, row in enumerate(rows):
        nodes.append(
            StructuralNode(
                node_index=idx,
                line_no=row.source_start_line or idx + 1,
                raw_text="\n".join(row.raw_lines or []),
                text=row.indicator,
                indent=0,
                is_bullet=True,
                bullet_marker="*",
                representation="bullet_debug",
                label_text=row.indicator,
                pattern_id=row.pattern_id,
                pattern_name=row.pattern_id,
            )
        )
    return nodes


def map_debug_rows_to_canonical(
    rows,
    *,
    schema_path: str | Path,
    aliases_path: str | Path,
    allow_fuzzy: bool = False,
    detected_sector: str | None = None,
    mapping_strategy: str = "legacy",
):
    """Map already-resolved bullet rows through the existing v0.5 alias/schema catalog.

    Structural extraction remains owned by BulletDebugFlow. This adapter only performs
    semantic mapping and uses the existing first-value-per-period canonical mapper.
    """
    catalog = SemanticCatalog(schema_path, aliases_path)
    nodes = _synthetic_nodes(rows)
    prior_selected: list[tuple[int, str, str]] = []
    resolved: list[ResolvedField] = []
    mapping_log = []
    unresolved = []

    for idx, (row, node) in enumerate(zip(rows, nodes)):
        candidates = match_candidates_for_strategy(
            mapping_strategy,
            node,
            nodes,
            catalog,
            prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
        )
        selected, reason = choose_candidate(candidates)
        log = {
            "source_line": row.source_start_line,
            "source_label": row.indicator,
            "pattern_id": row.pattern_id,
            "current": row.current,
            "previous": row.previous,
            "note": row.note,
            "unit": row.unit,
            "status": "mapped" if selected else "unmapped",
            "reason": reason,
            "top_candidates": [
                {
                    "node_id": c.node_id,
                    "canonical_name": c.canonical_name,
                    "method": c.method,
                    "matched_alias": c.matched_alias,
                    "alias_score": c.alias_score,
                    "context_score": c.context_score,
                    "final_score": c.final_score,
                    "evidence": c.evidence,
                }
                for c in candidates[:5]
            ],
        }
        if not selected:
            unresolved.append(log)
            mapping_log.append(log)
            continue

        values = []
        if row.current != "":
            values.append(
                ResolvedValue(
                    period_key="current",
                    period_label="current",
                    raw_value=row.current,
                    normalized_candidate=None,
                    unit=row.unit or None,
                    role="current",
                    provenance="bullet_flow",
                    source_line=row.source_start_line,
                )
            )
        if row.previous != "":
            values.append(
                ResolvedValue(
                    period_key="previous",
                    period_label="previous",
                    raw_value=row.previous,
                    normalized_candidate=None,
                    unit=row.unit or None,
                    role="previous",
                    provenance="bullet_flow",
                    source_line=row.source_start_line,
                )
            )

        field = ResolvedField(
            node_id=selected.node_id,
            canonical_name=selected.canonical_name,
            source_label=row.indicator,
            source_line=row.source_start_line,
            kind=selected.kind,
            sector=selected.sector,
            pattern_id=row.pattern_id,
            pattern_name=row.pattern_id,
            alias_method=selected.method,
            confidence=min(1.0, max(0.0, selected.final_score)),
            values=values,
            note=row.note or None,
            code=None,
            unit=row.unit or None,
            warnings=[],
        )
        resolved.append(field)
        prior_selected.append((row.source_start_line, selected.node_id, row.indicator))
        log.update({
            "node_id": selected.node_id,
            "canonical_name": selected.canonical_name,
            "alias_method": selected.method,
            "confidence": field.confidence,
        })
        mapping_log.append(log)

    canonical, accepted, dedup_log = map_first_value_per_period(resolved, catalog)
    value_nodes = [
        n for n in canonical.get("nodes", [])
        if any((n.get("value") or {}).get(k) is not None for k in ("current", "previous"))
    ]
    stats = {
        "input_rows": len(rows),
        "mapped_rows": len(resolved),
        "unmapped_rows": len(unresolved),
        "mapping_rate": round(len(resolved) / len(rows), 6) if rows else 0.0,
        "canonical_value_nodes": len(value_nodes),
        "current_value_nodes": sum(1 for n in value_nodes if (n.get("value") or {}).get("current") is not None),
        "previous_value_nodes": sum(1 for n in value_nodes if (n.get("value") or {}).get("previous") is not None),
        "accepted_occurrences": len(accepted),
    }
    return {
        "canonical": canonical,
        "debug": {
            "mapping_log": mapping_log,
            "unresolved_mapping": unresolved,
            "dedup_log": dedup_log,
            "stats": stats,
        },
    }


def enrich_existing_canonical(
    base_canonical,
    rows,
    *,
    schema_path: str | Path,
    aliases_path: str | Path,
    allow_fuzzy: bool = False,
    detected_sector: str | None = None,
    mapping_strategy: str = "legacy",
):
    """Conservative hybrid enrichment.

    The v0.5 canonical output is authoritative. Bullet rows may only fill missing
    current/previous/note slots. Existing values are never overwritten.
    """
    import copy
    catalog = SemanticCatalog(schema_path, aliases_path)
    canonical = copy.deepcopy(base_canonical)
    node_map = {n.get("node_id"): n for n in canonical.get("nodes", [])}
    nodes = _synthetic_nodes(rows)
    prior_selected = []
    logs = []
    enriched_nodes = set()
    filled_periods = 0
    filled_notes = 0
    conflicts = 0
    accepted_rows = 0

    for row, node in zip(rows, nodes):
        candidates = match_candidates_for_strategy(
            mapping_strategy,
            node, nodes, catalog, prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
        )
        selected, reason = choose_candidate(candidates)
        gap = None
        if len(candidates) > 1:
            gap = candidates[0].final_score - candidates[1].final_score

        # Hybrid enrichment is deliberately stricter than ordinary v0.5 mapping.
        if selected:
            safe_method = selected.method in {"exact_canonical", "exact", "alias"}
            safe_regex_fallback = selected.method.startswith("regex_fallback_") and selected.final_score >= 0.93
            strong_contains = selected.method == "contains" and selected.final_score >= 1.10
            strong_gap = gap is None or gap >= 0.08
            if not ((safe_method or safe_regex_fallback or strong_contains) and strong_gap):
                reason = "hybrid_guard_low_specificity"
                selected = None

        log = {
            "source_line": row.source_start_line,
            "source_label": row.indicator,
            "pattern_id": row.pattern_id,
            "current": row.current,
            "previous": row.previous,
            "note": row.note,
            "unit": row.unit,
            "candidate_gap": gap,
            "reason": reason,
            "actions": [],
            "top_candidates": [
                {
                    "node_id": c.node_id,
                    "canonical_name": c.canonical_name,
                    "method": c.method,
                    "final_score": c.final_score,
                }
                for c in candidates[:3]
            ],
        }
        if not selected or selected.node_id not in node_map:
            log["status"] = "unmapped"
            logs.append(log)
            continue

        target = node_map[selected.node_id]
        value = target.setdefault("value", {})
        changed = False
        for key, raw in (("current", row.current), ("previous", row.previous)):
            if raw == "":
                continue
            if value.get(key) is None:
                value[key] = raw
                log["actions"].append({"action": "fill_missing_period", "period": key, "value": raw})
                filled_periods += 1
                changed = True
            elif value.get(key) != raw:
                log["actions"].append({"action": "keep_v05_conflict", "period": key, "v05": value.get(key), "bullet": raw})
                conflicts += 1
            else:
                log["actions"].append({"action": "same_as_v05", "period": key, "value": raw})

        if row.note and value.get("note") is None:
            value["note"] = row.note
            log["actions"].append({"action": "fill_missing_note", "value": row.note})
            filled_notes += 1
            changed = True
        if changed and not value.get("raw_text"):
            value["raw_text"] = row.indicator

        meta = target.setdefault("extraction_meta", {"policy": "hybrid_v05_first_bullet_fill", "occurrences": []})
        meta.setdefault("occurrences", []).append({
            "source_line": row.source_start_line,
            "source_label": row.indicator,
            "pattern_id": row.pattern_id,
            "alias_method": selected.method,
            "confidence": selected.final_score,
            "hybrid_actions": log["actions"],
        })
        prior_selected.append((row.source_start_line, selected.node_id, row.indicator))
        log.update({
            "status": "enriched" if changed else "mapped_no_fill",
            "node_id": selected.node_id,
            "canonical_name": selected.canonical_name,
            "alias_method": selected.method,
            "confidence": selected.final_score,
        })
        if changed:
            accepted_rows += 1
            enriched_nodes.add(selected.node_id)
        logs.append(log)

    value_nodes = [
        n for n in canonical.get("nodes", [])
        if any((n.get("value") or {}).get(k) is not None for k in ("current", "previous"))
    ]
    return canonical, {
        "input_rows": len(rows),
        "accepted_enrichment_rows": accepted_rows,
        "enriched_nodes": len(enriched_nodes),
        "filled_periods": filled_periods,
        "filled_notes": filled_notes,
        "conflicts_kept_v05": conflicts,
        "canonical_value_nodes": len(value_nodes),
        "current_value_nodes": sum(1 for n in value_nodes if (n.get("value") or {}).get("current") is not None),
        "previous_value_nodes": sum(1 for n in value_nodes if (n.get("value") or {}).get("previous") is not None),
    }, logs
