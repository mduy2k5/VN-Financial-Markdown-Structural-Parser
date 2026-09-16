"""B03 - Cash Flow Statement Package."""

from .extractor import (
    CashFlowObservation,
    choose_cashflow_scope,
    detect_method,
    detect_sector,
    extract_cashflow_fallback,
)
from .mapper import CashFlowMapper, adapt_cashflow_row

__all__ = [
    "CashFlowObservation",
    "choose_cashflow_scope",
    "detect_method",
    "detect_sector",
    "extract_cashflow_fallback",
    "CashFlowMapper",
    "adapt_cashflow_row",
]
