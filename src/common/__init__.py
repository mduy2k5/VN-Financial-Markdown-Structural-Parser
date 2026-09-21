"""Tiện ích dùng chung để trích xuất báo cáo tài chính."""

from .period_resolver import period_role_for_date
from .value_semantics import (
    UnitContext,
    arithmetic_value,
    clean_text,
    detect_document_unit,
    detect_statement_unit,
    detect_unit,
    fold_text,
    is_note_reference,
    row_unit_override,
)
from .source_recovery import (
    clean,
    extract_financial_position_source_rows,
    extract_generic_statement_rows,
    extract_securities_supplemental_cashflow_rows,
    attach_hierarchy_context,
    fold,
    hierarchy_context_for_lines,
    parse_number,
)
from .source_canonical_hydrator import (
    augment_canonical_with_recovered_rows,
    extract_code_period_table,
    hydrate_canonical_by_form_code,
)
from .source_reconciler import reconcile_source_observations
from .source_observation import augment_from_rows
from .report_period import infer_report_period_context, infer_report_year_pair, resolve_report_years
from .structural_identity import (
    clean_identity_text,
    normalize_identity_label,
    occurrence_rank,
    structural_identity,
)
from .row_block_scanner import (
    ROW_BLOCK_SCAN_VERSION,
    attach_row_block_evidence,
    iter_eligible_read_ranges,
    scan_row_blocks,
    summarize_row_block_scan,
)

__all__ = [
    "period_role_for_date",
    "UnitContext",
    "arithmetic_value",
    "clean_text",
    "detect_document_unit",
    "detect_statement_unit",
    "detect_unit",
    "fold_text",
    "is_note_reference",
    "row_unit_override",
    "augment_canonical_with_recovered_rows",
    "clean",
    "extract_code_period_table",
    "extract_financial_position_source_rows",
    "extract_generic_statement_rows",
    "extract_securities_supplemental_cashflow_rows",
    "attach_hierarchy_context",
    "fold",
    "hierarchy_context_for_lines",
    "hydrate_canonical_by_form_code",
    "parse_number",
    "reconcile_source_observations",
    "augment_from_rows",
    "infer_report_year_pair",
    "infer_report_period_context",
    "resolve_report_years",
    "clean_identity_text",
    "normalize_identity_label",
    "occurrence_rank",
    "structural_identity",
    "ROW_BLOCK_SCAN_VERSION",
    "attach_row_block_evidence",
    "iter_eligible_read_ranges",
    "scan_row_blocks",
    "summarize_row_block_scan",
]
