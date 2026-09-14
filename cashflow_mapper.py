from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = ROOT / "resources" / "cash_flow_schema.json"
DEFAULT_ALIASES = ROOT / "resources" / "cash_flow_aliases.json"


def strip_md(s: Any) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"[*_`#]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" |:")


def clean_trailing_parens(s: str) -> str:
    while True:
        sub = re.sub(r"(?<=[A-Za-zÀ-ỹ0-9])\s*\([^)]*\)\s*$", "", s)
        if sub == s:
            break
        s = sub
    return s.strip()


def fold(s: Any) -> str:
    s = strip_md(s)
    s = clean_trailing_parens(s)
    s = re.sub(r"^\s*Chỉ\s*tiêu\s*\d+\s*:\s*", "", s, flags=re.I)
    s = re.sub(r"\s*\((?:Mã\s*số|Thuyết\s*minh|TM|Đơn\s*vị\s*:[^)]*)\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s*\(\d+(?:[a-z])?\)\s*$", "", s, flags=re.I)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"\([^)]*(?:=|ma so|thuyet minh|don vi)[^)]*\)", " ", s)
    s = re.sub(r"\(\s*\d+\s*=\s*[\d\s+–-]+\s*\)", " ", s)
    s = re.sub(r"^\s*(?:\d+|[ivxlcdm]+)\s*[.)-]\s*", "", s, flags=re.I)
    s = re.sub(r"[\"“”'«»]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


@dataclass
class CFRow:
    label: str
    current: Optional[float]
    previous: Optional[float]
    section: Optional[str]
    method: Optional[str]
    code: Optional[str] = None
    note: Optional[str] = None
    source_line: Optional[int] = None
    pattern: Optional[str] = None
    mapping_status: str = "unmapped"
    mapped_node_id: Optional[str] = None
    mapping_method: Optional[str] = None
    mapping_confidence: float = 0.0


def adapt_cashflow_row(obj: dict) -> CFRow:
    return CFRow(
        label=strip_md(obj.get("source_label") or obj.get("label")),
        current=obj.get("current"), previous=obj.get("previous"),
        section=obj.get("section"), method=obj.get("method"),
        code=strip_md(obj.get("code")) if obj.get("code") not in (None, "") else None,
        note=strip_md(obj.get("note")) if obj.get("note") not in (None, "") else None,
        source_line=obj.get("source_line"), pattern=obj.get("pattern"),
    )


class CashFlowMapper:
    def __init__(self, schema_path=DEFAULT_SCHEMA, aliases_path=DEFAULT_ALIASES, sector="enterprise", method="indirect"):
        self.schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self.aliases = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
        self.sector = sector
        self.method = method
        self.nodes = [n for n in self.schema["nodes"] if n["sector"] == sector and n.get("method", "any") in {"any", method}]
        self.by_id = {n["node_id"]: n for n in self.nodes}
        self.alias_catalog = {}
        for n in self.nodes:
            labels = [n["canonical_name"]] + list(self.aliases.get(n["node_id"], []))
            self.alias_catalog[n["node_id"]] = sorted({fold(x) for x in labels if fold(x)})

    def _compatible(self, node, row: CFRow):
        sec = node.get("section")
        if not row.section or not sec or row.section == sec:
            return True
        if sec == "reconciliation" and row.section == "financing":
            return True
        return False

    def map_one(self, row: CFRow):
        flabel = fold(row.label)
        best = None
        # Primary identity: section + method + label. Code is supporting evidence only.
        for node in self.nodes:
            aliases = self.alias_catalog[node["node_id"]]
            exact = bool(flabel and flabel in aliases)
            # Exact semantic label may repair a missing/wrong section emitted by LLM.
            # Fuzzy/code rescue remains section-aware, especially important for bank where codes repeat.
            if not exact and not self._compatible(node, row):
                continue
            if exact:
                score, how = 1.0, "exact_label"
            else:
                score, how = 0.0, None
                if flabel:
                    sim = max((SequenceMatcher(None, flabel, a).ratio() for a in aliases), default=0.0)
                    if sim >= 0.90:
                        score, how = sim, "fuzzy_label"
            ncode = str(node.get("form_code") or "").upper()
            rcode = str(row.code or "").upper()
            if rcode and ncode and rcode == ncode:
                # code can rescue a weak/missing label only within method+section-compatible catalog
                if score < 0.98:
                    score, how = 0.98, "section_code"
            if best is None or score > best[0]:
                best = (score, how, node)
        if best and best[0] >= 0.90:
            row.mapping_status = "mapped"
            row.mapping_confidence = round(best[0], 4)
            row.mapping_method = best[1]
            row.mapped_node_id = best[2]["node_id"]
        return row

    def map_rows(self, rows):
        return [self.map_one(r) for r in rows]

    def canonical(self, rows, source_name: str, current_year=2025, previous_year=2024):
        nodes_out = []
        conflicts = []
        grouped = {}
        for r in rows:
            if r.mapping_status == "mapped" and r.mapped_node_id:
                grouped.setdefault(r.mapped_node_id, []).append(r)
        for n in self.nodes:
            occ = grouped.get(n["node_id"], [])
            cur = next((r.current for r in occ if r.current is not None), None)
            prev = next((r.previous for r in occ if r.previous is not None), None)
            if len({r.current for r in occ if r.current is not None}) > 1 or len({r.previous for r in occ if r.previous is not None}) > 1:
                conflicts.append({"node_id": n["node_id"], "type": "multiple_values"})
            nodes_out.append({
                **n,
                "value": {
                    "current": cur, "previous": prev,
                    "note": next((r.note for r in occ if r.note), None),
                    "unit": None,
                    "raw_text": next((r.label for r in occ), None),
                },
                "extraction_meta": {"occurrences": [
                    {"source_line": r.source_line, "source_label": r.label, "pattern": r.pattern,
                     "mapping_method": r.mapping_method, "mapping_confidence": r.mapping_confidence,
                     "current": r.current, "previous": r.previous, "code": r.code, "note": r.note,
                     "section": r.section, "method": r.method}
                    for r in occ
                ]}
            })
        checks = self._formula_checks(nodes_out)
        evaluated = [x for x in checks if x["status"] in {"pass", "fail"}]
        passed = [x for x in evaluated if x["status"] == "pass"]
        formula_summary = {
            "evaluated": len(evaluated), "passed": len(passed), "failed": len(evaluated)-len(passed),
            "pass_rate": round(len(passed)/len(evaluated), 6) if evaluated else None,
        }
        mapped = sum(1 for r in rows if r.mapping_status == "mapped")
        valued = sum(1 for n in nodes_out if n["value"]["current"] is not None or n["value"]["previous"] is not None)
        rate = (mapped / len(rows)) if rows else 0.0
        validation_status = "ok" if formula_summary["failed"] == 0 else "formula_warning"
        status = "ok"
        if not rows:
            status = "source_rows_missing"
        elif valued == 0:
            status = "source_values_missing"
        elif mapped == 0:
            status = "mapping_failed"
        elif rate < 0.95:
            status = "partial_mapping"
        return {
            "schema_id": self.schema["schema_id"], "schema_version": self.schema["schema_version"],
            "statement_type": "CASH_FLOW_STATEMENT", "sector": self.sector, "method": self.method,
            "source_name": source_name, "periods": {"current": current_year, "previous": previous_year},
            "status": status, "validation_status": validation_status, "nodes": nodes_out, "conflicts": conflicts,
            "mapping_summary": {"rows_total": len(rows), "mapped": mapped, "unmapped": len(rows)-mapped, "valued_nodes": valued, "mapping_rate": round(rate, 6)},
            "diagnostics": {
                "unmapped_rows": [
                    {"source_line": r.source_line, "label": r.label, "section": r.section, "code": r.code,
                     "current": r.current, "previous": r.previous} for r in rows if r.mapping_status != "mapped"
                ],
                "formula_checks": checks, "formula_summary": formula_summary, "validation_status": validation_status,
            }
        }

    def _formula_checks(self, nodes):
        values = {n["node_id"]: n["value"] for n in nodes}
        checks = []
        formulas = self.schema.get("formulas", {}).get(self.sector, [])
        for frm in formulas:
            if frm.get("method") not in (None, "any", self.method):
                continue
            for period in ("current", "previous"):
                target = values.get(frm["target"], {}).get(period)
                ops = [values.get(x, {}).get(period) for x in frm["components"]]
                if target is None or any(v is None for v in ops):
                    checks.append({"name": frm["name"], "period": period, "status": "skipped_missing_operand"})
                    continue
                expected = sum(ops)
                diff = target - expected
                tol = max(1.0, abs(target) * 1e-6)
                checks.append({"name": frm["name"], "period": period, "status": "pass" if abs(diff) <= tol else "fail",
                               "reported": target, "expected": expected, "difference": diff})
        return checks
