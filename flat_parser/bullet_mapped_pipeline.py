from __future__ import annotations

from pathlib import Path

from .bullet_flow import BulletDebugFlow
from .bullet_mapping import enrich_existing_canonical
from .integrated_pipeline import IntegratedFinancialPipeline
from .preprocess import filter_noise
from .statement_scanner import (
    STATEMENT_CASH_FLOW,
    STATEMENT_FINANCIAL_POSITION,
    STATEMENT_INCOME,
    scan_statements,
)
from .textnorm import normalize_lines


class BulletMappedPipeline:
    """Hybrid pipeline: v0.5 canonical mapping first, P1-P34 only fills missing slots."""

    def __init__(
        self,
        *,
        financial_schema_path,
        financial_aliases_path,
        universal_guide_path,
        off_balance_schema_path,
        off_balance_aliases_path,
        allow_fuzzy=False,
        allow_unknown_structure=False,
        mapping_strategy="legacy",
        hybrid_fill=True,
    ):
        self.financial_schema_path = financial_schema_path
        self.financial_aliases_path = financial_aliases_path
        self.allow_fuzzy = allow_fuzzy
        self.mapping_strategy = mapping_strategy
        self.hybrid_fill = hybrid_fill
        self.flow = BulletDebugFlow()
        self.v05 = IntegratedFinancialPipeline(
            financial_schema_path=financial_schema_path,
            financial_aliases_path=financial_aliases_path,
            universal_guide_path=universal_guide_path,
            off_balance_schema_path=off_balance_schema_path,
            off_balance_aliases_path=off_balance_aliases_path,
            allow_fuzzy=allow_fuzzy,
            allow_unknown_structure=allow_unknown_structure,
            mapping_strategy=mapping_strategy,
        )

    @staticmethod
    def _range(scanner, statement_type):
        for r in scanner.get("ranges", []):
            if r.get("statement_type") == statement_type:
                return r
        return None

    @staticmethod
    def _slice_raw(raw_text: str, start_line: int, end_line: int):
        raw_lines = raw_text.splitlines()
        return "\n".join(raw_lines[max(0, start_line - 1): min(len(raw_lines), end_line)])

    def _extract_range(self, raw_text, r):
        text = self._slice_raw(raw_text, r["start_line"], r["end_line"])
        rows, debug = self.flow.extract(text)
        offset = r["start_line"] - 1
        for row in rows:
            row.source_start_line += offset
            row.source_end_line += offset
        return rows, debug

    def parse_text(self, raw_text: str, source_name="input"):
        # v0.5 remains authoritative for existing canonical packs.
        base = self.v05.parse_text(raw_text, source_name=source_name)
        scanner = base.get("statement_scanner") or scan_statements(filter_noise(normalize_lines(raw_text)))
        sector = (scanner.get("sector") or {}).get("sector") or "enterprise"
        result = base
        result["engine"] = f"hybrid_v05_plus_flat_p1_p34_mapping_{self.mapping_strategy}"
        result["mapping_strategy"] = self.mapping_strategy

        fp = self._range(scanner, STATEMENT_FINANCIAL_POSITION)
        if self.hybrid_fill and fp and (result.get("statements") or {}).get("financial_position"):
            rows, structural_debug = self._extract_range(raw_text, fp)
            fp_result = result["statements"]["financial_position"]
            enriched, enrichment_stats, enrichment_log = enrich_existing_canonical(
                fp_result.get("canonical") or {},
                rows,
                schema_path=self.financial_schema_path,
                aliases_path=self.financial_aliases_path,
                allow_fuzzy=self.allow_fuzzy,
                detected_sector=sector,
                mapping_strategy=self.mapping_strategy,
            )
            fp_result["canonical"] = enriched
            fp_result.setdefault("debug", {})["bullet_flow"] = structural_debug
            fp_result["debug"]["bullet_extracted_rows"] = [r.debug_dict() for r in rows]
            fp_result["debug"]["bullet_enrichment"] = enrichment_log
            fp_result["debug"]["hybrid_stats"] = enrichment_stats
            fp_result["hybrid_policy"] = f"v05_first_bullet_fill_missing_only:{self.mapping_strategy}"

        # Income/cash flow: expose P1-P34 structural rows until canonical packs exist.
        for stype, key in [(STATEMENT_INCOME, "income_statement_structural"), (STATEMENT_CASH_FLOW, "cash_flow_structural")]:
            r = self._range(scanner, stype)
            if not r:
                continue
            rows, structural_debug = self._extract_range(raw_text, r)
            result.setdefault("statements", {})[key] = {
                "canonical": {},
                "debug": {"bullet_flow": structural_debug, "extracted_rows": [x.debug_dict() for x in rows]},
                "stats": {"rows": len(rows), "mapping": "not_enabled_no_resource_pack"},
            }
        return result

    def parse_file(self, path):
        path = Path(path)
        return self.parse_text(path.read_text(encoding="utf-8-sig"), source_name=path.name)
