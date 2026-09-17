"""Production output contract for parser results.

The extraction engines keep rich internal diagnostics for tests and review.
This module projects those internal objects into a small, stable JSON contract
that downstream consumers can use without depending on parser implementation
details.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from .source_recovery import parse_number


OUTPUT_SCHEMA_NAME = "vn_financial_report_output"
OUTPUT_SCHEMA_VERSION = "1.0.0"

_NESTED_ROW_FIELDS = {
    "pages",
    "headers",
    "dimensions",
    "values",
    "raw_cells",
    "linked_targets",
}


def stable_report_id(source_sha256: str) -> str:
    """Return a content-derived id that does not depend on a filename."""

    return f"r_{source_sha256[:16]}"


def report_filename(source_name: str, source_sha256: str) -> str:
    """Return a readable, collision-resistant production report filename."""

    stem = Path(source_name or "report").stem or "report"
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip(" ._") or "report"
    stem = stem[:120].rstrip(" ._") or "report"
    if stem.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem.upper()):
        stem = f"report_{stem}"
    return f"{stem}__{source_sha256[:16]}.json"


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if not isinstance(value, float) or math.isfinite(value) else None
    if isinstance(value, str):
        return parse_number(value)
    return None


def _value(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    current_raw = value.get("current")
    previous_raw = value.get("previous")
    result = {
        "current": _number(current_raw),
        "previous": _number(previous_raw),
        "additional": _json_value(value.get("additional")),
        "note": value.get("note"),
        "unit": value.get("unit"),
    }
    raw = {}
    if isinstance(current_raw, str):
        raw["current"] = current_raw
    if isinstance(previous_raw, str):
        raw["previous"] = previous_raw
    if raw:
        result["raw"] = raw
    return result


def _evidence(extraction_meta: Any) -> list[dict[str, Any]]:
    if not isinstance(extraction_meta, dict):
        return []
    occurrences = extraction_meta.get("occurrences") or []
    result: list[dict[str, Any]] = []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        evidence: dict[str, Any] = {}
        line = occurrence.get("source_line", occurrence.get("line"))
        if line is not None:
            evidence["source_line"] = line
        label = occurrence.get("source_label")
        if label:
            evidence["source_label"] = label
        confidence = occurrence.get("mapping_confidence", occurrence.get("confidence"))
        if confidence is not None:
            evidence["confidence"] = confidence
        if evidence:
            result.append(evidence)
    return result


def _node(node: dict[str, Any], *, observation_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if observation_id is not None:
        result["observation_id"] = observation_id
        if node.get("node_id"):
            result["source_node_id"] = node["node_id"]
    else:
        result["node_id"] = node.get("node_id")

    for key in (
        "canonical_name",
        "kind",
        "parent_id",
        "section",
        "sector",
        "method",
        "form_code",
        "code",
        "note_ref",
    ):
        if node.get(key) is not None:
            result[key] = _json_value(node[key])
    if isinstance(node.get("children"), list):
        result["children"] = list(node["children"])
    result["value"] = _value(node.get("value"))
    result["evidence"] = _evidence(node.get("extraction_meta"))
    return result


def _statement_summary(metrics: dict[str, Any], node_count: int, observation_count: int) -> dict[str, Any]:
    mapping = metrics.get("mapping") or {}
    quality = metrics.get("quality") or {}
    return {
        "node_count": node_count,
        "observation_count": observation_count,
        "input_rows": mapping.get("input_rows"),
        "mapped_rows": mapping.get("mapped_rows"),
        "unmapped_rows": mapping.get("unmapped_rows"),
        "mapping_rate": mapping.get("mapping_rate"),
        "current_coverage": mapping.get("current_coverage"),
        "previous_coverage": mapping.get("previous_coverage"),
        "formula_evaluated": quality.get("formula_evaluated"),
        "formula_passed": quality.get("formula_passed"),
        "formula_failed": quality.get("formula_failed"),
        "formula_pass_rate": quality.get("formula_pass_rate"),
    }


def clean_statement(
    canonical: dict[str, Any] | None,
    metrics: dict[str, Any] | None,
    *,
    statement_type: str,
) -> dict[str, Any]:
    canonical = canonical or {}
    metrics = metrics or {}
    parser = metrics.get("parser") or {}
    nodes: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()

    for index, raw_node in enumerate(canonical.get("nodes") or [], start=1):
        if not isinstance(raw_node, dict):
            continue
        kind = raw_node.get("kind") or "semantic"
        node_id = str(raw_node.get("node_id") or "")
        is_observation = kind == "source_observation" or node_id.startswith("SOURCE.")
        if is_observation:
            source_counts[node_id] += 1
            observation_id = f"{node_id or 'source'}#{source_counts[node_id]}"
            observations.append(_node(raw_node, observation_id=observation_id))
        else:
            nodes.append(_node(raw_node))

    quality = metrics.get("quality") or {}
    return {
        "status": metrics.get("status") or canonical.get("status") or "not_available",
        "statement_type": canonical.get("statement_type") or statement_type,
        "schema": {
            "id": canonical.get("schema_id"),
            "version": canonical.get("schema_version"),
        },
        "sector": canonical.get("sector") or parser.get("sector"),
        "method": canonical.get("method") or parser.get("method"),
        "unit": canonical.get("unit"),
        "nodes": nodes,
        "observations": observations,
        "summary": _statement_summary(metrics, len(nodes), len(observations)),
        "validation": {
            "status": quality.get("canonical_status") or metrics.get("status"),
            "formula_evaluated": quality.get("formula_evaluated"),
            "formula_passed": quality.get("formula_passed"),
            "formula_failed": quality.get("formula_failed"),
            "formula_pass_rate": quality.get("formula_pass_rate"),
        },
    }


def _native_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    result = dict(row)
    for field in _NESTED_ROW_FIELDS:
        value = result.get(field)
        if isinstance(value, str):
            try:
                result[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
    block_id = result.get("block_id") or "block"
    row_index = result.get("row_index") or index
    result["row_id"] = f"{block_id}:row:{row_index}"
    return result


def clean_notes(note_ir: dict[str, Any] | None, rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not note_ir:
        return {
            "status": "disabled",
            "schema": {"id": None, "version": None},
            "sections": [],
            "rows": [],
            "links": [],
            "summary": {"section_count": 0, "row_count": 0, "link_count": 0},
        }

    diagnostics = note_ir.get("diagnostics") or {}
    sections = []
    for section in note_ir.get("sections") or []:
        if not isinstance(section, dict):
            continue
        sections.append(
            {
                "note_id": section.get("note_id_normalized") or section.get("note_id_raw"),
                "title": section.get("title_raw"),
                "title_normalized": section.get("title_normalized"),
                "source_start_line": section.get("source_start_line"),
                "source_end_line": section.get("source_end_line"),
                "pages": _json_value(section.get("pages") or []),
                "unit": section.get("unit_canonical") or section.get("unit"),
                "sector_topic": section.get("sector_topic"),
            }
        )

    links = []
    for link in note_ir.get("links") or []:
        if not isinstance(link, dict):
            continue
        links.append(
            {
                key: _json_value(link.get(key))
                for key in ("source_ref", "target_ref", "relation", "confidence")
                if link.get(key) is not None
            }
        )

    native_rows = [_native_row(row, index) for index, row in enumerate(rows or [], start=1)]
    return {
        "status": "parsed" if diagnostics.get("notes_found") else "not_detected",
        "schema": {
            "id": note_ir.get("schema_id"),
            "version": note_ir.get("schema_version"),
        },
        "scope": {
            "start_line": note_ir.get("scope_start_line"),
            "end_line": note_ir.get("scope_end_line"),
            "confidence": note_ir.get("scope_confidence"),
        },
        "sections": sections,
        "rows": native_rows,
        "links": links,
        "summary": {
            "section_count": len(sections),
            "row_count": len(native_rows),
            "link_count": len(links),
        },
    }


def build_periods(
    current_year: int | None,
    previous_year: int | None,
    year_resolution: dict[str, Any] | None,
) -> dict[str, Any]:
    resolution = year_resolution or {}
    return {
        "current": {
            "year": current_year,
            "start_date": resolution.get("current_start_date"),
            "end_date": resolution.get("current_end_date"),
        },
        "previous": {
            "year": previous_year,
            "start_date": resolution.get("previous_start_date"),
            "end_date": resolution.get("previous_end_date"),
        },
        "type": resolution.get("period_type"),
        "resolution": {
            "method": resolution.get("method"),
            "confidence": resolution.get("confidence"),
            "conflict": bool(resolution.get("conflict")),
        },
    }


def build_production_report(
    *,
    source_name: str,
    source_sha256: str,
    current_year: int | None,
    previous_year: int | None,
    year_resolution: dict[str, Any] | None,
    financial_position: dict[str, Any],
    income_statement: dict[str, Any],
    cash_flow: dict[str, Any],
    notes: dict[str, Any],
) -> dict[str, Any]:
    statements = {
        "financial_position": financial_position,
        "income_statement": income_statement,
        "cash_flow": cash_flow,
    }
    statement_statuses = {name: value.get("status") for name, value in statements.items()}
    review_statuses = {"ok", "parsed", "not_detected", "disabled"}
    issues = [
        f"{name}:{status}"
        for name, status in statement_statuses.items()
        if status not in review_statuses
    ]
    if notes.get("status") not in {"parsed", "not_detected", "disabled"}:
        issues.append(f"notes:{notes.get('status')}")
    quality_status = "ok" if not issues and not (year_resolution or {}).get("conflict") else "review_required"
    return {
        "output_schema": {
            "name": OUTPUT_SCHEMA_NAME,
            "version": OUTPUT_SCHEMA_VERSION,
        },
        "report": {
            "id": stable_report_id(source_sha256),
            "source_name": source_name,
            "source_sha256": source_sha256,
        },
        "periods": build_periods(current_year, previous_year, year_resolution),
        "sector": income_statement.get("sector") or cash_flow.get("sector"),
        "statements": statements,
        "notes": notes,
        "quality": {
            "status": quality_status,
            "issues": issues,
            "statement_statuses": statement_statuses,
        },
    }


def manifest_entry(report: dict[str, Any]) -> dict[str, Any]:
    report_meta = report.get("report") or {}
    periods = report.get("periods") or {}
    return {
        "report_id": report_meta.get("id"),
        "source_name": report_meta.get("source_name"),
        "source_sha256": report_meta.get("source_sha256"),
        "path": f"reports/{report_filename(report_meta.get('source_name'), report_meta.get('source_sha256'))}",
        "current_year": ((periods.get("current") or {}).get("year")),
        "previous_year": ((periods.get("previous") or {}).get("year")),
        "status": (report.get("quality") or {}).get("status"),
        "statement_statuses": (report.get("quality") or {}).get("statement_statuses", {}),
        "notes_status": (report.get("notes") or {}).get("status"),
    }
