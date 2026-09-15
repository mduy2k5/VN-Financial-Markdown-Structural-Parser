from __future__ import annotations

from pathlib import Path
import tempfile

from .pipeline import FlatParserPipeline
from .preprocess import filter_noise
from .statement_scanner import (
    STATEMENT_FINANCIAL_POSITION,
    STATEMENT_OFF_BALANCE,
    scan_statements,
)
from .textnorm import normalize_lines
from .resource_adapter import build_income_compatible_resources


class IntegratedFinancialPipeline:
    """Route one Markdown financial report into statement-specific resources.

    v0.5.0 intentionally enables only:
      - FINANCIAL_POSITION -> existing B02/B01 universal schema
    - OFF_BALANCE(bank) -> OFF_BALANCE Alias Pack v1.3
    - INCOME_STATEMENT -> Universal Income Statement v1

    Cash-flow ranges are detected and exposed in scanner metadata but are not
    parsed until its canonical resource pack exists.
    """

    def __init__(
        self,
        *,
        financial_schema_path,
        financial_aliases_path,
        universal_guide_path,
        off_balance_schema_path,
        off_balance_aliases_path=None,
        income_schema_path="resources/income_statement_schema.json",
        income_aliases_path="resources/income_statement_aliases.json",
        allow_fuzzy=False,
        allow_unknown_structure=False,
        mapping_strategy="legacy",
    ):
        self.financial = FlatParserPipeline(
            schema_path=financial_schema_path,
            aliases_path=financial_aliases_path,
            universal_guide_path=universal_guide_path,
            allow_fuzzy=allow_fuzzy,
            scope_mode="financial_position",
            allow_unknown_structure=allow_unknown_structure,
            mapping_strategy=mapping_strategy,
        )
        self.mapping_strategy = mapping_strategy
        self.off_balance = FlatParserPipeline(
            schema_path=off_balance_schema_path,
            aliases_path=off_balance_aliases_path,
            universal_guide_path=universal_guide_path,
            allow_fuzzy=allow_fuzzy,
            scope_mode="whole",
            allow_unknown_structure=allow_unknown_structure,
            mapping_strategy=mapping_strategy,
        )
        self._income_resource_dir = tempfile.TemporaryDirectory(prefix="flat-income-")
        income_schema = Path(self._income_resource_dir.name) / "schema.json"
        income_aliases = Path(self._income_resource_dir.name) / "aliases.json"
        build_income_compatible_resources(
            income_schema_path, income_aliases_path, income_schema, income_aliases
        )
        self.income = FlatParserPipeline(
            schema_path=income_schema,
            aliases_path=income_aliases,
            universal_guide_path=universal_guide_path,
            allow_fuzzy=allow_fuzzy,
            scope_mode="whole",
            allow_unknown_structure=allow_unknown_structure,
            mapping_strategy=mapping_strategy,
        )

    @staticmethod
    def _range(scanner: dict, statement_type: str):
        for r in scanner.get("ranges", []):
            if r.get("statement_type") == statement_type:
                return r
        return None

    def parse_text(self, raw_text: str, source_name="input"):
        scan_lines = filter_noise(normalize_lines(raw_text))
        scanner = scan_statements(scan_lines)
        sector = (scanner.get("sector") or {}).get("sector") or "enterprise"

        statements = {}
        routing = []

        fp = self._range(scanner, STATEMENT_FINANCIAL_POSITION)
        if fp:
            result = self.financial.parse_text(
                raw_text,
                source_name=source_name,
                scope_override=(fp["start_line"], fp["end_line"]),
                detected_sector_override=sector,
                statement_profile="financial_position",
            )
            statements["financial_position"] = result
            routing.append({
                "statement_type": STATEMENT_FINANCIAL_POSITION,
                "status": "parsed",
                "resource_profile": "universal_financial_position",
                "range": [fp["start_line"], fp["end_line"]],
            })
        else:
            routing.append({
                "statement_type": STATEMENT_FINANCIAL_POSITION,
                "status": "not_detected",
            })

        ob = self._range(scanner, STATEMENT_OFF_BALANCE)
        if ob:
            if sector == "bank":
                result = self.off_balance.parse_text(
                    raw_text,
                    source_name=source_name,
                    scope_override=(ob["start_line"], ob["end_line"]),
                    detected_sector_override="bank",
                    statement_profile="off_balance",
                )
                statements["off_balance"] = result
                routing.append({
                    "statement_type": STATEMENT_OFF_BALANCE,
                    "status": "parsed",
                    "resource_profile": "off_balance_bank_v1_3",
                    "range": [ob["start_line"], ob["end_line"]],
                })
            else:
                routing.append({
                    "statement_type": STATEMENT_OFF_BALANCE,
                    "status": "resource_unavailable",
                    "sector": sector,
                    "range": [ob["start_line"], ob["end_line"]],
                })
        else:
            routing.append({
                "statement_type": STATEMENT_OFF_BALANCE,
                "status": "not_detected",
            })

        income = self._range(scanner, "INCOME_STATEMENT")
        if income:
            result = self.income.parse_text(
                raw_text,
                source_name=source_name,
                scope_override=(income["start_line"], income["end_line"]),
                detected_sector_override=sector,
                statement_profile="income_statement",
            )
            statements["income_statement"] = result
            routing.append({
                "statement_type": "INCOME_STATEMENT",
                "status": "parsed",
                "resource_profile": "universal_income_statement_v1",
                "range": [income["start_line"], income["end_line"]],
            })
        else:
            routing.append({
                "statement_type": "INCOME_STATEMENT",
                "status": "not_detected",
            })

        detected_unparsed = []
        for r in scanner.get("ranges", []):
            if r.get("statement_type") not in {STATEMENT_FINANCIAL_POSITION, STATEMENT_OFF_BALANCE, "INCOME_STATEMENT"}:
                detected_unparsed.append({
                    "statement_type": r.get("statement_type"),
                    "range": [r.get("start_line"), r.get("end_line")],
                    "confidence": r.get("confidence"),
                    "status": "detected_not_enabled",
                })

        return {
            "source_name": source_name,
            "document_sector": scanner.get("sector"),
            "statement_scanner": scanner,
            "routing": routing,
            "detected_not_enabled": detected_unparsed,
            "statements": statements,
        }

    def parse_file(self, path):
        path = Path(path)
        return self.parse_text(path.read_text(encoding="utf-8-sig"), source_name=path.name)
