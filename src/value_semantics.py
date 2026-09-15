from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional


UNIT_UNKNOWN = "unknown"
UNIT_VND = "vnd"
UNIT_THOUSAND_VND = "thousand_vnd"
UNIT_MILLION_VND = "million_vnd"
UNIT_BILLION_VND = "billion_vnd"
UNIT_VND_PER_SHARE = "vnd_per_share"
UNIT_PERCENT = "percent"
UNIT_SHARE = "share"


@dataclass(frozen=True)
class UnitContext:
    unit: str = UNIT_UNKNOWN
    source: str = "unknown"
    confidence: float = 0.0


NOTE_REFERENCE_RE = re.compile(
    r"^(?:"
    r"\d{1,3}(?:\.\d{1,2})?"
    r"|"
    r"[IVXLCDM]+(?:\.[A-Za-z0-9]+)+(?:\([A-Za-z0-9]+\))?"
    r")$",
    re.I,
)


def clean_text(value: Any) -> str:
    s = "" if value is None else str(value)
    s = re.sub(r"[*_`#]+", "", s)
    return re.sub(r"\s+", " ", s).strip(" |:\t\r\n")


def fold_text(value: Any) -> str:
    s = unicodedata.normalize("NFD", clean_text(value))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def is_note_reference(value: Any) -> bool:
    """Recognize note references without deciding semantic role by itself.

    Examples: 28, 31, V.1, V.09, VI.02, V.03.3, V.4(a), V.12(b).
    Callers must still require structural evidence (TM column / code->note->values).
    """
    s = clean_text(value)
    if not s or s.startswith("(") or s.startswith("-"):
        return False
    return bool(NOTE_REFERENCE_RE.fullmatch(s))


CURRENCY_UNITS = {UNIT_MILLION_VND, UNIT_VND, UNIT_BILLION_VND, UNIT_THOUSAND_VND}


def detect_unit(text: Any, *, source: str = "context") -> UnitContext:
    """Detect display unit while preserving original numeric magnitude.

    This function NEVER converts/scales values.
    """
    s = clean_text(text)
    f = fold_text(s)
    if not f:
        return UnitContext()

    # 1. Row-level special unit for EPS
    if re.search(r"(?i)(?:vnd|vnđ|đồng)\s*/\s*(?:cổ\s*phiếu|cp)|(?:đồng|vnd)\s+trên\s+cổ\s*phiếu", s):
        return UnitContext(UNIT_VND_PER_SHARE, source, 1.0)

    # 2. Monetary units (always outrank % in statement/document headers, e.g. "Đơn vị tính: triệu đồng, %")
    if re.search(r"(?i)\b(?:tỷ|ty)\s*(?:đồng|vnd|vnđ)\b", s):
        return UnitContext(UNIT_BILLION_VND, source, 1.0)
    if re.search(r"(?i)\b(?:triệu|trieu)\s*(?:đồng|vnd|vnđ)\b", s):
        return UnitContext(UNIT_MILLION_VND, source, 1.0)
    if re.search(r"(?i)\b(?:nghìn|nghin|ngàn|ngan)\s*(?:đồng|vnd|vnđ)\b", s):
        return UnitContext(UNIT_THOUSAND_VND, source, 1.0)

    # Explicit VND/Đồng (when not part of triệu đồng, etc.)
    if re.search(r"(?i)\b(?:vnd|vnđ|đồng)\b", s) and not re.search(r"(?i)(?:triệu|tỷ|nghìn|ngàn)\b", s):
        return UnitContext(UNIT_VND, source, 0.98)

    # 3. Share count (only explicit share count / unit indicators, not transactions like phát hành cổ phiếu)
    if re.search(r"(?i)(?:\b(?:số\s+lượng|khối\s+lượng)\s*cổ\s*phiếu\b|\((?:cổ\s*phiếu|cp|shares?)\)|\bđơn\s*vị(?:\s*tính)?\s*:\s*(?:cổ\s*phiếu|cp)\b)", s) and not re.search(r"(?i)(?:vnd|vnđ|đồng)\s*/", s):
        return UnitContext(UNIT_SHARE, source, 0.92)

    # 4. Percent (only when no monetary unit present)
    if re.search(r"(?i)(?:%|\bphần\s*trăm\b)", s):
        return UnitContext(UNIT_PERCENT, source, 0.98)

    return UnitContext()


