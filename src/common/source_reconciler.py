from __future__ import annotations

import collections
import hashlib
from typing import Any

try:
    from .source_recovery import clean, fold
except ImportError:
    from source_recovery import clean, fold


def _value_key(v: Any):
    if isinstance(v, float):
        return round(v, 8)
    return v


def _source_line(node: dict) -> int:
    occ = ((node.get("extraction_meta") or {}).get("occurrences") or [{}])[0]
    return occ.get("source_line") or 10**9


def _group_id(statement: str, section: str, label: str, context: str = "") -> str:
    raw = f"{statement}|{section}|{label}|{context}".encode("utf-8")
    return "SRCGRP." + hashlib.sha1(raw).hexdigest()[:14]


def _period_votes(nodes: list[dict], period: str):
    """Return period vote table using both node value and occurrence evidence.

    A single node value contributes one vote. Occurrence values contribute only when they are
    not identical to the node-level value from the same observation, avoiding accidental double
    weighting of the same evidence.
    """
    votes = collections.Counter()
    support: dict[Any, list[tuple[int, int]]] = collections.defaultdict(list)
    for n in nodes:
        nv = (n.get("value") or {}).get(period)
        if nv is not None:
            k = _value_key(nv)
            both = int((n.get("value") or {}).get("current") is not None and (n.get("value") or {}).get("previous") is not None)
            votes[k] += 1
            support[k].append((both, _source_line(n)))
        seen_occ_values = set()
        for occ in (n.get("extraction_meta") or {}).get("occurrences") or []:
            ov = occ.get(period)
            if ov is None:
                continue
            k = _value_key(ov)
            if k == _value_key(nv) or k in seen_occ_values:
                continue
            seen_occ_values.add(k)
            both = int(occ.get("current") is not None and occ.get("previous") is not None)
            votes[k] += 1
            support[k].append((both, occ.get("source_line") or _source_line(n)))
    return votes, support


def _resolve_period(nodes: list[dict], period: str):
    """Conservative reconciliation.

    - one distinct value: accept it;
    - strict majority: accept majority value;
    - tie/conflict: do not invent a winner.
    """
    votes, support = _period_votes(nodes, period)
    if not votes:
        return None, "missing", {}
    if len(votes) == 1:
        value = next(iter(votes))
        return value, "unanimous", dict(votes)
    ranked = sorted(
        votes,
        key=lambda k: (
            votes[k],
            max((x[0] for x in support[k]), default=0),
            -min((x[1] for x in support[k]), default=10**9),
        ),
        reverse=True,
    )
    top = ranked[0]
    second = ranked[1]
    if votes[top] > votes[second]:
        return top, "majority", dict(votes)
    return None, "conflict", dict(votes)


def _preferred_node(bucket: list[dict], current: Any, previous: Any) -> dict:
    """Choose presentation-preferred source observation without dropping alternatives."""
    def score(n: dict):
        v = n.get("value") or {}
        exact = int((current is None or _value_key(v.get("current")) == _value_key(current)) and
                    (previous is None or _value_key(v.get("previous")) == _value_key(previous)))
        both = int(v.get("current") is not None and v.get("previous") is not None)
        recovered = int(bool((n.get("extraction_meta") or {}).get("source_recovery")))
        return (exact, both, recovered, -_source_line(n))
    return max(bucket, key=score)


def _semantic_candidates(semantic: list[dict], statement: str, section: str, label: str):
    out = []
    for n in semantic:
        if fold(n.get("canonical_name")) != label:
            continue
        if statement == "CASHFLOW" and clean(n.get("section") or "") != section:
            continue
        out.append(n)
    return out


def _node_occurrences(node: dict) -> list[dict]:
    """Return provenance records usable for source-to-semantic linking."""

    meta = node.get("extraction_meta") or {}
    records = []
    for key in ("occurrences", "source_recovery_occurrences"):
        for occurrence in meta.get(key) or []:
            if isinstance(occurrence, dict):
                records.append(occurrence)
    if not records:
        records.append({
            "source_line": _source_line(node) if _source_line(node) < 10**9 else None,
            "source_label": node.get("canonical_name"),
            "current": (node.get("value") or {}).get("current"),
            "previous": (node.get("value") or {}).get("previous"),
        })
    return records


def _record_value(node: dict, occurrence: dict, period: str):
    value = occurrence.get(period)
    if value is not None:
        return value
    return (node.get("value") or {}).get(period)


def _record_label(node: dict, occurrence: dict) -> str:
    return fold(occurrence.get("source_label") or occurrence.get("label") or node.get("canonical_name"))


def _period_values_match(source_node: dict, source_occurrence: dict, semantic_node: dict, semantic_occurrence: dict) -> bool:
    """Compare evidence values without treating a source code as identity."""

    compared = False
    for period in ("current", "previous"):
        source_value = _record_value(source_node, source_occurrence, period)
        semantic_value = _record_value(semantic_node, semantic_occurrence, period)
        if source_value is None or semantic_value is None:
            continue
        compared = True
        if _value_key(source_value) != _value_key(semantic_value):
            return False
    return compared


