from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

try:
    from src.common.source_recovery import extract_financial_position_source_rows
    from src.common.source_canonical_hydrator import augment_canonical_with_recovered_rows
    from src.common.source_reconciler import reconcile_source_observations
    from src.common.report_period import resolve_report_years
    from src.common.row_block_scanner import scan_row_blocks, summarize_row_block_scan
except ImportError:
    from source_recovery import extract_financial_position_source_rows
    from source_canonical_hydrator import augment_canonical_with_recovered_rows
    from source_reconciler import reconcile_source_observations
    from report_period import resolve_report_years
    from row_block_scanner import scan_row_blocks, summarize_row_block_scan


def _attach_source_provenance(
    canonical: dict,
    *,
    source_name: str,
    source_sha256: str,
    current_year: int | None,
    previous_year: int | None,
    year_resolution: Optional[dict[str, Any]] = None,
) -> dict:
    canonical["source_name"] = source_name
    canonical["source_sha256"] = source_sha256
    canonical["provenance"] = {
        "source_name": source_name,
        "source_sha256": source_sha256,
        "current_year": current_year,
        "previous_year": previous_year,
    }
    if year_resolution:
        canonical["provenance"]["year_resolution"] = year_resolution
    return canonical


def _set_statement_unit(canonical: dict, unit: Optional[str]) -> dict:
    if not unit or unit == "unknown":
        return canonical
    canonical["unit"] = unit
    for node in canonical.get("nodes", []):
        value = node.get("value")
        if (
            isinstance(value, dict)
            and value.get("unit") is None
            and (value.get("current") is not None or value.get("previous") is not None)
        ):
            value["unit"] = unit
    return canonical


def summarize_canonical(
    canonical: dict,
    *,
    structural_stats: Optional[dict[str, Any]] = None,
) -> dict:
    """Tính metrics production từ canonical B01.

    Đầu vào là dict canonical đã được structural parser tạo. Hàm đếm node có
    giá trị theo từng kỳ và đọc các conflict/recovery diagnostics. Đầu ra là
    dict metrics, không sửa canonical và không đọc source hay output cũ.
    """
    nodes = canonical.get("nodes") or []
    structural_stats = structural_stats or {}
    valued = []
    current = []
    previous = []
    for n in nodes:
        val = n.get("value") or {}
        c, p = val.get("current"), val.get("previous")
        if c is not None or p is not None:
            valued.append(n)
        if c is not None:
            current.append(n)
        if p is not None:
            previous.append(n)
    valued_n = len(valued)
    diagnostics = canonical.get("diagnostics") or {}
    dedup = diagnostics.get("semantic_dedup") or {}
    semantic_conflicts = int(dedup.get("conflict_count") or 0)
    recovery = diagnostics.get("source_statement_recovery") or {}
    source_mapping = diagnostics.get("source_observation_mapping") or {}
    recovery_conflicts = int(recovery.get("conflicts") or 0)
    ambiguous_source_nodes = int(source_mapping.get("ambiguous_source_nodes") or 0)
    source_nodes = int(source_mapping.get("source_nodes") or 0)
    linked_source_nodes = int(source_mapping.get("linked_source_nodes") or 0)
    source_only_nodes = int(source_mapping.get("source_only_nodes") or 0)
    source_mapping_rate = (
        round(linked_source_nodes / source_nodes, 6)
        if source_nodes
        else None
    )
    semantic_input_rows = int(
        structural_stats.get("true_actionable_financial_label_candidates") or 0
    )
    semantic_mapped_rows = int(
        structural_stats.get("matched_financial_labels") or 0
    )
    semantic_unmapped_rows = max(semantic_input_rows - semantic_mapped_rows, 0)
    semantic_mapping_rate = structural_stats.get(
        "true_actionable_semantic_label_coverage"
    )
    if semantic_mapping_rate is None and semantic_input_rows:
        semantic_mapping_rate = round(
            semantic_mapped_rows / semantic_input_rows, 6
        )
    if not valued_n:
        status = "no_financial_position_values"
    elif semantic_conflicts:
        status = "review_required"
    else:
        status = "ok"
    metrics = {
        "status": status,
        "value_nodes": valued_n,
        "current_value_nodes": len(current),
        "previous_value_nodes": len(previous),
        "mapping": {
            "canonical_value_nodes": valued_n,
            "current_value_nodes": len(current),
            "previous_value_nodes": len(previous),
            "current_coverage": round(len(current) / valued_n, 6) if valued_n else 0.0,
            "previous_coverage": round(len(previous) / valued_n, 6) if valued_n else 0.0,
        },
        "semantic_mapping": {
            # Đây là mapping rate chính của B01: chỉ đếm nhãn tài chính nghiệp
            # vụ mà structural parser nhận diện, không đếm nhãn kỳ/thuộc tính,
            # dòng nhiễu hoặc source recovery bổ sung.
            "input_rows": semantic_input_rows,
            "mapped_rows": semantic_mapped_rows,
            "unmapped_rows": semantic_unmapped_rows,
            "mapping_rate": semantic_mapping_rate,
            "basis": "true_actionable_semantic_label_coverage",
        },
        "source_evidence_link": {
            # Chẩn đoán provenance riêng; không dùng làm mapping rate B01 vì
            # source recovery chủ yếu chứa các dòng ngoài schema/chưa có node.
            "input_rows": source_nodes,
            "mapped_rows": linked_source_nodes,
            "unmapped_rows": source_only_nodes,
            "mapping_rate": source_mapping_rate,
            "basis": "source_observation_link",
        },
        "parser": {
            "statement_profile": "financial_position",
            "schema_id": canonical.get("schema_id"),
            "schema_version": canonical.get("schema_version"),
            "integration_mode": "source_parse",
            "semantic_dedup_conflicts": semantic_conflicts,
            "source_recovery_conflicts": recovery_conflicts,
            "ambiguous_source_nodes": ambiguous_source_nodes,
        },
    }
    return metrics