def detect_document_unit(full_text: Any) -> UnitContext:
    """Detect overall document-level currency unit from cover, TOC, audit report, or general notes.

    In VAS financial reporting, all primary statements share the same reporting currency.
    """
    s = "" if full_text is None else str(full_text)
    lines = s.splitlines()

    # Step 1: Search top 300 lines (cover, auditor's report, TOC, first statements)
    for line in lines[:300]:
        if re.search(r"(?i)(?:đơn\s*vị(?:\s*tính|\s*tiền\s*tệ|\s*trình\s*bày)?|don\s*vi)\s*[:：]", line):
            ctx = detect_unit(line, source="document_header")
            if ctx.unit in CURRENCY_UNITS:
                return ctx
        if re.search(r"(?i)đơn\s*vị\s*tiền\s*tệ\s*(?:kế\s*toán\s*)?là\b", line):
            ctx = detect_unit(line, source="document_accounting_currency")
            if ctx.unit in CURRENCY_UNITS:
                return ctx

    # Step 2: Search entire document for explicit currency declarations
    for line in lines:
        if re.search(r"(?i)(?:đơn\s*vị(?:\s*tính|\s*tiền\s*tệ|\s*trình\s*bày)?)\s*[:：]", line):
            ctx = detect_unit(line, source="document_explicit")
            if ctx.unit in CURRENCY_UNITS:
                return ctx

    # Step 3: Check early table headers
    for line in lines[:400]:
        if "|" in line or re.search(r"20\d{2}", line):
            ctx = detect_unit(line, source="document_table_header")
            if ctx.unit in CURRENCY_UNITS:
                return ctx

    return UnitContext()


def detect_statement_unit(text: Any, fallback_unit: Optional[str] = None) -> UnitContext:
    """Detect the most specific statement/page currency unit, no conversion.

    If not found in statement text, falls back to fallback_unit if provided.
    """
    s = "" if text is None else str(text)
    lines = s.splitlines()

    # Prefer explicit unit declaration.
    for line in lines:
        if re.search(r"(?i)(?:đơn\s*vị(?:\s*tính|\s*tiền\s*tệ|\s*trình\s*bày)?|don\s*vi)\s*[:：]", line):
            ctx = detect_unit(line, source="statement_header")
            if ctx.unit in CURRENCY_UNITS:
                return ctx

    # Then table column/header evidence.
    for line in lines[:150]:
        if "|" in line or re.search(r"20\d{2}", line):
            ctx = detect_unit(line, source="table_header")
            if ctx.unit in CURRENCY_UNITS:
                return ctx

    # Check top lines of statement for unit mention
    for line in lines[:60]:
        ctx = detect_unit(line, source="statement_early_context")
        if ctx.unit in CURRENCY_UNITS:
            return ctx

    # Fallback to document unit if statement text has no explicit currency unit
    if fallback_unit and fallback_unit in CURRENCY_UNITS:
        return UnitContext(fallback_unit, source="document_fallback", confidence=0.85)

    return UnitContext()


def row_unit_override(label: Any, inherited: UnitContext) -> UnitContext:
    s = clean_text(label)
    f = fold_text(s)
    if "lai co ban tren co phieu" in f or "lai suy giam tren co phieu" in f or "thu nhap tren moi co phieu" in f:
        return UnitContext(UNIT_VND_PER_SHARE, "row_semantic", 0.99)
    ctx = detect_unit(s, source="row_explicit")
    if ctx.unit != UNIT_UNKNOWN:
        return ctx
    return inherited


def arithmetic_value(value: Any):
    """Arithmetic view only. Canonical/source value must stay None for dash/blank."""
    return 0 if value is None else value


def units_compatible(*units: Optional[str]) -> bool:
    known = [u for u in units if u and u != UNIT_UNKNOWN]
    return len(set(known)) <= 1

