"""Hợp đồng output production cho kết quả parser.

Các engine trích xuất giữ chẩn đoán nội bộ đầy đủ cho test và review. Module
này chiếu các object nội bộ thành hợp đồng JSON nhỏ, ổn định để consumer phía
sau dùng mà không phụ thuộc chi tiết triển khai parser.
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
OUTPUT_SCHEMA_VERSION = "2.0.0"
BATCH_SCHEMA_NAME = "vn_financial_report_batch"
BATCH_SCHEMA_VERSION = "2.0.0"
QUALITY_GATE_POLICY = "strict_source_backed_quality_gate_v1"

_NESTED_ROW_FIELDS = {
    "pages",
    "headers",
    "dimensions",
    "values",
    "raw_cells",
    "linked_targets",
}


def stable_report_id(source_sha256: str) -> str:
    """Trả về id suy ra từ nội dung, không phụ thuộc tên file."""

    return f"r_{source_sha256[:16]}"


def report_filename(source_name: str, source_sha256: str) -> str:
    """Trả về tên file báo cáo production dễ đọc và chống va chạm."""

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


def _nullable(value: Any) -> Any:
    """Chuyển chuỗi rỗng ở tầng serializer thành JSON null rõ ràng."""

    if isinstance(value, str) and not value.strip():
        return None
    return value


def _value(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    current_raw = value.get("current")
    previous_raw = value.get("previous")
    additional = value.get("additional")
    if additional is None:
        additional = {}
    result = {
        "current": _number(current_raw),
        "previous": _number(previous_raw),
        "additional": _json_value(additional),
        "note": _nullable(value.get("note")),
        "unit": _nullable(value.get("unit")),
    }
    raw_text = value.get("raw_text", value.get("source_text"))
    # Giữ serialize Markdown/nguồn gốc tách khỏi giá trị số đã chuẩn hóa.
    # Key luôn có để consumer có contract ổn định; ``null`` nghĩa là giá trị
    # được suy ra nhưng không khôi phục được dạng serialize của nguồn.
    result["raw_text"] = _json_value(raw_text)
    result["raw_values"] = {
        "current": current_raw if isinstance(current_raw, str) else None,
        "previous": previous_raw if isinstance(previous_raw, str) else None,
    }
    return result


def _evidence(extraction_meta: Any) -> list[dict[str, Any]]:
    if not isinstance(extraction_meta, dict):
        return []
    occurrences = extraction_meta.get("occurrences") or []
    result: list[dict[str, Any]] = []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        evidence: dict[str, Any] = {
            "source_line": None,
            "source_label": None,
            "raw_text": None,
            "confidence": None,
        }
        line = occurrence.get("source_line", occurrence.get("line"))
        if line is not None:
            evidence["source_line"] = line
        label = occurrence.get("source_label")
        if label:
            evidence["source_label"] = label
        raw_text = occurrence.get("raw_text", occurrence.get("source_text"))
        if raw_text is not None:
            evidence["raw_text"] = _json_value(raw_text)
        confidence = occurrence.get("mapping_confidence", occurrence.get("confidence"))
        if confidence is not None:
            evidence["confidence"] = confidence
        result.append(evidence)
    return result


def _mapping(node: dict[str, Any], *, observation: bool) -> dict[str, Any]:
    """Chuẩn hóa mapping semantic/nguồn thành một object provenance ổn định."""

    meta = node.get("extraction_meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    existing = node.get("mapping")
    if not isinstance(existing, dict):
        existing = {}

    status = existing.get("status") or meta.get("mapping_status")
    target_id = (
        existing.get("target_id")
        or existing.get("mapped_node_id")
        or meta.get("target_id")
        or meta.get("mapped_node_id")
    )
    method = existing.get("method") or meta.get("mapping_method")
    confidence = existing.get("confidence", meta.get("mapping_confidence"))

    if observation:
        status = status or "source_only"
    elif status is None:
        occurrences = [
            occurrence
            for occurrence in (meta.get("occurrences") or [])
            if isinstance(occurrence, dict)
            and (occurrence.get("mapping_method") or occurrence.get("mapping_confidence") is not None)
        ]
        status = "mapped" if occurrences else "not_reported"
        if status == "mapped":
            target_id = target_id or node.get("node_id")
            methods = sorted({
                str(occurrence["mapping_method"])
                for occurrence in occurrences
                if occurrence.get("mapping_method")
            })
            if methods:
                method = methods[0] if len(methods) == 1 else "multiple_evidence_methods"
            confidences = [
                occurrence.get("mapping_confidence")
                for occurrence in occurrences
                if isinstance(occurrence.get("mapping_confidence"), (int, float))
            ]
            if confidences:
                confidence = min(confidences)

    return {
        "status": status,
        "target_id": target_id,
        "method": method,
        "confidence": confidence,
    }


def _attributes(node: dict[str, Any]) -> dict[str, Any]:
    """Trả về cùng một dạng metadata cho mọi record báo cáo."""

    children = node.get("children")
    if not isinstance(children, list):
        children = []
    return {
        "kind": _nullable(node.get("kind")),
        "parent_id": _nullable(node.get("parent_id")),
        "children": list(children),
        "section": _nullable(node.get("section")),
        "sector": _nullable(node.get("sector")),
        "method": _nullable(node.get("method")),
        "form_code": _nullable(node.get("form_code")),
        "code": _nullable(node.get("code")),
        "note_ref": _nullable(node.get("note_ref")),
        # Hierarchy nguồn là một chiều evidence độc lập. Nó không đổi parent_id
        # semantic mà consumer phía sau sử dụng.
        "source_context": _json_value(node.get("source_context")),
    }


def _record(node: dict[str, Any], *, observation_id: str | None = None) -> dict[str, Any]:
    is_observation = observation_id is not None
    return {
        "record_type": "source_observation" if is_observation else "semantic_item",
        "id": observation_id if is_observation else node.get("node_id"),
        "source_id": node.get("node_id") if is_observation else None,
        "label": _nullable(node.get("canonical_name")),
        "attributes": _attributes(node),
        "value": _value(node.get("value")),
        "provenance": {
            "evidence": _evidence(node.get("extraction_meta")),
            "mapping": _mapping(node, observation=is_observation),
        },
    }


def _statement_summary(metrics: dict[str, Any], item_count: int, observation_count: int) -> dict[str, Any]:
    mapping = metrics.get("mapping") or {}
    return {
        "counts": {
            "items": item_count,
            "observations": observation_count,
            "valued_items": metrics.get("value_nodes"),
        },
        "mapping": {
            "input_rows": mapping.get("input_rows"),
            "mapped_rows": mapping.get("mapped_rows"),
            "unmapped_rows": mapping.get("unmapped_rows"),
            "rate": mapping.get("mapping_rate"),
        },
        "coverage": {
            "current": mapping.get("current_coverage"),
            "previous": mapping.get("previous_coverage"),
        },
    }


def _quality_gate(
    canonical: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Quyết định báo cáo có an toàn để dùng semantic ở bước sau không.

    Gate cố ý nghiêm ngặt hơn trạng thái parser thành công. Parser có thể giữ
    evidence nguồn hữu ích nhưng vẫn có scope chưa giải quyết, giá trị semantic
    trùng, kỳ chưa đủ hoặc công thức lỗi. Output đó vẫn có trong ``observations``
    và artifact audit, nhưng được đánh dấu rõ là chỉ review trong contract production.
    """

    parser = metrics.get("parser") or {}
    quality = metrics.get("quality") or {}
    mapping = metrics.get("mapping") or {}
    diagnostics = canonical.get("diagnostics") or {}
    issues: list[str] = []

    statement_status = metrics.get("status") or canonical.get("status") or "not_available"
    if statement_status != "ok":
        issues.append(f"statement_status:{statement_status}")

    value_nodes = metrics.get("value_nodes")
    if isinstance(value_nodes, (int, float)) and value_nodes <= 0:
        issues.append("no_valued_items")

    for key in ("scope_health", "statement_health"):
        value = parser.get(key)
        if value and value not in {"healthy", "locator_routed", "scanner_routed"}:
            issues.append(f"{key}:{value}")

    for key in ("semantic_dedup_conflicts", "source_recovery_conflicts", "unresolved"):
        value = parser.get(key)
        if isinstance(value, (int, float)) and value > 0:
            issues.append(f"{key}:{int(value)}")

    if parser.get("schema_sector_gap"):
        issues.append(f"schema_sector_gap:{parser['schema_sector_gap']}")

    unmapped = mapping.get("unmapped_rows")
    if isinstance(unmapped, (int, float)) and unmapped > 0:
        issues.append(f"unmapped_rows:{int(unmapped)}")

    mapping_rate = mapping.get("mapping_rate")
    if isinstance(mapping_rate, (int, float)) and mapping_rate < 0.95:
        issues.append(f"mapping_rate:{mapping_rate}")

    for period in ("current_coverage", "previous_coverage"):
        coverage = mapping.get(period)
        if isinstance(coverage, (int, float)) and coverage < 0.95:
            issues.append(f"{period}:{coverage}")

    formula_failed = quality.get("formula_failed")
    if isinstance(formula_failed, (int, float)) and formula_failed > 0:
        issues.append(f"formula_failed:{int(formula_failed)}")

    source_mapping = diagnostics.get("source_observation_mapping") or {}
    ambiguous_source = source_mapping.get("ambiguous_source_nodes")
    if isinstance(ambiguous_source, (int, float)) and ambiguous_source > 0:
        issues.append(f"ambiguous_source_observations:{int(ambiguous_source)}")

    # Giữ thứ tự nhưng loại mã issue trùng do nhiều lớp chẩn đoán tạo ra.
    issues = list(dict.fromkeys(issues))
    return {
        "status": "ok" if not issues else "review_required",
        "eligible_for_use": not issues,
        "policy": QUALITY_GATE_POLICY,
        "issues": issues,
    }