class FinancialPositionSourceParser:
    """Đọc B01 trực tiếp từ Markdown mà không đọc output lần trước.

    Instance giữ một ``FlatParserPipeline`` cho B01. Parser cấu trúc tạo cây
    semantic trước, sau đó source recovery chỉ bổ sung evidence còn thiếu.
    """

    def __init__(
        self,
        *,
        schema_path: Optional[Path] = None,
        aliases_path: Optional[Path] = None,
        guide_path: Optional[Path] = None,
        same_label_recovery: bool = True,
        row_scan_mode: str = "off",
    ):
        """Khởi tạo B01 parser từ schema, alias và structural guide.

        Đầu vào là các path tùy chọn; khi bỏ trống, parser dùng resource chuẩn
        trong repository. Đầu ra là instance giữ structural pipeline, chưa đọc
        một báo cáo cụ thể.
        """
        # Import lazy để import package không khởi tạo structural parser trước
        # khi có source document thực sự cần parse.
        from flat_parser.pipeline import FlatParserPipeline

        project_root = Path(__file__).resolve().parents[2]
        self.same_label_recovery = bool(same_label_recovery)
        if row_scan_mode not in {"off", "shadow", "assist"}:
            raise ValueError(f"Unsupported row_scan_mode: {row_scan_mode}")
        # B01 keeps the structural tree authoritative. The fast scanner is
        # evidence-only here until a tree-constrained integration is proven.
        self.row_scan_mode = row_scan_mode
        self.parser = FlatParserPipeline(
            schema_path=schema_path or project_root / "resources" / "schemas" / "financial_position_schema.json",
            aliases_path=aliases_path or project_root / "resources" / "schemas" / "financial_position_aliases.json",
            universal_guide_path=guide_path or project_root / "resources" / "guides" / "compiled" / "structural_guide.json",
            scope_mode="financial_position",
            mapping_strategy="legacy",
            same_label_recovery=self.same_label_recovery,
        )

    def parse_text(
        self,
        source_text: str,
        *,
        source_name: str,
        source_sha256: Optional[str] = None,
        current_year: int | None = None,
        previous_year: int | None = None,
        fallback_unit: Optional[str] = None,
    ) -> dict:
        """Đọc B01 từ source text và chạy source recovery thận trọng.

        Đầu vào:
        - ``source_text``: toàn bộ Markdown nguồn;
        - ``source_name`` và ``source_sha256``: provenance của file;
        - cặp năm và ``fallback_unit``: ngữ cảnh kỳ/đơn vị nếu source thiếu.

        Xử lý:
        - suy luận kỳ;
        - chạy ``FlatParserPipeline.parse_text`` để dựng canonical B01;
        - trích xuất source rows, hydrate node, reconcile conflict và gắn unit;
        - tính metrics cùng provenance.

        Đầu ra:
        - dict gồm ``canonical``, ``metrics``, ``scope`` và ``sector``;
        - khi parser không tạo canonical, trả trạng thái thiếu source thay vì
          tạo một kết quả rỗng trông như hợp lệ.

        Structural parser tạo semantic node trước. Recovery kiểm tra row nguồn
        để bổ sung kỳ còn thiếu hoặc giữ observation chưa map. Nó không bao giờ
        dùng mã biểu mẫu hoặc số thuyết minh làm identity.
        """
        period = resolve_report_years(
            source_text,
            source_name=source_name,
            current_year=current_year,
            previous_year=previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
        source_sha256 = source_sha256 or hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        result = self.parser.parse_text(
            source_text,
            source_name=source_name,
            statement_profile="financial_position",
        )
        canonical = result.get("canonical") if isinstance(result, dict) else None
        debug = result.get("debug") if isinstance(result, dict) else {}
        debug = debug if isinstance(debug, dict) else {}
        raw_stats = debug.get("stats") if isinstance(debug.get("stats"), dict) else {}
        scope_debug = debug.get("scope_debug") if isinstance(debug.get("scope_debug"), dict) else {}
        scan_start = scope_debug.get("selected_start")
        scan_end = scope_debug.get("selected_end")
        row_block_scan = None
        if self.row_scan_mode != "off" and scan_start and scan_end:
            row_block_scan = scan_row_blocks(
                source_text,
                int(scan_start),
                int(scan_end),
                profile="financial_position",
            )
        if not isinstance(canonical, dict):
            missing_result = {
                "canonical": None,
                "canonical_file": None,
                "metrics": {
                    "status": "financial_position_source_missing",
                    "value_nodes": 0,
                    "current_value_nodes": 0,
                    "previous_value_nodes": 0,
                    "mapping": {
                        "canonical_value_nodes": 0,
                        "current_value_nodes": 0,
                        "previous_value_nodes": 0,
                    },
                    "parser": {
                        "statement_profile": "financial_position",
                        "integration_mode": "source_parse",
                        "source_name": source_name,
                        "source_sha256": source_sha256,
                    },
                },
                "status": "financial_position_source_missing",
                "scope": {
                    **scope_debug,
                    "row_block_scan": row_block_scan,
                },
                "sector": raw_stats.get("detected_sector") or "unknown",
            }
            if self.row_scan_mode != "off":
                missing_result["metrics"]["parser"].update({
                    "row_block_scan_mode": self.row_scan_mode,
                    "row_block_scan": summarize_row_block_scan(row_block_scan),
                })
            return missing_result

        recovered = extract_financial_position_source_rows(
            source_text,
            current_year=current_year,
            previous_year=previous_year,
            fallback_unit=fallback_unit,
        )
        stmt_unit = fallback_unit if fallback_unit and fallback_unit != "unknown" else None
        rec_unit = recovered.get("unit")
        if rec_unit and rec_unit != "unknown":
            stmt_unit = rec_unit
        canonical = augment_canonical_with_recovered_rows(
            canonical,
            recovered.get("rows") or [],
            "FINANCIAL_POSITION",
            same_label_recovery=self.same_label_recovery,
        )
        canonical = reconcile_source_observations(canonical, "FINANCIAL_POSITION")
        canonical = _set_statement_unit(canonical, stmt_unit)
        canonical = _attach_source_provenance(
            canonical,
            source_name=source_name,
            source_sha256=source_sha256,
            current_year=current_year,
            previous_year=previous_year,
            year_resolution=period,
        )

        metrics = summarize_canonical(canonical, structural_stats=raw_stats)
        parser_metrics = dict(metrics.get("parser") or {})
        parser_metrics.update({
            "source_name": source_name,
            "source_sha256": source_sha256,
            "source_parser_version": raw_stats.get("parser_version"),
            "same_label_recovery": self.same_label_recovery,
            "source_recovery": "v16.1",
            "recovery_scope_start": recovered.get("scope_start_line"),
            "recovery_scope_end": recovered.get("scope_end_line"),
            "recovery_scope_score": recovered.get("scope_score"),
            "recovered_rows": len(recovered.get("rows") or []),
            "source_recovery_added_nodes": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("added_nodes", 0),
            "source_recovery_filled_nodes": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("filled_existing_nodes", 0),
            "source_recovery_conflicts": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("conflicts", 0),
            # Đưa trạng thái parser vào production metrics để quality gate
            # không phải đọc audit artifact.
            "statement_health": raw_stats.get("statement_health"),
            "scope_health": raw_stats.get("scope_health"),
            "unresolved": raw_stats.get("unresolved", 0),
            "source_statement_health": raw_stats.get("statement_health"),
            "source_scope_health": raw_stats.get("scope_health"),
            "locator_enabled": raw_stats.get("locator_enabled"),
            "locator_activated": raw_stats.get("locator_activated"),
            "locator_confidence": raw_stats.get("locator_confidence"),
            "locator_alias_hits": raw_stats.get("locator_alias_hits"),
            "locator_candidate_rows": raw_stats.get("locator_candidate_rows"),
        })
        if self.row_scan_mode != "off":
            parser_metrics.update({
                "row_block_scan_mode": self.row_scan_mode,
                "row_block_scan": summarize_row_block_scan(row_block_scan),
            })
        metrics["parser"] = parser_metrics
        return {
            "canonical": canonical,
            "metrics": metrics,
            "status": metrics.get("status", "ok"),
            "scope": {
                **scope_debug,
                "row_block_scan": row_block_scan,
            },
            "sector": raw_stats.get("detected_sector") or "unknown",
        }
