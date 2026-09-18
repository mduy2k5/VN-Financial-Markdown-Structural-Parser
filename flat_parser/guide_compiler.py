from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PATTERN_FAMILY_MAP = {
    # A1 names
    "label_multi_period_inline": "SP_MULTI_PERIOD_INLINE",
    "label_with_period_bearing_children": "SP_PERIOD_CHILDREN",
    "label_with_positional_value_children": "SP_POSITIONAL_VALUE_CHILDREN",
    "period_value_attribute": "SP_PERIOD_VALUE_ATTRIBUTE",
    "label_single_value_inline": "SP_LABEL_VALUE_INLINE",
    "bare_value_positional": "SP_VALUE_ONLY_POSITIONAL",
    "qualifier_node": "SP_QUALIFIER_CONTAINER",
    "label_with_keyed_attribute_children": "SP_KEYED_ATTRIBUTE_CHILDREN",
    "structural_container": "SP_STRUCTURAL_CONTAINER",
    "context_header_or_unit_carrier": "SP_CONTEXT_CARRIER",

    # Tên trong A2-A5.
    "label_or_container": "SP_LABEL_CONTAINER",
    "label_value_inline": "SP_LABEL_VALUE_INLINE",
    "value_only_positional": "SP_VALUE_ONLY_POSITIONAL",
    "markdown_table_row": "SP_MARKDOWN_TABLE_ROW",
    "named_attribute": "SP_NAMED_ATTRIBUTE",
    "qualifier_container": "SP_QUALIFIER_CONTAINER",
    "period_container": "SP_PERIOD_CONTAINER",
    "pipe_delimited_inline_row": "SP_PIPE_DELIMITED_INLINE_ROW",
}

UNIVERSAL_PATTERN_META = {
    "SP_MARKDOWN_TABLE_ROW": ("markdown_table_row", 160),
    "SP_QUALIFIER_CONTAINER": ("qualifier_container", 155),
    "SP_PIPE_DELIMITED_INLINE_ROW": ("pipe_delimited_inline_row", 150),
    "SP_PERIOD_CONTAINER": ("period_container", 145),
    "SP_MULTI_PERIOD_INLINE": ("label_multi_period_inline", 140),
    "SP_NAMED_ATTRIBUTE": ("named_attribute", 135),
    "SP_PERIOD_VALUE_ATTRIBUTE": ("period_value_attribute", 130),
    "SP_PERIOD_CHILDREN": ("label_with_period_children", 125),
    "SP_KEYED_ATTRIBUTE_CHILDREN": ("label_with_keyed_attribute_children", 120),
    "SP_POSITIONAL_VALUE_CHILDREN": ("label_with_positional_value_children", 115),
    "SP_LABEL_VALUE_INLINE": ("label_value_inline", 100),
    "SP_VALUE_ONLY_POSITIONAL": ("value_only_positional", 90),
    "SP_CONTEXT_CARRIER": ("context_carrier", 80),
    "SP_STRUCTURAL_CONTAINER": ("structural_container", 40),
    "SP_LABEL_CONTAINER": ("label_container", 30),
}


def _append_unique(out: list, value):
    if value not in out:
        out.append(value)


def _merge_field_patterns(target: dict[str, Any], source: dict[str, Any], guide_id: str):
    for category in ("value", "period", "unit", "note", "role", "qualifier", "label"):
        src = source.get(category, {})
        dst = target.setdefault(category, {
            "observed_forms": [],
            "patterns": [],
            "mappings": {},
            "sources": [],
        })

        _append_unique(dst["sources"], guide_id)

        for item in src.get("observed_forms", []):
            _append_unique(dst["observed_forms"], item)

        for pattern in src.get("patterns", []):
            key = json.dumps(pattern, ensure_ascii=False, sort_keys=True)
            existing = {
                json.dumps(x, ensure_ascii=False, sort_keys=True)
                for x in dst["patterns"]
            }
            if key not in existing:
                dst["patterns"].append(pattern)

        for map_key in ("mapping", "semantic_mapping_examples"):
            mapping = src.get(map_key, {})
            if isinstance(mapping, dict):
                dst["mappings"].update(mapping)


def compile_guides(guides_root: str | Path) -> dict:
    guides_root = Path(guides_root)
    universal = {
        "version": "1.0",
        "design": {
            "semantic_pattern_ids": True,
            "dataset_pattern_ids_are_provenance_only": True,
            "alias_first": True,
            "structure_second": True,
            "first_value_per_period_wins": True,
        },
        "patterns": {},
        "field_patterns": {},
        "named_attribute_keys": [],
        "source_guides": [],
        "unmapped_source_pattern_names": [],
    }

    for guide_dir in sorted(p for p in guides_root.iterdir() if p.is_dir()):
        guide_id = guide_dir.name
        structural_path = guide_dir / "structural_patterns.json"
        fields_path = guide_dir / "field_patterns.json"

        if not structural_path.exists():
            continue

        structural = json.loads(structural_path.read_text(encoding="utf-8"))
        universal["source_guides"].append({
            "guide_id": guide_id,
            "dataset": structural.get("dataset"),
        })

        if fields_path.exists():
            _merge_field_patterns(
                universal["field_patterns"],
                json.loads(fields_path.read_text(encoding="utf-8")),
                guide_id,
            )

        for p in structural.get("patterns", []):
            source_name = p.get("name")
            universal_id = PATTERN_FAMILY_MAP.get(source_name)
            if not universal_id:
                if source_name not in universal["unmapped_source_pattern_names"]:
                    universal["unmapped_source_pattern_names"].append(source_name)
                continue

            universal_name, universal_priority = UNIVERSAL_PATTERN_META[universal_id]
            item = universal["patterns"].setdefault(
                universal_id,
                {
                    "id": universal_id,
                    "name": universal_name,
                    "priority": universal_priority,
                    "observed_in": [],
                    "source_patterns": [],
                    "examples": [],
                },
            )
            _append_unique(item["observed_in"], guide_id)
            item["source_patterns"].append({
                "guide_id": guide_id,
                "source_id": p.get("id"),
                "source_name": source_name,
                "source_priority": p.get("priority"),
            })
            for ex in p.get("examples", []):
                _append_unique(item["examples"], ex)

            detect = p.get("detect", {})
            for key in ("observed_keys",):
                for observed_key in detect.get(key, []):
                    _append_unique(universal["named_attribute_keys"], observed_key)

    # Các key được mô tả rõ trong A1/A2/A5 nhưng không phải lúc nào cũng có trong observed_keys.
    for key in [
        "Thuyết minh",
        "Số liệu thuyết minh",
        "Mã số",
        "Số tiền",
        "Chức vụ",
        "Tỷ lệ sở hữu %",
        "Tỷ lệ sở hữu",
        "Tên công ty",
        "Diễn giải",
        "Phân loại",
        "Tiêu chí",
        "Hoạt động chính",
    ]:
        _append_unique(universal["named_attribute_keys"], key)

    universal["selection_order"] = [
        x[0]
        for x in sorted(
            UNIVERSAL_PATTERN_META.items(),
            key=lambda kv: kv[1][1],
            reverse=True,
        )
    ]
    universal["patterns"] = [
        universal["patterns"][pid]
        for pid in universal["selection_order"]
        if pid in universal["patterns"]
    ]
    return universal


def write_compiled_guide(guides_root: str | Path, output_path: str | Path):
    output_path = Path(output_path)
    output_path.write_text(
        json.dumps(compile_guides(guides_root), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
