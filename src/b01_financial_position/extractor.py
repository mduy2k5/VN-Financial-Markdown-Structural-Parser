from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

try:
    from src.common.source_recovery import extract_financial_position_source_rows, augment_canonical_with_recovered_rows
    from src.common.source_reconciler import reconcile_source_observations
    from src.common.report_period import resolve_report_years
except ImportError:
    from source_recovery import extract_financial_position_source_rows, augment_canonical_with_recovered_rows
    from source_reconciler import reconcile_source_observations
    from report_period import resolve_report_years


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
) -> dict:
    nodes = canonical.get("nodes") or []
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
    metrics = {
        "status": "ok" if valued_n else "no_financial_position_values",
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
        "parser": {
            "statement_profile": "financial_position",
            "schema_id": canonical.get("schema_id"),
            "schema_version": canonical.get("schema_version"),
            "integration_mode": "source_parse",
        },
    }
    return metrics


class FinancialPositionSourceParser:
    """Parse B01 directly from Markdown without reading prior report output."""

    def __init__(
        self,
        *,
        schema_path: Optional[Path] = None,
        aliases_path: Optional[Path] = None,
        guide_path: Optional[Path] = None,
    ):
        # Import lazily so importing the package does not initialize the
        # structural parser before a source document is actually parsed.
        from flat_parser.pipeline import FlatParserPipeline

        project_root = Path(__file__).resolve().parents[2]
        self.parser = FlatParserPipeline(
            schema_path=schema_path or project_root / "resources" / "universal_financial_position_schema_v1_6.json",
            aliases_path=aliases_path or project_root / "resources" / "universal_financial_position_aliases_v1_6_1.json",
            universal_guide_path=guide_path or project_root / "resources" / "universal_structural_guide_a1_a5.json",
            scope_mode="financial_position",
            mapping_strategy="legacy",
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
        if not isinstance(canonical, dict):
            return {
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
                "scope": debug.get("scope_debug") or {},
                "sector": raw_stats.get("detected_sector") or "unknown",
            }

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

        metrics = summarize_canonical(canonical)
        parser_metrics = dict(metrics.get("parser") or {})
        parser_metrics.update({
            "source_name": source_name,
            "source_sha256": source_sha256,
            "source_parser_version": raw_stats.get("parser_version"),
            "source_recovery": "v16.1",
            "recovery_scope_start": recovered.get("scope_start_line"),
            "recovery_scope_end": recovered.get("scope_end_line"),
            "recovery_scope_score": recovered.get("scope_score"),
            "recovered_rows": len(recovered.get("rows") or []),
            "source_recovery_added_nodes": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("added_nodes", 0),
            "source_recovery_filled_nodes": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("filled_existing_nodes", 0),
            "source_recovery_conflicts": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("conflicts", 0),
            "source_statement_health": raw_stats.get("statement_health"),
            "source_scope_health": raw_stats.get("scope_health"),
        })
        metrics["parser"] = parser_metrics
        return {
            "canonical": canonical,
            "metrics": metrics,
            "status": metrics.get("status", "ok"),
            "scope": debug.get("scope_debug") or {},
            "sector": raw_stats.get("detected_sector") or "unknown",
        }
