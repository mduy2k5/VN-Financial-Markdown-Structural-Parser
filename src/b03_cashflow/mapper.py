from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from flat_parser.schema_loader import load_alias_document, load_schema_document

def _find_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(5):
        if (cur / "resources").exists():
            return cur
        cur = cur.parent
    return start.resolve().parents[1]

ROOT = _find_root(Path(__file__))
DEFAULT_SCHEMA = ROOT / "resources" / "schemas" / "cash_flow_schema.json"
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


def _form_code_key(value: Any) -> str | None:
    """Chuẩn hóa mã biểu mẫu dòng tiền theo luật định để phân biệt có guard."""

    text = strip_md(value)
    if not text or not re.fullmatch(r"0*\d+(?:\.\d+)?", text):
        return None
    if "." in text:
        major, minor = text.split(".", 1)
        return f"{int(major)}.{minor}"
    return str(int(text))


# Từ ngữ ngữ pháp/hướng biến đổi giữa các layout báo cáo. Đây không phải mã
# báo cáo hay tham chiếu thuyết minh; fallback so sánh khái niệm kế toán từ
# các token còn lại.
_SEMANTIC_VARIANTS = {
    "tang", "giam", "thay", "doi", "bien", "dong",
}


def semantic_label_similarity(left: Any, right: Any) -> float:
    """So sánh khái niệm kế toán cho các biến thể OCR/layout theo quy tắc bảo thủ.

    Khớp chính xác và fuzzy thông thường vẫn là các nhánh chính. Fallback này
    xử lý nhãn như ``Các khoản phải thu`` và ``Tăng, giảm các khoản phải thu``
    mà không tra mã biểu mẫu. Chỉ nhận phần giao rõ có ít nhất ba token không
    thuộc biến thể.
    """
    l_tokens = set(fold(left).split())
    r_tokens = set(fold(right).split())
    l_core = l_tokens - _SEMANTIC_VARIANTS
    r_core = r_tokens - _SEMANTIC_VARIANTS
    if len(l_core) < 3 or len(r_core) < 3:
        return 0.0
    shared = len(l_core & r_core)
    if shared < 3:
        return 0.0
    coverage = shared / min(len(l_core), len(r_core))
    if coverage < 0.80:
        return 0.0
    # Giữ fallback semantic dưới nhãn chính xác nhưng trên ngưỡng thông thường.
    return min(0.96, 0.90 + 0.06 * coverage)


@dataclass
class CFRow:
    label: str
    current: Optional[float]
    previous: Optional[float]
    section: Optional[str]
    method: Optional[str]
    code: Optional[str] = None
    note: Optional[str] = None
    statement_code: Optional[str] = None
    note_ref: Optional[str] = None
    source_line: Optional[int] = None
    pattern: Optional[str] = None
    unit: Optional[str] = None
    raw_text: Optional[str] = None
    parent_label: Optional[str] = None
    hierarchy_path: Optional[str] = None
    mapping_status: str = "unmapped"
    mapped_node_id: Optional[str] = None
    mapping_method: Optional[str] = None
    mapping_confidence: float = 0.0

    def __post_init__(self):
        if self.statement_code is None:
            self.statement_code = self.code
        if self.code is None:
            self.code = self.statement_code
        if self.note_ref is None:
            self.note_ref = self.note
        if self.note is None:
            self.note = self.note_ref


def adapt_cashflow_row(obj: dict) -> CFRow:
    statement_code = obj.get("statement_code")
    if statement_code in (None, ""):
        statement_code = obj.get("code")
    note_ref = obj.get("note_ref")
    if note_ref in (None, ""):
        note_ref = obj.get("note")
    return CFRow(
        label=strip_md(obj.get("source_label") or obj.get("label")),
        current=obj.get("current"), previous=obj.get("previous"),
        section=obj.get("section"), method=obj.get("method"),
        code=strip_md(statement_code) if statement_code not in (None, "") else None,
        note=strip_md(note_ref) if note_ref not in (None, "") else None,
        statement_code=strip_md(statement_code) if statement_code not in (None, "") else None,
        note_ref=strip_md(note_ref) if note_ref not in (None, "") else None,
        source_line=obj.get("source_line"), pattern=obj.get("pattern"),
        unit=obj.get("unit"),
        raw_text=obj.get("raw_text") or obj.get("source_text"),
        parent_label=obj.get("parent_label") or obj.get("parent_context"),
        hierarchy_path=obj.get("hierarchy_path") or obj.get("source_path"),
    )


