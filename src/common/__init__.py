"""Common utilities for financial statements extraction."""

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
    fold,
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
    "fold",
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
]
