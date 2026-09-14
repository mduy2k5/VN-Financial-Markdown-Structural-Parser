from __future__ import annotations

from pathlib import Path

from .bullet_flow import BulletDebugFlow
from .bullet_mapping import map_debug_rows_to_canonical
from .preprocess import filter_noise
from .statement_scanner import (
    STATEMENT_CASH_FLOW,
    STATEMENT_FINANCIAL_POSITION,
    STATEMENT_INCOME,
    scan_statements,
)
from .textnorm import normalize_lines


class FlowMappedPipeline:
    """Pure P1-P34 flat-row structural flow followed by the existing semantic mapper.

    Unlike the hybrid pipeline, this engine does not use v0.5 canonical output as
    a base and does not borrow values from v0.5. It is therefore suitable for an
    independent A/B/C comparison.
    """

    def __init__(
        self,
        *,
        financial_schema_path,
        financial_aliases_path,
        universal_guide_path=None,
        off_balance_schema_path=None,
        off_balance_aliases_path=None,
        allow_fuzzy=False,
        allow_unknown_structure=False,
        mapping_strategy="legacy",
    ):
        self.financial_schema_path = financial_schema_path
        self.financial_aliases_path = financial_aliases_path
        self.allow_fuzzy = allow_fuzzy
        self.mapping_strategy = mapping_strategy
        self.flow = BulletDebugFlow()

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
        scanner = scan_statements(filter_noise(normalize_lines(raw_text)))
        sector = (scanner.get("sector") or {}).get("sector") or "enterprise"
        result = {
            "source_name": source_name,
            "engine": f"flow_p1_p34_mapping_{self.mapping_strategy}",
            "mapping_strategy": self.mapping_strategy,
            "statement_scanner": scanner,
            "statements": {},
        }

        fp = self._range(scanner, STATEMENT_FINANCIAL_POSITION)
        if fp:
            rows, structural_debug = self._extract_range(raw_text, fp)
            mapped = map_debug_rows_to_canonical(
                rows,
                schema_path=self.financial_schema_path,
                aliases_path=self.financial_aliases_path,
                allow_fuzzy=self.allow_fuzzy,
                detected_sector=sector,
                mapping_strategy=self.mapping_strategy,
            )
            result["statements"]["financial_position"] = {
                "canonical": mapped["canonical"],
                "debug": {
                    "bullet_flow": structural_debug,
                    "bullet_extracted_rows": [r.debug_dict() for r in rows],
                    **mapped["debug"],
                },
                "stats": mapped["debug"].get("stats", {}),
                "mapping_policy": f"pure_flat_flow_then_{self.mapping_strategy}_mapping",
            }

        # These remain structural-only until resource packs exist.
        for stype, key in [
            (STATEMENT_INCOME, "income_statement_structural"),
            (STATEMENT_CASH_FLOW, "cash_flow_structural"),
        ]:
            r = self._range(scanner, stype)
            if not r:
                continue
            rows, structural_debug = self._extract_range(raw_text, r)
            result["statements"][key] = {
                "canonical": {},
                "debug": {"bullet_flow": structural_debug, "extracted_rows": [x.debug_dict() for x in rows]},
                "stats": {"rows": len(rows), "mapping": "not_enabled_no_resource_pack"},
            }
        return result

    def parse_file(self, path):
        path = Path(path)
        return self.parse_text(path.read_text(encoding="utf-8-sig"), source_name=path.name)