def clean_statement(
    canonical: dict[str, Any] | None,
    metrics: dict[str, Any] | None,
    *,
    statement_type: str,
) -> dict[str, Any]:
    """Chiếu một báo cáo nội bộ thành dạng production ổn định.

    Đầu vào:
    - ``canonical``: node và diagnostics do engine statement tạo;
    - ``metrics``: coverage, validation và parser metrics;
    - ``statement_type``: tên B01, B02 hoặc B03 dùng làm fallback.

    Xử lý:
    - tách semantic item khỏi source observation;
    - giữ value, period, mapping, provenance cần cho consumer;
    - áp dụng quality gate và đặt trạng thái ``ok`` hoặc ``review_required``.

    Đầu ra là một statement contract ổn định. Hàm không parse Markdown, không
    map alias và không lấy dữ liệu từ report trước.

    Chẩn đoán parser vẫn nằm trong artifact audit. Hàm này chỉ giữ field mà
    consumer phía sau có thể dựa vào và áp dụng quality gate trước khi đánh dấu
    báo cáo đủ điều kiện sử dụng.
    """
    canonical = canonical or {}
    metrics = metrics or {}
    gate = _quality_gate(canonical, metrics)
    parser = metrics.get("parser") or {}
    items: list[dict[str, Any]] = []
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
            observations.append(_record(raw_node, observation_id=observation_id))
        else:
            items.append(_record(raw_node))

    quality = metrics.get("quality") or {}
    valued_node = next(
        (node for node in canonical.get("nodes") or [] if node.get("value")),
        {},
    )
    parser_sector = parser.get("sector")
    parser_method = parser.get("method")
    sector = canonical.get("sector") or parser_sector or valued_node.get("sector")
    method = canonical.get("method") or parser_method or valued_node.get("method")
    return {
        "status": (
            "ok"
            if gate["eligible_for_use"]
            else "review_required"
        ),
        "statement_type": canonical.get("statement_type") or statement_type,
        "schema": {
            "id": canonical.get("schema_id"),
            "version": canonical.get("schema_version"),
        },
        "context": {
            "sector": _nullable(sector),
            "method": _nullable(method),
            "unit": _nullable(canonical.get("unit") or parser.get("unit")),
        },
        "items": items,
        "observations": observations,
        "summary": _statement_summary(metrics, len(items), len(observations)),
        "validation": {
            "status": quality.get("canonical_status") or metrics.get("status"),
            "formulas": {
                "evaluated": quality.get("formula_evaluated"),
                "passed": quality.get("formula_passed"),
                "failed": quality.get("formula_failed"),
                "pass_rate": quality.get("formula_pass_rate"),
            },
            "gate": gate,
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


def _note_value(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw": value.get("raw"),
        "normalized": value.get("normalized"),
        "period": {
            "label": value.get("period_label"),
            "role": value.get("period_role"),
        },
        "movement_role": value.get("movement_role"),
        "measure": value.get("measure"),
        "unit": {
            "raw": value.get("unit"),
            "canonical": value.get("unit_canonical"),
        },
        "source": {
            "line": value.get("source_line"),
            "column": value.get("source_column"),
        },
    }


def _note_section(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": section.get("note_id_normalized") or section.get("note_id_raw"),
        "title": section.get("title_raw"),
        "title_normalized": section.get("title_normalized"),
        "source": {
            "start_line": section.get("source_start_line"),
            "end_line": section.get("source_end_line"),
            "pages": _json_value(section.get("pages") or []),
        },
        "context": {
            "unit": section.get("unit_canonical") or section.get("unit"),
            "sector_topic": section.get("sector_topic"),
        },
    }


def _note_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    row = _native_row(row, index)
    return {
        "id": row.get("row_id"),
        "note": {
            "id": row.get("note_id_normalized") or row.get("note_id_raw"),
            "title": row.get("note_title"),
            "title_normalized": row.get("note_title_normalized"),
        },
        "label": {
            "raw": row.get("row_label"),
            "normalized": row.get("row_label_normalized"),
        },
        "role": row.get("row_role"),
        "values": [
            _note_value(value)
            for value in (row.get("values") or [])
            if isinstance(value, dict)
        ],
        "dimensions": _json_value(row.get("dimensions") or []),
        "context": {
            "sector": row.get("sector"),
            "sector_topic": row.get("sector_topic"),
            "unit": {
                "raw": row.get("row_unit"),
                "canonical": row.get("row_unit_canonical"),
            },
        },
        "source": {
            "name": row.get("source_name"),
            "line": row.get("row_source_line"),
            "pages": _json_value(row.get("pages") or []),
            "section": {
                "start_line": row.get("section_start_line"),
                "end_line": row.get("section_end_line"),
            },
            "block": {
                "id": row.get("block_id"),
                "form": row.get("block_form"),
                "start_line": row.get("block_start_line"),
                "end_line": row.get("block_end_line"),
            },
            "raw_cells": _json_value(row.get("raw_cells") or []),
        },
        "metadata": {
            "row_code": row.get("row_code"),
            "row_note_ref": row.get("row_note_ref"),
            "semantic_shape": row.get("semantic_shape"),
            "headers": _json_value(row.get("headers") or []),
            "hierarchy_path": _json_value(row.get("hierarchy_path") or []),
            "parser_metadata": _json_value(row.get("metadata") or {}),
            "value_count": row.get("value_count") or len(row.get("values") or []),
        },
        "links": _json_value(row.get("linked_targets") or []),
    }


def _note_raw_blocks(note_ir: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Keep non-tabular source blocks that have no row representation.

    Numeric rows are already exported with raw cells and source columns.  A
    paragraph/narrative block has no such row, so it is retained here instead
    of disappearing from the production Notes view when no alias exists.
    """

    result: list[dict[str, Any]] = []
    for section in (note_ir or {}).get("sections") or []:
        if not isinstance(section, dict):
            continue
        for block in section.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if text is None:
                continue
            result.append({
                "section": {
                    "id": section.get("note_id_normalized") or section.get("note_id_raw"),
                    "title": section.get("title_raw"),
                },
                "id": block.get("block_id"),
                "form": block.get("form"),
                "semantic_shape": block.get("semantic_shape"),
                "source": {
                    "start_line": block.get("source_start_line"),
                    "end_line": block.get("source_end_line"),
                },
                "text": text,
                "metadata": _json_value(block.get("metadata") or {}),
            })
    return result


def clean_notes(note_ir: dict[str, Any] | None, rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Chiếu Notes IR bổ sung thành contract Notes production.

    Đầu vào là Notes IR và các native row đã parse. Hàm chuyển section, row,
    value, link và source location sang schema output thống nhất. Đầu ra có
    trạng thái ``disabled``, ``not_detected`` hoặc ``parsed``; Notes không được
    dùng để ghi đè statement chính.
    """
    if not note_ir:
        return {
            "status": "disabled",
            "schema": {"id": None, "version": None},
            "sections": [],
            "rows": [],
            "raw_blocks": [],
            "links": [],
            "summary": {"section_count": 0, "row_count": 0, "link_count": 0},
        }

    diagnostics = note_ir.get("diagnostics") or {}
    sections = [
        _note_section(section)
        for section in note_ir.get("sections") or []
        if isinstance(section, dict)
    ]

    links = []
    for link in note_ir.get("links") or []:
        if not isinstance(link, dict):
            continue
        links.append(
            {
                "source_ref": link.get("source_ref"),
                "target_ref": link.get("target_ref"),
                "relation": link.get("relation"),
                "confidence": link.get("confidence"),
            }
        )

    native_rows = [
        _note_row(row, index)
        for index, row in enumerate(rows or [], start=1)
        if isinstance(row, dict)
    ]
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
        "raw_blocks": _note_raw_blocks(note_ir),
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
    """Chuẩn hóa cặp năm và metadata kỳ cho output contract.

    Đầu vào là hai năm và dict resolution tùy chọn. Đầu ra là khối ``periods``
    có current, previous, loại kỳ và trạng thái conflict; hàm không suy luận
    lại source.
    """
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
    """Tạo envelope production cuối cho một báo cáo.

    Đầu vào:
    - provenance source và period resolution;
    - ba statement đã qua ``clean_statement``;
    - Notes đã qua ``clean_notes``.

    Xử lý:
    - gắn report id ổn định từ SHA-256;
    - gom statement, Notes và periods vào một contract;
    - tổng hợp status, quality gate và các issue cần review.

    Đầu ra là một dict JSON-serializable có các khối ``contract``, ``report``,
    ``periods``, ``statements``, ``notes`` và ``quality``.
    """
    statements = {
        "financial_position": financial_position,
        "income_statement": income_statement,
        "cash_flow": cash_flow,
    }
    statement_statuses = {name: value.get("status") for name, value in statements.items()}
    review_statuses = {"ok", "parsed", "not_detected", "disabled"}
    period_conflict = bool((year_resolution or {}).get("conflict"))
    issues = [
        f"{name}:{status}"
        for name, status in statement_statuses.items()
        if status not in review_statuses
    ]
    if notes.get("status") not in {"parsed", "not_detected", "disabled"}:
        issues.append(f"notes:{notes.get('status')}")
    statement_gates = {
        name: ((value.get("validation") or {}).get("gate") or {})
        for name, value in statements.items()
    }
    gate_issues = {
        name: list(gate.get("issues") or [])
        for name, gate in statement_gates.items()
        if gate.get("issues")
    }
    for name, statement_issues in gate_issues.items():
        for issue in statement_issues:
            marker = f"{name}:quality_gate:{issue}"
            if marker not in issues:
                issues.append(marker)
    if period_conflict:
        issues.append("periods:conflict")
        gate_issues.setdefault("periods", []).append("period_conflict")
    quality_status = "ok" if not issues else "review_required"
    return {
        "contract": {
            "name": OUTPUT_SCHEMA_NAME,
            "version": OUTPUT_SCHEMA_VERSION,
        },
        "report": {
            "id": stable_report_id(source_sha256),
            "source": {
                "name": source_name,
                "sha256": source_sha256,
            },
        },
        "periods": build_periods(current_year, previous_year, year_resolution),
        "statements": statements,
        "notes": notes,
        "quality": {
            "status": quality_status,
            "issues": issues,
            "statements": statement_statuses,
            "periods": {
                "conflict": period_conflict,
            },
            "gate": {
                "status": quality_status,
                "eligible_for_use": quality_status == "ok",
                "policy": QUALITY_GATE_POLICY,
                "issues": gate_issues,
            },
        },
    }


def manifest_entry(report: dict[str, Any]) -> dict[str, Any]:
    """Tạo một dòng manifest từ production report.

    Đầu vào là report đã được ``build_production_report`` tạo. Xử lý lấy id,
    source, kỳ và trạng thái quality; đầu ra là dict ngắn gọn trỏ tới file
    trong ``reports/`` để batch consumer không phải mở toàn bộ report.
    """
    report_meta = report.get("report") or {}
    source = report_meta.get("source") or {}
    periods = report.get("periods") or {}
    return {
        "report_id": report_meta.get("id"),
        "source": {
            "name": source.get("name"),
            "sha256": source.get("sha256"),
        },
        "path": f"reports/{report_filename(source.get('name'), source.get('sha256'))}",
        "current_year": ((periods.get("current") or {}).get("year")),
        "previous_year": ((periods.get("previous") or {}).get("year")),
        "status": (report.get("quality") or {}).get("status"),
        "statements": (report.get("quality") or {}).get("statements", {}),
        "notes_status": (report.get("notes") or {}).get("status"),
    }