class CashFlowMapper:
    """Map row B03 theo sector, method và label semantic.

    Mapper lọc schema theo direct/indirect trước khi map. Section giúp loại
    candidate sai ngữ cảnh; form code chỉ là tie-breaker khi code duy nhất và
    label semantic chưa đủ phân biệt.
    """

    def __init__(self, schema_path=DEFAULT_SCHEMA, aliases_path=DEFAULT_ALIASES, sector="enterprise", method="indirect"):
        """Nạp schema/alias cho một profile B03.

        Đầu vào là đường dẫn cấu hình, sector và phương pháp. Xử lý index node,
        form code và alias catalog. Đầu ra là mapper chưa đọc source report.
        """
        self.schema = load_schema_document(schema_path)
        self.aliases = load_alias_document(aliases_path)
        self.sector = sector
        self.method = method
        self.nodes = [n for n in self.schema["nodes"] if n["sector"] == sector and n.get("method", "any") in {"any", method}]
        self.by_id = {n["node_id"]: n for n in self.nodes}
        self.by_form_code = {}
        for node in self.nodes:
            code_key = _form_code_key(node.get("form_code"))
            if code_key:
                self.by_form_code.setdefault(code_key, []).append(node)
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
        """Gán một row B03 vào node phù hợp hoặc để row chưa map.

        Đầu vào là ``CFRow`` có label, section, method và giá trị. Hàm thử
        label exact/fuzzy/semantic trong profile, sau đó chỉ dùng form code
        duy nhất để phân biệt khi cần. Đầu ra là row được cập nhật status,
        node id, method và confidence.
        """
        flabel = fold(row.label)
        best = None
        row_code_key = _form_code_key(row.statement_code or row.code)
        exact_candidate_ids = {
            node["node_id"]
            for node in self.nodes
            if flabel and flabel in self.alias_catalog[node["node_id"]]
        }
        # Identity chính: section + method + nhãn semantic. Mã báo cáo và tham
        # chiếu thuyết minh chỉ giữ làm metadata, không phải identity hay khóa cứu hộ.
        for node in self.nodes:
            aliases = self.alias_catalog[node["node_id"]]
            exact = bool(flabel and flabel in aliases)
            # Nhãn semantic chính xác có thể sửa section bị thiếu/sai do LLM phát ra.
            # Fallback fuzzy và token-semantic vẫn nhận biết section.
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
                    if score == 0.0:
                        token_sim = max((semantic_label_similarity(flabel, a) for a in aliases), default=0.0)
                        if token_sim >= 0.90:
                            score, how = token_sim, "semantic_tokens"
                # Khi source có mã dòng, semantic gần đúng không được vượt
                # qua mã luật định khác. Ví dụ mã 103 ``... cuối năm`` có
                # nhiều token chung với node 101.2 ``... đầu năm`` nhưng đó
                # là hai dòng khác nhau; giữ source-only còn an toàn hơn gán
                # nhầm vào child trước đó.
                node_code_key = _form_code_key(node.get("form_code"))
                if (
                    score >= 0.90
                    and how in {"fuzzy_label", "semantic_tokens"}
                    and row_code_key
                    and node_code_key
                    and row_code_key != node_code_key
                ):
                    score, how = 0.0, None
            if best is None or score > best[0]:
                best = (score, how, node)

        # Bảng theo luật định tách rời có thể mang mã biểu mẫu đáng tin nhưng
        # nhãn bị rút gọn đến mức fuzzy khớp nhầm node semantic (ví dụ
        # ``Tiền và tương đương tiền đầu năm`` với node thay đổi tiền thuần).
        # Chỉ dùng mã làm tie-breaker có guard: mã phải duy nhất trong profile
        # sector+method đã chọn; nhãn semantic chính xác luôn có thẩm quyền.
        # Profile có mã lặp (đặc biệt báo cáo ngân hàng) tiếp tục dựa vào nhãn
        # và evidence section.
        code_key = _form_code_key(row.statement_code or row.code)
        code_candidates = self.by_form_code.get(code_key, []) if code_key else []
        if len(code_candidates) == 1:
            code_node = code_candidates[0]
            exact_best = bool(best and best[1] == "exact_label")
            code_is_exact = code_node["node_id"] in exact_candidate_ids
            if not exact_best or (code_is_exact and best[2]["node_id"] != code_node["node_id"]):
                # Mã duy nhất xác nhận candidate fuzzy/semantic (hoặc thay
                # candidate exact khác node); ghi provenance đúng là
                # code-confirmed. Điều này cần thiết cho các cặp cùng nhãn
                # như ``Tiền`` ở 101.1 và 103.1.
                best = (0.97, "form_code_disambiguation", code_node)
        if best and best[0] >= 0.90:
            row.mapping_status = "mapped"
            row.mapping_confidence = round(best[0], 4)
            row.mapping_method = best[1]
            row.mapped_node_id = best[2]["node_id"]
        return row

    def map_rows(self, rows):
        """Map toàn bộ row B03 và giữ thứ tự source.

        Đầu vào là iterable ``CFRow`` từ extractor. Đầu ra là list row sau khi
        mỗi row đi qua ``map_one``.
        """
        return [self.map_one(r) for r in rows]

    def canonical(self, rows, source_name: str, current_year=None, previous_year=None, statement_unit: Optional[str] = None):
        """Gộp row B03 đã map thành canonical statement.

        Đầu vào là row sau ``map_rows``, provenance source, cặp năm và unit.
        Hàm nhóm theo node, điền hai kỳ, lưu occurrences, phát hiện nhiều giá
        trị xung đột và chạy formula checks. Đầu ra là dict canonical gồm node,
        mapping summary, validation và diagnostics; row chưa map vẫn nằm trong
        danh sách diagnostics.
        """
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
            row_unit = next((r.unit for r in occ if getattr(r, "unit", None)), statement_unit)
            if len({r.current for r in occ if r.current is not None}) > 1 or len({r.previous for r in occ if r.previous is not None}) > 1:
                conflicts.append({"node_id": n["node_id"], "type": "multiple_values"})
            node_out = {
                **n,
                "value": {
                    "current": cur, "previous": prev,
                    "note": next((r.note for r in occ if r.note), None),
                    "unit": row_unit,
                    "raw_text": next((r.raw_text for r in occ if getattr(r, "raw_text", None)),
                                     next((r.label for r in occ), None)),
                },
                "extraction_meta": {"occurrences": [
                    {"source_line": r.source_line, "source_label": r.label, "pattern": r.pattern,
                     "mapping_method": r.mapping_method, "mapping_confidence": r.mapping_confidence,
                     "current": r.current, "previous": r.previous, "code": r.code, "note": r.note,
                     "section": r.section, "method": r.method, "unit": getattr(r, "unit", None),
                     "parent_label": getattr(r, "parent_label", None),
                     "hierarchy_path": getattr(r, "hierarchy_path", None),
                     "raw_text": getattr(r, "raw_text", None)}
                    for r in occ
                ]}
            }
            if occ:
                methods = sorted({str(r.mapping_method) for r in occ if r.mapping_method})
                confidences = [r.mapping_confidence for r in occ if isinstance(r.mapping_confidence, (int, float))]
                node_out["mapping"] = {
                    "status": "mapped",
                    "mapped_node_id": n["node_id"],
                    "method": methods[0] if len(methods) == 1 else "multiple_evidence_methods",
                    "confidence": min(confidences) if confidences else None,
                }
            nodes_out.append(node_out)
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
            "unit": statement_unit,
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
                # Một số cách trình bày theo luật định thêm dòng chỉ phục vụ đối
                # chiếu như chênh lệch quy đổi (mã 62). Lấy nếu có nhưng không
                # bắt buộc với tài liệu không trình bày dòng này.
                optional_ops = [
                    values.get(x, {}).get(period)
                    for x in frm.get("optional_components", [])
                ]
                expected = sum(ops) + sum(v for v in optional_ops if v is not None)
                diff = target - expected
                tol = max(1.0, abs(target) * 1e-6)
                checks.append({"name": frm["name"], "period": period, "status": "pass" if abs(diff) <= tol else "fail",
                               "reported": target, "expected": expected, "difference": diff})
        return checks