def _context_matches(source_node: dict, semantic_node: dict, statement: str) -> bool:
    if statement == "CASHFLOW":
        source_section = clean(source_node.get("section") or "")
        semantic_section = clean(semantic_node.get("section") or "")
        if source_section and semantic_section and source_section != semantic_section:
            return False
    if statement == "FINANCIAL_POSITION":
        source_context = fold(source_node.get("hierarchy_path") or source_node.get("parent_label") or "")
        semantic_context = fold(semantic_node.get("hierarchy_path") or semantic_node.get("parent_label") or "")
        if source_context and semantic_context and source_context != semantic_context:
            return False
    return True


def _link_source_observations(semantic: list[dict], source: list[dict], statement: str) -> dict:
    """Link retained source evidence to semantic nodes when evidence is unambiguous.

    This is a provenance reconciliation step, not a new identity rule.  It uses the
    extracted source line, normalized source label, period values, and structural
    context.  Form codes are intentionally absent from every lookup key.
    """

    by_line: dict[str, list[tuple[dict, dict]]] = collections.defaultdict(list)
    by_label_values: dict[tuple[str, Any, Any], list[tuple[dict, dict]]] = collections.defaultdict(list)
    for semantic_node in semantic:
        seen_records = set()
        for occurrence in _node_occurrences(semantic_node):
            record_key = (
                occurrence.get("source_line"),
                _record_label(semantic_node, occurrence),
                _value_key(_record_value(semantic_node, occurrence, "current")),
                _value_key(_record_value(semantic_node, occurrence, "previous")),
            )
            if record_key in seen_records:
                continue
            seen_records.add(record_key)
            line = occurrence.get("source_line")
            if line is not None:
                by_line[str(line)].append((semantic_node, occurrence))
            by_label_values[
                (
                    _record_label(semantic_node, occurrence),
                    _value_key(_record_value(semantic_node, occurrence, "current")),
                    _value_key(_record_value(semantic_node, occurrence, "previous")),
                )
            ].append((semantic_node, occurrence))

    linked = 0
    source_only = 0
    ambiguous = 0
    for source_node in source:
        candidates: list[tuple[dict, dict, str, float]] = []
        for source_occurrence in _node_occurrences(source_node):
            line = source_occurrence.get("source_line")
            if line is not None:
                for semantic_node, semantic_occurrence in by_line.get(str(line), []):
                    if not _context_matches(source_node, semantic_node, statement):
                        continue
                    if not _period_values_match(source_node, source_occurrence, semantic_node, semantic_occurrence):
                        continue
                    candidates.append((semantic_node, semantic_occurrence, "source_line_and_values", 1.0))

            label_key = (
                _record_label(source_node, source_occurrence),
                _value_key(_record_value(source_node, source_occurrence, "current")),
                _value_key(_record_value(source_node, source_occurrence, "previous")),
            )
            for semantic_node, semantic_occurrence in by_label_values.get(label_key, []):
                if _context_matches(source_node, semantic_node, statement):
                    candidates.append((semantic_node, semantic_occurrence, "normalized_label_and_values", 0.98))

        unique: dict[str, tuple[dict, dict, str, float]] = {}
        for candidate in candidates:
            semantic_node = candidate[0]
            key = str(semantic_node.get("node_id") or id(semantic_node))
            previous = unique.get(key)
            if previous is None or candidate[3] > previous[3]:
                unique[key] = candidate

        meta = source_node.setdefault("extraction_meta", {})
        if len(unique) == 1:
            semantic_node, semantic_occurrence, method, confidence = next(iter(unique.values()))
            mapped_node_id = semantic_node.get("node_id")
            meta["mapping_status"] = "mapped"
            meta["mapping_method"] = "source_evidence_link"
            meta["mapping_confidence"] = confidence
            meta["mapped_node_id"] = mapped_node_id
            meta["source_semantic_link"] = {
                "mapped_node_id": mapped_node_id,
                "relation": "source_evidence_for",
                "method": method,
                "confidence": confidence,
            }
            source_node["mapping"] = {
                "status": "mapped",
                "mapped_node_id": mapped_node_id,
                "method": "source_evidence_link",
                "confidence": confidence,
            }
            linked += 1
        else:
            if len(unique) > 1:
                ambiguous += 1
            meta.setdefault("mapping_status", "source_only")
            meta.setdefault("mapping_method", "source_preservation")
            meta.setdefault("source_only_reason", "no_unique_semantic_evidence_link")
            source_node["mapping"] = {
                "status": meta["mapping_status"],
                "method": meta["mapping_method"],
            }
            if meta.get("source_only_reason"):
                source_node["mapping"]["reason"] = meta["source_only_reason"]
            source_only += 1

    return {
        "policy": "source_evidence_link_v1",
        "source_nodes": len(source),
        "linked_source_nodes": linked,
        "source_only_nodes": source_only,
        "ambiguous_source_nodes": ambiguous,
    }


