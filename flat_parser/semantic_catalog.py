from __future__ import annotations

import json
from pathlib import Path

from .models import CanonicalNodeSpec
from .schema_loader import load_alias_document, load_schema_document
from .textnorm import fold, strip_numbering


def _label_key(value: str | None) -> str:
    """Chuẩn hóa nhãn semantic để so sánh quan hệ cha--con.

    Đây chỉ là khóa so sánh cấu trúc, không phải khóa identity cuối cùng. Số
    thứ tự dòng (``1.``, ``IV.``...) và khác biệt dấu/hoa thường không được
    xem là một phần tên semantic.
    """

    return fold(strip_numbering(value or "")).strip(" |;:-")


class SemanticCatalog:
    def __init__(self, schema_path: str | Path, aliases_path: str | Path):
        self.schema = load_schema_document(schema_path)
        aliases = load_alias_document(aliases_path)

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

        # Tính trước các cặp node có nhãn nguồn giao nhau với nhãn của parent.
        # Alias pack vẫn có thể khai báo cờ thủ công, nhưng không nên là nơi
        # duy nhất quyết định một child có thể trùng tên parent; schema mới
        # thêm node phải được bảo vệ ngay cả khi quên thêm cờ alias.
        self.same_label_parent_overlaps: dict[str, set[str]] = {}
        for node_id, node in self.nodes.items():
            parent = self.nodes.get(node.parent_id) if node.parent_id else None
            if parent is None:
                continue
            child_labels = {
                _label_key(value)
                for value in [node.canonical_name, *node.exact, *node.aliases]
                if _label_key(value)
            }
            parent_labels = {
                _label_key(value)
                for value in [parent.canonical_name, *parent.exact, *parent.aliases]
                if _label_key(value)
            }
            overlap = child_labels & parent_labels
            if overlap:
                self.same_label_parent_overlaps[node_id] = overlap

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

    def same_label_parent_overlap(self, node_id: str) -> set[str]:
        """Return nhãn giao giữa node và parent trực tiếp, nếu có."""

        return set(self.same_label_parent_overlaps.get(node_id, set()))
