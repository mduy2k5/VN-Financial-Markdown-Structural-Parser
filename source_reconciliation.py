from __future__ import annotations

import collections
import hashlib
from typing import Any

from source_statement_recovery import clean, fold


def _value_key(v: Any):
    if isinstance(v, float):
        return round(v, 8)
    return v


def _source_line(node: dict) -> int:
    occ = ((node.get("extraction_meta") or {}).get("occurrences") or [{}])[0]
    return occ.get("source_line") or 10**9


def _group_id(statement: str, section: str, label: str) -> str:
    raw = f"{statement}|{section}|{label}".encode("utf-8")
    return "SRCGRP." + hashlib.sha1(raw).hexdigest()[:14]


def _period_votes(nodes: list[dict], period: str):
    """Return period vote table using both node value and occurrence evidence.

    A single node value contributes one vote. Occurrence values contribute only when they are
    not identical to the node-level value from the same observation, avoiding accidental double
    weighting of the same evidence.
    """
    votes = collections.Counter()
    support: dict[Any, list[tuple[int, int, int]]] = collections.defaultdict(list)
    for n in nodes:
        nv = (n.get("value") or {}).get(period)
        if nv is not None:
            k = _value_key(nv)
            both = int((n.get("value") or {}).get("current") is not None and (n.get("value") or {}).get("previous") is not None)
            code = int(bool(clean(n.get("form_code") or "")))
            votes[k] += 1
            support[k].append((both, code, _source_line(n)))
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
            code = int(bool(clean(occ.get("code") or occ.get("code_candidate") or n.get("form_code") or "")))
            votes[k] += 1
            support[k].append((both, code, occ.get("source_line") or _source_line(n)))
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
            max((x[1] for x in support[k]), default=0),
            -min((x[2] for x in support[k]), default=10**9),
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
        has_code = int(bool(clean(n.get("form_code") or "")))
        recovered = int(bool((n.get("extraction_meta") or {}).get("source_recovery")))
        return (exact, both, has_code, recovered, -_source_line(n))
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


def reconcile_source_observations(canonical: dict | None, statement: str) -> dict | None:
    """v15 non-destructive source reconciliation.

    v14 physically collapsed compatible source observations. That improved value precision but
    reduced ground-truth row recall. v15 keeps every source observation in ``nodes`` and treats
    reconciliation as a parallel view:

    * all original observations remain available;
    * duplicate groups are annotated, not deleted;
    * one observation is marked preferred and moved before alternatives;
    * the preferred observation may be completed with a conservative reconciled period pair;
    * semantic nodes are only hydrated when the semantic identity is unique and the period is null;
    * conflicting evidence is retained verbatim for debugging.
    """
    if not canonical:
        return canonical

    nodes = canonical.get("nodes") or []
    semantic = [n for n in nodes if n.get("kind") != "source_observation"]
    src = [n for n in nodes if n.get("kind") == "source_observation"]

    # Family identity deliberately ignores form code: code is supporting evidence and continuation
    # pages often drop it. Cash Flow section remains part of identity because labels/codes can repeat.
    groups: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    ungrouped = []
    for n in src:
        label = fold(n.get("canonical_name"))
        section = clean(n.get("section") or "") if statement == "CASHFLOW" else ""
        if not label:
            ungrouped.append(n)
            continue
        groups[(section, label)].append(n)

    ordered_src: list[dict] = []
    view = []
    duplicate_groups = 0
    conflicts = 0
    semantic_fills = 0
    preferred_completed = 0

    for (section, label), bucket in sorted(groups.items(), key=lambda kv: min(_source_line(n) for n in kv[1])):
        gid = _group_id(statement, section, label)
        if len(bucket) > 1:
            duplicate_groups += 1

        cur, cur_state, cur_votes = _resolve_period(bucket, "current")
        prev, prev_state, prev_votes = _resolve_period(bucket, "previous")
        if cur_state == "conflict" or prev_state == "conflict":
            conflicts += 1

        preferred = _preferred_node(bucket, cur, prev)
        pval = preferred.setdefault("value", {})
        before = (pval.get("current"), pval.get("previous"))
        if pval.get("current") is None and cur is not None:
            pval["current"] = cur
        if pval.get("previous") is None and prev is not None:
            pval["previous"] = prev
        if before != (pval.get("current"), pval.get("previous")):
            preferred_completed += 1

        member_ids = []
        for rank, n in enumerate(sorted(bucket, key=_source_line), start=1):
            em = n.setdefault("extraction_meta", {})
            em["duplicate_group_id"] = gid
            em["duplicate_group_size"] = len(bucket)
            em["preferred_observation"] = (n is preferred)
            em["reconciliation_rank"] = 0 if n is preferred else rank
            em["reconciliation_policy"] = "non_destructive_source_view_v15"
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
                    "policy": "fill_missing_only_v15",
                })

        # Preferred first, but every alternative remains in nodes for recall/debug evidence.
        ordered_src.append(preferred)
        ordered_src.extend(n for n in sorted(bucket, key=_source_line) if n is not preferred)
        view.append({
            "group_id": gid,
            "statement": statement,
            "section": section or None,
            "normalized_label": label,
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
        "policy": "non_destructive_source_view_v15",
        "input_source_nodes": len(src),
        "output_source_nodes": len(ordered_src),
        "duplicate_groups": duplicate_groups,
        "removed_duplicate_nodes": 0,
        "conflicting_groups": conflicts,
        "preferred_completed_nodes": preferred_completed,
        "semantic_nodes_filled": semantic_fills,
        "preserves_all_source_observations": True,
    }
    return canonical
