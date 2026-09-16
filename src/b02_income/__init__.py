"""B02 - Income Statement / Statement of Profit or Loss Package."""

from .extractor import extract_income_fallback, is_non_item_header_or_noise, strip_md
from .mapper import IncomeMapper, IncomeRow, adapt_row, auto_sector, detect_special_sector
from .scope import (
    choose_income_scope,
    clean_value,
    parse_period_line,
)
from .validator import (
    BANK_ALWAYS_NEGATIVE_NODES,
    ENTERPRISE_PRESENTATION_MAGNITUDE_NODES,
    SECURITIES_ALWAYS_NEGATIVE_NODES,
    normalize_bank_semantic_signs,
    normalize_enterprise_formula_signs,
    normalize_securities_semantic_signs,
    summarize_formula_checks,
    validate_bank_formulas,
    validate_enterprise_formulas,
    validate_insurance_formulas,
    validate_securities_formulas,
)

__all__ = [
    "IncomeRow",
    "extract_income_fallback",
    "strip_md",
    "is_non_item_header_or_noise",
    "IncomeMapper",
    "adapt_row",
    "auto_sector",
    "detect_special_sector",
    "choose_income_scope",
    "clean_value",
    "parse_period_line",
    "BANK_ALWAYS_NEGATIVE_NODES",
    "ENTERPRISE_PRESENTATION_MAGNITUDE_NODES",
    "SECURITIES_ALWAYS_NEGATIVE_NODES",
    "normalize_bank_semantic_signs",
    "normalize_enterprise_formula_signs",
    "normalize_securities_semantic_signs",
    "validate_enterprise_formulas",
    "validate_bank_formulas",
    "validate_securities_formulas",
    "validate_insurance_formulas",
    "summarize_formula_checks",
]
