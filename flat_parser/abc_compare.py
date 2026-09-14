from __future__ import annotations


def canonical_stats(canonical):
    nodes = canonical.get("nodes", []) if isinstance(canonical, dict) else []
    value_nodes = [n for n in nodes if any((n.get("value") or {}).get(k) is not None for k in ("current", "previous"))]
    return {
        "value_nodes": len(value_nodes),
        "current_value_nodes": sum(1 for n in value_nodes if (n.get("value") or {}).get("current") is not None),
        "previous_value_nodes": sum(1 for n in value_nodes if (n.get("value") or {}).get("previous") is not None),
    }


def _fp(result):
    return (result.get("statements") or {}).get("financial_position") or {}


def _node_map(result):
    can = _fp(result).get("canonical") or {}
    return {n.get("node_id"): n for n in can.get("nodes", [])}


def _pair(n):
    v = (n or {}).get("value") or {}
    return (v.get("current"), v.get("previous"))


def _has(pair):
    return any(v is not None for v in pair)


def pairwise(a_name, a_result, b_name, b_result):
    a_nodes = _node_map(a_result)
    b_nodes = _node_map(b_result)
    ids = sorted(set(a_nodes) | set(b_nodes))
    same = different = only_a = only_b = 0
    diffs = []
    for nid in ids:
        ap = _pair(a_nodes.get(nid))
        bp = _pair(b_nodes.get(nid))
        ah, bh = _has(ap), _has(bp)
        if ah and not bh:
            only_a += 1
        elif bh and not ah:
            only_b += 1
        elif ah and bh:
            if ap == bp:
                same += 1
            else:
                different += 1
                diffs.append({"node_id": nid, a_name: ap, b_name: bp})
    return {
        "same_value_nodes": same,
        "different_value_nodes": different,
        f"only_{a_name}_value_nodes": only_a,
        f"only_{b_name}_value_nodes": only_b,
        "different_values": diffs,
    }


def compare_three(v05_result, flow_result, hybrid_result):
    v05_fp, flow_fp, hy_fp = _fp(v05_result), _fp(flow_result), _fp(hybrid_result)
    flow_map_stats = (flow_fp.get("debug") or {}).get("stats") or flow_fp.get("stats") or {}
    hybrid_stats = (hy_fp.get("debug") or {}).get("hybrid_stats") or {}
    v05_stats = (v05_fp.get("debug") or {}).get("stats") or {}
    return {
        "financial_position": {
            "v05": {**canonical_stats(v05_fp.get("canonical") or {}), "parser": v05_stats},
            "flow": {**canonical_stats(flow_fp.get("canonical") or {}), "mapping": flow_map_stats},
            "hybrid": {**canonical_stats(hy_fp.get("canonical") or {}), "mapping": hybrid_stats},
            "pairwise": {
                "v05_vs_flow": pairwise("v05", v05_result, "flow", flow_result),
                "v05_vs_hybrid": pairwise("v05", v05_result, "hybrid", hybrid_result),
                "flow_vs_hybrid": pairwise("flow", flow_result, "hybrid", hybrid_result),
            },
        }
    }
