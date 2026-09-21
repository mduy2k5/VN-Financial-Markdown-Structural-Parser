"""Load baseline schemas and reversible schema overlays.

An overlay is deliberately kept separate from the production baseline.  It
references a base JSON file and contains only additions/updates, so a caller
can roll back by selecting the baseline path without restoring or rewriting a
large schema file.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve(base_path: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (base_path.parent / candidate).resolve()


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        result = copy.deepcopy(base)
        for key, value in patch.items():
            result[key] = _deep_merge(result[key], value) if key in result else copy.deepcopy(value)
        return result
    return copy.deepcopy(patch)


def _unique_extend(current: list[Any], additions: list[Any]) -> list[Any]:
    result = copy.deepcopy(current)
    for item in additions:
        if item not in result:
            result.append(copy.deepcopy(item))
    return result


def _apply_entry_patch(entry: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply ordinary fields plus ``*_add``/``*_remove`` list operations."""

    result = copy.deepcopy(entry)
    for key, value in patch.items():
        if key.endswith("_add"):
            field = key[:-4]
            current = result.get(field) or []
            if not isinstance(current, list) or not isinstance(value, list):
                raise ValueError(f"Overlay list addition requires lists: {key}")
            result[field] = _unique_extend(current, value)
        elif key.endswith("_remove"):
            field = key[:-7]
            current = result.get(field) or []
            if not isinstance(current, list) or not isinstance(value, list):
                raise ValueError(f"Overlay list removal requires lists: {key}")
            result[field] = [item for item in current if item not in value]
        else:
            result[key] = _deep_merge(result[key], value) if key in result else copy.deepcopy(value)
    return result


def load_schema_document(path: str | Path) -> dict[str, Any]:
    """Return a materialized schema from a baseline or schema overlay path."""

    path = Path(path).resolve()
    raw = _read_json(path)
    if raw.get("overlay_type") != "schema":
        return raw

    base_path = _resolve(path, raw["base_schema"])
    result = load_schema_document(base_path)
    nodes = {node["node_id"]: copy.deepcopy(node) for node in result.get("nodes", [])}

    for node_id, patch in (raw.get("node_updates") or {}).items():
        if node_id not in nodes:
            raise ValueError(f"Schema overlay updates unknown node: {node_id}")
        nodes[node_id] = _deep_merge(nodes[node_id], patch)

    for node in raw.get("nodes_add") or []:
        node_id = node.get("node_id")
        if not node_id or node_id in nodes:
            raise ValueError(f"Schema overlay adds duplicate/empty node: {node_id}")
        nodes[node_id] = copy.deepcopy(node)

    result["nodes"] = list(nodes.values())
    if raw.get("formula_updates"):
        result["formulas"] = copy.deepcopy(result.get("formulas") or {})
        for profile, formulas in raw["formula_updates"].items():
            result["formulas"][profile] = copy.deepcopy(formulas)
    for key in ("schema_id", "schema_version", "statement_type"):
        if key in raw:
            result[key] = raw[key]
    return result


def load_alias_document(path: str | Path) -> dict[str, Any]:
    """Return a materialized alias catalog from a baseline or alias overlay."""

    path = Path(path).resolve()
    raw = _read_json(path)
    if raw.get("overlay_type") != "aliases":
        return raw

    base_path = _resolve(path, raw["base_aliases"])
    result = load_alias_document(base_path)
    if isinstance(result.get("nodes"), dict):
        container = result["nodes"]
    else:
        container = result

    for node_id, spec in (raw.get("entries_update") or {}).items():
        if node_id not in container:
            raise ValueError(f"Alias overlay updates unknown node: {node_id}")
        container[node_id] = _apply_entry_patch(container[node_id], spec)

    for node_id, spec in (raw.get("entries_add") or {}).items():
        if node_id in container:
            raise ValueError(f"Alias overlay adds duplicate node: {node_id}")
        container[node_id] = copy.deepcopy(spec)

    if "alias_schema_version" in raw:
        result["alias_schema_version"] = raw["alias_schema_version"]
    if "target_schema" in raw:
        result["target_schema"] = raw["target_schema"]
    return result
