from __future__ import annotations

import json
from pathlib import Path


def _value_template():
    return {
        "current": None,
        "previous": None,
        "additional": None,
        "note": None,
        "raw_text": None,
    }


def build_off_balance_compatible_resources(
    source_schema: str | Path,
    source_aliases: str | Path,
    out_schema: str | Path,
    out_aliases: str | Path,
):
    """Convert the standalone OFF_BALANCE alias pack to FlatParser's catalog format.

    The conversion is deterministic and intentionally does not invent aliases.
    Formatting variants stay the responsibility of the existing lexical/structural
    engine; only semantic aliases from the pack are transferred.
    """
    source_schema = Path(source_schema)
    source_aliases = Path(source_aliases)
    schema = json.loads(source_schema.read_text(encoding="utf-8"))
    aliases = json.loads(source_aliases.read_text(encoding="utf-8"))

    source_nodes = {n["node_id"]: n for n in schema.get("nodes", [])}
    children = {nid: [] for nid in source_nodes}
    for n in source_nodes.values():
        parent = n.get("parent")
        if parent in children:
            children[parent].append(n["node_id"])

    compat_nodes = []
    for n in schema.get("nodes", []):
        compat_nodes.append({
            "node_id": n["node_id"],
            "canonical_name": n.get("label", n["node_id"]),
            "parent_id": n.get("parent"),
            "kind": n.get("kind", "line"),
            "sector": "bank",
            "children": children.get(n["node_id"], []),
            "value": _value_template(),
            "off_balance_optional": bool(n.get("optional", False)),
        })

    compat_schema = {
        "schema_id": "UNIVERSAL_OFF_BALANCE_BANK_V1_3",
        "schema_version": aliases.get("version", schema.get("schema_version", "1.3.0")),
        "statement_type": "FINANCIAL_POSITION",
        "sub_statement_type": "OFF_BALANCE",
        "sector": "bank",
        "value_type": "POINT_IN_TIME",
        "design_principles": {
            "mapping_key": "semantic node_id",
            "form_code_used_for_mapping": False,
            "hierarchy_used_as_context": True,
            "formatting_variants_are_aliases": False,
            "participates_in_balance_identity": False,
        },
        "nodes": compat_nodes,
    }

    semantic_aliases = aliases.get("aliases", {})
    context_only = aliases.get("context_only", {})
    root_context_aliases = [
        k for k, v in context_only.items()
        if v.get("role") == "scope_heading"
    ]

    alias_nodes = {}
    for nid, n in source_nodes.items():
        vals = list(semantic_aliases.get(nid, []))
        exact = []
        canonical = n.get("label", nid)
        if canonical:
            exact.append(canonical)
        if nid == "OFF_BALANCE":
            exact.extend(root_context_aliases)
        if nid == "OFF_BALANCE.TOTAL":
            # The generic Total is safe only because StatementScanner has already
            # isolated an OFF_BALANCE range. It is not exposed outside that range.
            exact.append("Tổng cộng")

        # Deduplicate while retaining source order.
        def uniq(seq):
            seen = set(); out = []
            for x in seq:
                key = x.strip().casefold()
                if x and key not in seen:
                    seen.add(key); out.append(x)
            return out

        alias_nodes[nid] = {
            "node_id": nid,
            "canonical_name": canonical,
            "match": {
                "exact": uniq(exact),
                "aliases": uniq(vals),
                "parent_context": [],
                "contains": [],
                "exclude_if_contains": [],
                "structural": {},
            },
        }

    compat_aliases = {
        "alias_schema_version": "1.3.0-flat-parser-adapter",
        "target_schema": "UNIVERSAL_OFF_BALANCE_BANK_V1_3",
        "normalization": {
            "use_flat_parser_normalizer": True,
            "strip_leading_numbering": True,
            "semantic_aliases_only": True,
        },
        "nodes": alias_nodes,
        "source_alias_catalog": aliases.get("alias_catalog_id"),
    }

    out_schema = Path(out_schema)
    out_aliases = Path(out_aliases)
    out_schema.parent.mkdir(parents=True, exist_ok=True)
    out_aliases.parent.mkdir(parents=True, exist_ok=True)
    out_schema.write_text(json.dumps(compat_schema, ensure_ascii=False, indent=2), encoding="utf-8")
    out_aliases.write_text(json.dumps(compat_aliases, ensure_ascii=False, indent=2), encoding="utf-8")
    return compat_schema, compat_aliases


def build_income_compatible_resources(source_schema, source_aliases, out_schema, out_aliases):
    """Convert the v1 income schema/alias files to the universal catalog format."""
    source_schema = Path(source_schema)
    source_aliases = Path(source_aliases)
    schema = json.loads(source_schema.read_text(encoding="utf-8"))
    aliases = json.loads(source_aliases.read_text(encoding="utf-8"))

    source_alias_nodes = aliases.get("nodes", aliases)
    alias_nodes = {}
    for node in schema.get("nodes", []):
        node_id = node["node_id"]
        spec = source_alias_nodes.get(node_id, {})
        source_match = spec.get("match", {})
        alias_nodes[node_id] = {
            "node_id": node_id,
            "canonical_name": node.get("canonical_name", node_id),
            "match": {
                "exact": list(source_match.get("exact", [])),
                "aliases": list(source_match.get("aliases", [])),
                "parent_context": list(source_match.get("parent_context", [])),
                "contains": list(source_match.get("contains", [])),
                "exclude_if_contains": list(source_match.get("exclude_if_contains", [])),
                "structural": dict(source_match.get("structural", {})),
            },
        }

    compat_schema = {
        "schema_id": schema.get("schema_id", "UNIVERSAL_INCOME_STATEMENT_V1"),
        "schema_version": schema.get("schema_version", "1.0.0"),
        "statement_type": "INCOME_STATEMENT",
        "nodes": [
            {
                "node_id": node["node_id"],
                "canonical_name": node.get("canonical_name", node["node_id"]),
                "parent_id": node.get("parent_id"),
                "kind": node.get("kind", "line"),
                "sector": node.get("sector", "common"),
                "children": node.get("children", []),
                "value": node.get("value", _value_template()),
            }
            for node in schema.get("nodes", [])
        ],
    }
    compat_aliases = {
        "alias_schema_version": f"{schema.get('schema_version', '1.0.0')}-flat-parser-adapter",
        "target_schema": compat_schema["schema_id"],
        "nodes": alias_nodes,
    }

    out_schema = Path(out_schema)
    out_aliases = Path(out_aliases)
    out_schema.parent.mkdir(parents=True, exist_ok=True)
    out_aliases.parent.mkdir(parents=True, exist_ok=True)
    out_schema.write_text(json.dumps(compat_schema, ensure_ascii=False, indent=2), encoding="utf-8")
    out_aliases.write_text(json.dumps(compat_aliases, ensure_ascii=False, indent=2), encoding="utf-8")
    return compat_schema, compat_aliases
