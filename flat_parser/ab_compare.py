from __future__ import annotations


def _canonical_stats(canonical):
    nodes = canonical.get("nodes", []) if isinstance(canonical, dict) else []
    value_nodes = [n for n in nodes if any((n.get("value") or {}).get(k) is not None for k in ("current", "previous"))]
    return {
        "value_nodes": len(value_nodes),
        "current_value_nodes": sum(1 for n in value_nodes if (n.get("value") or {}).get("current") is not None),
        "previous_value_nodes": sum(1 for n in value_nodes if (n.get("value") or {}).get("previous") is not None),
    }


def compare_results(new_result, v05_result):
    new_fp = (new_result.get("statements") or {}).get("financial_position") or {}
    old_fp = (v05_result.get("statements") or {}).get("financial_position") or {}
    new_can = new_fp.get("canonical") or {}
    old_can = old_fp.get("canonical") or {}
    new_stats = _canonical_stats(new_can)
    old_stats = _canonical_stats(old_can)

    new_nodes = {n.get("node_id"): n for n in new_can.get("nodes", [])}
    old_nodes = {n.get("node_id"): n for n in old_can.get("nodes", [])}
    all_ids = sorted(set(new_nodes) | set(old_nodes))
    agreements = disagreements = only_new = only_old = 0
    diff = []
    for nid in all_ids:
        nv = (new_nodes.get(nid) or {}).get("value") or {}
        ov = (old_nodes.get(nid) or {}).get("value") or {}
        npair = (nv.get("current"), nv.get("previous"))
        opair = (ov.get("current"), ov.get("previous"))
        nhas = any(v is not None for v in npair)
        ohas = any(v is not None for v in opair)
        if nhas and not ohas:
            only_new += 1
        elif ohas and not nhas:
            only_old += 1
        elif nhas and ohas:
            if npair == opair:
                agreements += 1
            else:
                disagreements += 1
                diff.append({"node_id": nid, "new": npair, "v05": opair})

    new_map_stats = ((new_fp.get("debug") or {}).get("hybrid_stats") or {})
    old_parser_stats = ((old_fp.get("debug") or {}).get("stats") or {})
    return {
        "financial_position": {
            "new": {**new_stats, "mapping": new_map_stats},
            "v05": {**old_stats, "parser": old_parser_stats},
            "cross_engine": {
                "same_value_nodes": agreements,
                "different_value_nodes": disagreements,
                "only_new_value_nodes": only_new,
                "only_v05_value_nodes": only_old,
                "different_values": diff,
            },
        }
    }
