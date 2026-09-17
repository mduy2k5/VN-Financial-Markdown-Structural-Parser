from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from ..common import detect_document_unit, detect_statement_unit
    from ..common.report_period import resolve_report_years
except ImportError:
    from common import detect_document_unit, detect_statement_unit
    from common.report_period import resolve_report_years

from .block_classifier import extract_blocks
from .diagnostics import build_diagnostics
from .linker import link_notes_to_primary
from .note_ir import NoteDocument
from .scanner import detect_notes_scope
from .sectionizer import sectionize_notes
from .sector_profile import classify_topic
from .reconciliation import reconcile_notes
from .unit_normalization import canonical_unit
from .dimension_inference import infer_movement_role


class NotesPipeline:
    def __init__(self, *, current_year: int | None = None, previous_year: int | None = None):
        self.current_year = current_year
        self.previous_year = previous_year

    def parse_text(
        self,
        text: str,
        *,
        source_name: str = "input",
        sector: str = "enterprise",
        scanner_result: Optional[dict] = None,
        primary: Optional[dict] = None,
    ) -> dict:
        period = resolve_report_years(
            text,
            source_name=source_name,
            current_year=self.current_year,
            previous_year=self.previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
        scope = detect_notes_scope(text, scanner_result=scanner_result)
        doc = NoteDocument(
            source_name=source_name,
            sector=sector,
            scope_start_line=scope.start_line,
            scope_end_line=scope.end_line,
            scope_confidence=scope.confidence,
        )

        if not scope.found:
            doc.diagnostics = build_diagnostics(doc, text, scope)
            result = doc.to_dict()
            result["period"] = period
            return result

        sections = sectionize_notes(text, scope)
        all_lines = text.splitlines()
        document_unit = detect_document_unit(text)

        for section in sections:
            section_text = "\n".join(
                all_lines[section.source_start_line - 1: section.source_end_line]
            )
            unit_ctx = detect_statement_unit(
                section_text,
                fallback_unit=document_unit.unit if getattr(document_unit, "unit", None) else None,
            )
            section.unit = getattr(unit_ctx, "unit", None)
            section.unit_raw = getattr(unit_ctx, "source", None)
            section.unit_canonical = canonical_unit(section.unit)
            section.sector_topic = classify_topic(section.title_raw, sector)
            section.blocks = extract_blocks(
                section_text,
                section.source_start_line,
                section.ref,
                current_year=current_year,
                previous_year=previous_year,
            )
            for block in section.blocks:
                if not block.unit:
                    block.unit = section.unit
                block.unit_canonical = canonical_unit(block.unit)
                for row in block.rows:
                    movement_role = infer_movement_role(row.label_raw)
                    for value in row.values:
                        if not value.unit:
                            value.unit = section.unit
                        value.unit_canonical = canonical_unit(value.unit)
                        if block.semantic_shape == "movement" and not value.movement_role:
                            value.movement_role = movement_role

        doc.sections = sections
        link_notes_to_primary(doc, primary=primary)
        reconcile_notes(doc, primary=primary)
        doc.diagnostics = build_diagnostics(doc, text, scope)
        result = doc.to_dict()
        result["period"] = period
        return result

    def parse_file(
        self,
        path,
        *,
        sector: str = "enterprise",
        scanner_result: Optional[dict] = None,
        primary: Optional[dict] = None,
    ) -> dict:
        path = Path(path)
        return self.parse_text(
            path.read_text(encoding="utf-8-sig", errors="replace"),
            source_name=path.name,
            sector=sector,
            scanner_result=scanner_result,
            primary=primary,
        )


def parse_notes(
    text: str,
    *,
    source_name: str = "input",
    sector: str = "enterprise",
    scanner_result: Optional[dict] = None,
    primary: Optional[dict] = None,
    current_year: int | None = None,
    previous_year: int | None = None,
) -> dict:
    return NotesPipeline(current_year=current_year, previous_year=previous_year).parse_text(
        text,
        source_name=source_name,
        sector=sector,
        scanner_result=scanner_result,
        primary=primary,
    )
