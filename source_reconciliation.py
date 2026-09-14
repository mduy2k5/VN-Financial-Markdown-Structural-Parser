from __future__ import annotations

import collections
from typing import Any

from source_statement_recovery import clean, fold


def _value_key(v: Any):
    if isinstance(v, float):
        return round(v, 8)
    return v


def _choose_period(nodes: list[dict], period: str):
    """Choose the most defensible period value from source observations.

    Priority: value appearing most often across observations/occurrences; ties prefer a
    node that has both periods populated, then the earliest source line.  We do not
    touch semantic nodes here.
    """
    votes = collections.Counter()
    support: dict[Any, list[tuple[int, int]]] = collections.defaultdict(list)
    for n in nodes:
        val = (n.get("value") or {}).get(period)
        if val is not None:
            k = _value_key(val)
            votes[k] += 1
            both = int((n.get("value") or {}).get("current") is not None and (n.get("value") or {}).get("previous") is not None)
            occ = ((n.get("extraction_meta") or {}).get("occurrences") or [{}])[0]
            line = occ.get("source_line") or 10**9
            support[k].append((both, line))
        for occ in (n.get("extraction_meta") or {}).get("occurrences") or []:
            ov = occ.get(period)
            if ov is not None:
                k = _value_key(ov)
                votes[k] += 1
                both = int(occ.get("current") is not None and occ.get("previous") is not None)
                line = occ.get("source_line") or 10**9
                support[k].append((both, line))
    if not votes:
        return None
    ranked = sorted(votes, key=lambda k: (
        votes[k],
        max((x[0] for x in support[k]), default=0),
        -min((x[1] for x in support[k]), default=10**9),
    ), reverse=True)
    return ranked[0]


def reconcile_source_observations(canonical: dict | None, statement: str) -> dict | None:
    if not canonical:
        return canonical
    nodes = canonical.get("nodes") or []
    semantic = [n for n in nodes if n.get("kind") != "source_observation"]
    src = [n for n in nodes if n.get("kind") == "source_observation"]

    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for n in src:
        label = fold(n.get("canonical_name"))
        code = clean(n.get("form_code") or "")
        section = clean(n.get("section") or "") if statement == "CASHFLOW" else ""
        if not label:
            continue
        # Section is part of Cash Flow identity; form code is supporting identity when present.
        groups[(section, label, code)].append(n)

    reconciled = []
    merged_groups = removed = conflicts = 0
    for key, bucket in groups.items():
        if len(bucket) == 1:
            reconciled.append(bucket[0]); continue
        merged_groups += 1
        primary = min(bucket, key=lambda n: (((n.get("extraction_meta") or {}).get("occurrences") or [{}])[0].get("source_line") or 10**9))
        cur = _choose_period(bucket, "current")
        prev = _choose_period(bucket, "previous")
        vals_seen_cur = {_value_key((n.get("value") or {}).get("current")) for n in bucket if (n.get("value") or {}).get("current") is not None}
        vals_seen_prev = {_value_key((n.get("value") or {}).get("previous")) for n in bucket if (n.get("value") or {}).get("previous") is not None}
        if len(vals_seen_cur) > 1 or len(vals_seen_prev) > 1:
            # Conflict is debug evidence. Do not collapse alternatives: dropping one can hide the
            # actually correct source occurrence. Only compatible/complementary observations are merged.
            conflicts += 1
            reconciled.extend(bucket)
            continue
        pval = primary.setdefault("value", {})
        pval["current"] = cur
        pval["previous"] = prev
        pem = primary.setdefault("extraction_meta", {})
        all_occ = []
        patterns = []
        for n in bucket:
            for occ in (n.get("extraction_meta") or {}).get("occurrences") or []:
                all_occ.append(occ)
                if occ.get("pattern") and occ.get("pattern") not in patterns:
                    patterns.append(occ.get("pattern"))
        all_occ.sort(key=lambda x: x.get("source_line") or 10**9)
        pem["occurrences"] = all_occ
        pem["reconciled_source_observation"] = True
        pem["reconciliation_patterns"] = patterns
        reconciled.append(primary)
        removed += len(bucket) - 1

    # Second pass: when code-specific and code-less rows share the same exact label and section,
    # merge complementary periods if values do not conflict. This is common when the LLM drops
    # the form-code column on continuation pages.
    by_label = collections.defaultdict(list)
    for n in reconciled:
        by_label[(clean(n.get("section") or "") if statement == "CASHFLOW" else "", fold(n.get("canonical_name")))].append(n)
    keep = []
    consumed = set()
    for _, bucket in by_label.items():
        if len(bucket) == 1:
            keep.append(bucket[0]); continue
        # Only collapse if all populated values are compatible or complementary.
        cur_vals = {_value_key((n.get("value") or {}).get("current")) for n in bucket if (n.get("value") or {}).get("current") is not None}
        prev_vals = {_value_key((n.get("value") or {}).get("previous")) for n in bucket if (n.get("value") or {}).get("previous") is not None}
        if len(cur_vals) <= 1 and len(prev_vals) <= 1:
            primary = next((n for n in bucket if n.get("form_code")), bucket[0])
            primary.setdefault("value", {})["current"] = next(iter(cur_vals), None)
            primary.setdefault("value", {})["previous"] = next(iter(prev_vals), None)
            occ = []
            for n in bucket:
                occ.extend((n.get("extraction_meta") or {}).get("occurrences") or [])
            primary.setdefault("extraction_meta", {})["occurrences"] = sorted(occ, key=lambda x: x.get("source_line") or 10**9)
            primary["extraction_meta"]["reconciled_codeless_variant"] = True
            keep.append(primary)
            removed += len(bucket) - 1
        else:
            keep.extend(bucket)

    canonical["nodes"] = semantic + keep
    canonical.setdefault("diagnostics", {})["source_observation_reconciliation"] = {
        "statement": statement,
        "policy": "normalized_label_period_reconciliation_v14",
        "input_source_nodes": len(src),
        "output_source_nodes": len(keep),
        "merged_groups": merged_groups,
        "removed_duplicate_nodes": removed,
        "conflicting_groups": conflicts,
    }
    return canonical
