from __future__ import annotations

import json
from pathlib import Path

from .models import CanonicalNodeSpec


class SemanticCatalog:
    def __init__(self, schema_path: str | Path, aliases_path: str | Path):
        self.schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        aliases = json.loads(Path(aliases_path).read_text(encoding="utf-8"))

        schema_nodes = {x["node_id"]: x for x in self.schema["nodes"]}
        alias_nodes = aliases["nodes"]

        if set(schema_nodes) != set(alias_nodes):
            raise ValueError("Schema and alias catalog must have identical node_id sets.")

        self.nodes = {}
        for node_id, s in schema_nodes.items():
            a = alias_nodes[node_id]
            m = a.get("match", {})
            self.nodes[node_id] = CanonicalNodeSpec(
                node_id=node_id,
                canonical_name=s.get("canonical_name", a.get("canonical_name", node_id)),
                parent_id=s.get("parent_id"),
                kind=s.get("kind", "line"),
                sector=s.get("sector", "common"),
                exact=list(m.get("exact", [])),
                aliases=list(m.get("aliases", [])),
                parent_context=list(m.get("parent_context", [])),
                contains=list(m.get("contains", [])),
                exclude_if_contains=list(m.get("exclude_if_contains", [])),
                structural=dict(m.get("structural", {})),
            )

    def clone_schema(self):
        return json.loads(json.dumps(self.schema, ensure_ascii=False))

    def ancestor_ids(self, node_id: str):
        out = []
        seen = set()
        current = self.nodes.get(node_id)
        while current and current.parent_id and current.parent_id not in seen:
            out.append(current.parent_id)
            seen.add(current.parent_id)
            current = self.nodes.get(current.parent_id)
        return out