def reconcile_source_observations(canonical: dict | None, statement: str) -> dict | None:
    """v16 structural-identity, non-destructive source reconciliation.

    Source observations stay intact. Financial Position duplicate families additionally use
    hierarchy context so repeated generic labels under different parents are not collapsed.
    Reconciliation is a parallel view:

    * all original observations remain available;
    * duplicate groups are annotated, not deleted;
    * one observation is marked preferred and moved before alternatives;
    * original source-observation period values are never synthetically modified;
    * semantic nodes are only hydrated when the semantic identity is unique and the period is null;
    * conflicting evidence is retained verbatim for debugging.
    """
    if not canonical:
        return canonical

    nodes = canonical.get("nodes") or []
    semantic = [n for n in nodes if n.get("kind") != "source_observation"]
    src = [n for n in nodes if n.get("kind") == "source_observation"]
    source_mapping = _link_source_observations(semantic, src, statement)

    # Family identity deliberately ignores form code: code is supporting evidence and continuation
    # pages often drop it. Cash Flow section remains part of identity because labels/codes can repeat.
    groups: dict[tuple[str, str, str], list[dict]] = collections.defaultdict(list)
    ungrouped = []
    for n in src:
        label = fold(n.get("canonical_name"))
        section = clean(n.get("section") or "") if statement == "CASHFLOW" else ""
        # Financial-position labels such as "Nguyên giá" or "Dự phòng" legitimately repeat under
        # different parents.  Preserve that source identity instead of collapsing by label alone.
        context = fold(n.get("hierarchy_path") or n.get("parent_label") or "") if statement == "FINANCIAL_POSITION" else ""
        if not label:
            ungrouped.append(n)
            continue
        groups[(section, label, context)].append(n)

    ordered_src: list[dict] = []
    view = []
    duplicate_groups = 0
    conflicts = 0
    semantic_fills = 0
    preferred_completed = 0

    for (section, label, context), bucket in sorted(groups.items(), key=lambda kv: min(_source_line(n) for n in kv[1])):
        gid = _group_id(statement, section, label, context)
        if len(bucket) > 1:
            duplicate_groups += 1

        cur, cur_state, cur_votes = _resolve_period(bucket, "current")
        prev, prev_state, prev_votes = _resolve_period(bucket, "previous")
        if cur_state == "conflict" or prev_state == "conflict":
            conflicts += 1

        preferred = _preferred_node(bucket, cur, prev)
        # v16 keeps source observations byte-semantic: reconciliation is a parallel view only.
        # Never synthesize a period directly into an original source observation.

        member_ids = []
        for rank, n in enumerate(sorted(bucket, key=_source_line), start=1):
            em = n.setdefault("extraction_meta", {})
            em["duplicate_group_id"] = gid
            em["duplicate_group_size"] = len(bucket)
            em["preferred_observation"] = (n is preferred)
            em["reconciliation_rank"] = 0 if n is preferred else rank
            em["reconciliation_policy"] = "structural_identity_non_destructive_v16"
            member_ids.append(n.get("node_id"))

        # Fill semantic node only if exact normalized identity is unique and semantic period is null.
        sem = _semantic_candidates(semantic, statement, section, label)
        if len(sem) == 1:
            sv = sem[0].setdefault("value", {})
            changed = False
            if sv.get("current") is None and cur is not None:
                sv["current"] = cur
                changed = True
            if sv.get("previous") is None and prev is not None:
                sv["previous"] = prev
                changed = True
            if changed:
                semantic_fills += 1
                sem[0].setdefault("extraction_meta", {}).setdefault("source_reconciliation_fills", []).append({
                    "group_id": gid,
                    "current": cur,
                    "previous": prev,
                    "policy": "fill_missing_only_v16",
                })

        # Preferred first, but every alternative remains in nodes for recall/debug evidence.
        ordered_src.append(preferred)
        ordered_src.extend(n for n in sorted(bucket, key=_source_line) if n is not preferred)
        view.append({
            "group_id": gid,
            "statement": statement,
            "section": section or None,
            "normalized_label": label,
            "identity_context": context or None,
            "display_label": preferred.get("canonical_name"),
            "preferred_node_id": preferred.get("node_id"),
            "member_node_ids": member_ids,
            "member_count": len(bucket),
            "current": cur,
            "previous": prev,
            "current_state": cur_state,
            "previous_state": prev_state,
            "current_votes": cur_votes,
            "previous_votes": prev_votes,
            "conflict": cur_state == "conflict" or prev_state == "conflict",
        })

    ordered_src.extend(ungrouped)
    canonical["nodes"] = semantic + ordered_src
    canonical["reconciled_source_view"] = view
    canonical.setdefault("diagnostics", {})["source_observation_reconciliation"] = {
        "statement": statement,
        "policy": "structural_identity_non_destructive_v16",
        "input_source_nodes": len(src),
        "output_source_nodes": len(ordered_src),
        "duplicate_groups": duplicate_groups,
        "removed_duplicate_nodes": 0,
        "conflicting_groups": conflicts,
        "preferred_completed_nodes": 0,
        "semantic_nodes_filled": semantic_fills,
        "preserves_all_source_observations": True,
        "source_mapping": source_mapping,
    }
    canonical.setdefault("diagnostics", {})["source_observation_mapping"] = source_mapping
    return canonical
