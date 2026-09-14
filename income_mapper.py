from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = ROOT / "resources" / "income_statement_schema.json"
DEFAULT_ALIASES = ROOT / "resources" / "income_statement_aliases.json"

LABEL_KEYS = (
    "label", "source_label", "canonical_name", "name", "indicator",
    "chi_tieu", "chỉ tiêu", "title", "row_label", "semantic_label",
    "raw_label", "text", "body", "description", "semantic_name"
)
CURRENT_KEYS = (
    "current", "current_value", "this_year", "value_current", "nam_nay",
    "năm nay", "year_current", "current_period_value"
)
PREVIOUS_KEYS = (
    "previous", "previous_value", "last_year", "value_previous", "nam_truoc",
    "năm trước", "year_previous", "previous_period_value"
)
CODE_KEYS = ("code", "form_code", "ma_so", "mã số", "index_code", "display_code", "code_candidate")
NOTE_KEYS = ("note", "thuyet_minh", "thuyết minh", "ocr_note", "note_ref", "note_candidate")
PARENT_KEYS = ("parent_context", "parent_label", "parent", "context", "semantic_parent")
LINE_KEYS = ("source_line", "line_no", "line", "source_lineno", "line_number")
PATTERN_KEYS = ("pattern", "pattern_id", "pattern_name", "extractor", "method", "structural_pattern")
UNIT_KEYS = ("unit", "don_vi", "đơn vị")


def strip_md(s: Any) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"[*_`]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" |:")


def strip_mapping_qualifiers(s: str) -> str:
    s = strip_md(s)
    pats = [
        r"\s*\((?:Thuyết\s*minh|Mục|TM)\b[^)]*\)\s*$",
        r"\s*\([IVXLCDM]+\)\s*$",
        r"\s*\((?:VND|VNĐ|đồng|dong|triệu\s*(?:đồng|VND)?|trieu\s*(?:dong|VND)?)(?:/[^)]*)?\)\s*$",
        r"\s*\((?:Trình\s*bày\s*lại|Trinh\s*bay\s*lai|Điều\s*chỉnh|Dieu\s*chinh)\)\s*$",
        r"\s*\(\d+(?:[a-z])?\)\s*$",
        r"\s*\([^)]*=.+?\)\s*$",
    ]
    changed = True
    while changed:
        changed = False
        for pat in pats:
            ns = re.sub(pat, "", s, flags=re.I).strip()
            if ns != s:
                s, changed = ns, True
    return s


def fold(s: Any) -> str:
    s = strip_mapping_qualifiers(strip_md(s))
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"^\s*(?:\d+|[ivxlcdm]+|[a-z])\s*[.)-]\s*", "", s, flags=re.I)
    s = re.sub(r"\([^)]*(?:=|vnd|dong|triệu|trieu)[^)]*\)", " ", s, flags=re.I)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())




def clean_source_label_and_code(label: Any, code: Any = None):
    """Normalize source labels before semantic mapping without changing display semantics too aggressively."""
    s = strip_md(label)
    # Extract code embedded in labels such as "Doanh thu ... (Mã số 01, Mã tham chiếu 30)"
    # or prefix layouts such as "100.1 Chi phí thuế..." / "44 Doanh thu khác...".
    if code in (None, ""):
        m = re.search(r"(?i)\bMã\s*số\s*[: ]\s*([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)\b", s)
        if m:
            code = m.group(1)
        else:
            mp = re.match(r"^\s*([0-9]{1,3}(?:\.[0-9]+)?|[IVXLC]+)\s*[.)-]?\s+(.+)$", s, flags=re.I)
            if mp:
                code = mp.group(1)
                s = mp.group(2).strip()
    # Remove mapping metadata suffixes while keeping semantic parentheses such as (lỗ)/lãi.
    s = re.sub(r"(?i)\s*\(\s*Mã\s*số\s*[^)]*\)\s*$", "", s).strip()
    s = re.sub(r"(?i)\s*\(\s*Mã\s*tham\s*chiếu\s*[^)]*\)\s*$", "", s).strip()
    # Combined metadata parenthesis.
    s = re.sub(r"(?i)\s*\(\s*Mã\s*số\s*[^)]*Mã\s*tham\s*chiếu[^)]*\)\s*$", "", s).strip()
    # Generic prefixes produced by keyed converters.
    s = re.sub(r"(?i)^(?:Chỉ\s*tiêu|Ghi\s*chú)\s*:\s*", "", s).strip()
    return s, code


def parse_number(v: Any):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = strip_md(v).strip()
    if not s:
        return None
    if s in {"-", "–", "—"}:
        return 0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("() ").replace(" ", "")
    try:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
            val = int(s.replace(".", ""))
        elif re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", s):
            val = int(s.replace(",", ""))
        elif re.fullmatch(r"-?\d+(?:,\d+)", s):
            val = float(s.replace(",", "."))
        elif re.fullmatch(r"-?\d+(?:\.\d+)", s):
            _, b = s.rsplit(".", 1)
            val = int(s.replace(".", "")) if len(b) == 3 else float(s)
        elif re.fullmatch(r"-?\d+", s):
            val = int(s)
        else:
            return None
        return -abs(val) if neg else val
    except Exception:
        return None


def _first(obj: dict, keys, default=None):
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return default


def _year_from_period(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, int) and 2000 <= x <= 2100:
        return x
    s = strip_md(x)
    m = re.search(r"\b(20\d{2})\b", s)
    return int(m.group(1)) if m else None


def _role_from_period(x: Any, current_year=None, previous_year=None) -> Optional[str]:
    f = fold(x)
    y = _year_from_period(x)
    if current_year and y == current_year:
        return "current"
    if previous_year and y == previous_year:
        return "previous"
    if any(k in f for k in ("nam nay", "ky nay", "so cuoi nam", "cuoi nam", "current")):
        return "current"
    if any(k in f for k in ("nam truoc", "ky truoc", "so dau nam", "dau nam", "previous")):
        return "previous"
    return None


def _extract_period_payload(obj: dict, current_year=None, previous_year=None):
    """Hydrate current/previous from heterogeneous converter payloads.

    Supports:
      - current/previous fields
      - value: {current, previous}
      - period_values: [{period/year, value}, ...]
      - periods + values parallel arrays
      - values: [{period, value}, ...]
      - values as {2025: x, 2024: y}
    """
    cur = _first(obj, CURRENT_KEYS)
    prev = _first(obj, PREVIOUS_KEYS)

    value_obj = obj.get("value")
    if isinstance(value_obj, dict):
        if cur is None:
            cur = _first(value_obj, CURRENT_KEYS)
        if prev is None:
            prev = _first(value_obj, PREVIOUS_KEYS)

    def ingest(period, value):
        nonlocal cur, prev
        role = _role_from_period(period, current_year, previous_year)
        if role == "current" and cur is None:
            cur = value
        elif role == "previous" and prev is None:
            prev = value

    pv = obj.get("period_values")
    if isinstance(pv, dict):
        for p, v in pv.items():
            ingest(p, v.get("value") if isinstance(v, dict) else v)
    elif isinstance(pv, list):
        for item in pv:
            if isinstance(item, dict):
                p = _first(item, ("period", "year", "date", "label", "role", "period_label", "period_key"))
                v = _first(item, ("value", "raw_value", "amount", "number", "parsed_value", "normalized_candidate"))
                ingest(p, v)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                ingest(item[0], item[1])

    vals = obj.get("values")
    periods = obj.get("periods")
    if isinstance(vals, dict):
        for p, v in vals.items():
            if isinstance(v, dict):
                vv = _first(v, ("value", "raw_value", "amount", "number", "parsed_value", "normalized_candidate"), v)
            else:
                vv = v
            ingest(p, vv)
    elif isinstance(vals, list):
        if vals and all(isinstance(x, dict) for x in vals):
            for item in vals:
                p = _first(item, ("period", "year", "date", "label", "role", "period_label", "period_key"))
                v = _first(item, ("value", "raw_value", "amount", "number", "parsed_value", "normalized_candidate"))
                ingest(p, v)
        elif isinstance(periods, list) and len(periods) == len(vals):
            for p, v in zip(periods, vals):
                ingest(p, v)

    return parse_number(cur), parse_number(prev)


@dataclass
class IncomeRow:
    label: str
    current: Any = None
    previous: Any = None
    note: Optional[str] = None
    code: Optional[str] = None
    unit: Optional[str] = None
    parent_context: Optional[str] = None
    source_line: Optional[int] = None
    pattern: Optional[str] = None
    raw: Any = None
    node_id: Optional[str] = None
    canonical_name: Optional[str] = None
    mapping_method: Optional[str] = None
    mapping_confidence: Optional[float] = None
    mapping_status: str = "unmapped"


def adapt_row(obj: dict, idx=0, current_year=None, previous_year=None, inherited: Optional[dict] = None) -> IncomeRow:
    inherited = inherited or {}
    label = _first(obj, LABEL_KEYS)
    if not label:
        raise ValueError(f"Row {idx}: missing semantic label")
    raw_code = _first(obj, CODE_KEYS, inherited.get("code"))
    label, raw_code = clean_source_label_and_code(label, raw_code)
    cur, prev = _extract_period_payload(obj, current_year, previous_year)
    if cur is None and inherited.get("current") is not None:
        cur = inherited["current"]
    if prev is None and inherited.get("previous") is not None:
        prev = inherited["previous"]
    return IncomeRow(
        label=str(label),
        current=cur,
        previous=prev,
        note=_first(obj, NOTE_KEYS, inherited.get("note")),
        code=raw_code,
        unit=_first(obj, UNIT_KEYS, inherited.get("unit")),
        parent_context=_first(obj, PARENT_KEYS, inherited.get("parent_context")),
        source_line=_first(obj, LINE_KEYS, inherited.get("source_line", idx + 1)),
        pattern=_first(obj, PATTERN_KEYS, inherited.get("pattern")),
        raw=obj,
    )


def _looks_like_row(obj: dict) -> bool:
    """Return True only for a semantic observation, not a schema/container node.

    Important invariant: code/note metadata alone is NOT enough to make a row.
    A row must carry a numeric/current/previous payload or explicit period/value
    structure. This prevents empty canonical schema nodes from being remapped as
    source observations merely because they have form_code.
    """
    if not any(k in obj and obj[k] not in (None, "") for k in LABEL_KEYS):
        return False

    # Direct current / previous values.
    if any(k in obj and obj[k] not in (None, "") for k in CURRENT_KEYS + PREVIOUS_KEYS):
        return True

    # Explicit period/value carriers.
    for key in ("values", "period_values"):
        if obj.get(key) not in (None, "", [], {}):
            return True

    # Parallel periods only count when values also exist.
    if obj.get("periods") not in (None, "", [], {}) and obj.get("values") not in (None, "", [], {}):
        return True

    # Canonical-like aggregate node. Empty schema nodes must remain containers.
    value_obj = obj.get("value")
    if isinstance(value_obj, dict):
        return any(value_obj.get(k) is not None for k in ("current", "previous", "additional"))
    if value_obj not in (None, "", [], {}):
        return parse_number(value_obj) is not None

    return False


def discover_rows(root: Any, current_year=None, previous_year=None) -> list[IncomeRow]:
    """Recursively discover row observations from the common converter JSON.

    This is intentionally independent of a particular extractor's container name.
    It supports rows/observations/items/data, nested sections, node occurrences,
    and canonical-like node payloads.
    """
    found: list[IncomeRow] = []
    seen_obj_ids = set()

    def walk(x: Any, inherited: Optional[dict] = None):
        inherited = inherited or {}
        if isinstance(x, list):
            for item in x:
                walk(item, inherited)
            return
        if not isinstance(x, dict):
            return
        oid = id(x)
        if oid in seen_obj_ids:
            return
        seen_obj_ids.add(oid)

        # Canonical/debug node with occurrences: occurrences are closest to the
        # original observations and therefore preferred over the aggregate node.
        meta = x.get("extraction_meta")
        if isinstance(meta, dict) and isinstance(meta.get("occurrences"), list) and meta["occurrences"]:
            base_label = _first(x, LABEL_KEYS)
            base_code = _first(x, CODE_KEYS)
            base_value = x.get("value") if isinstance(x.get("value"), dict) else {}
            base_inherited = {
                **inherited,
                "code": base_code or inherited.get("code"),
                "current": base_value.get("current"),
                "previous": base_value.get("previous"),
            }
            for occ in meta["occurrences"]:
                if not isinstance(occ, dict):
                    continue
                occ2 = dict(occ)
                if not _first(occ2, LABEL_KEYS) and base_label:
                    occ2["source_label"] = base_label
                try:
                    found.append(adapt_row(occ2, len(found), current_year, previous_year, base_inherited))
                except ValueError:
                    pass
            # Do not also emit the aggregate node as a duplicate row.
        elif _looks_like_row(x):
            try:
                found.append(adapt_row(x, len(found), current_year, previous_year, inherited))
            except ValueError:
                pass

        # Propagate lightweight context only; never propagate values blindly from
        # arbitrary containers because that creates false period assignments.
        next_inherited = dict(inherited)
        parent_label = _first(x, LABEL_KEYS)
        if parent_label:
            next_inherited["parent_context"] = str(parent_label)
        for key in CODE_KEYS:
            if x.get(key) not in (None, ""):
                next_inherited["code"] = x[key]
                break
        for key in NOTE_KEYS:
            if x.get(key) not in (None, ""):
                next_inherited["note"] = x[key]
                break
        for key in UNIT_KEYS:
            if x.get(key) not in (None, ""):
                next_inherited["unit"] = x[key]
                break

        skip = {"extraction_meta"}
        for k, v in x.items():
            if k in skip:
                continue
            if isinstance(v, (dict, list)):
                walk(v, next_inherited)

    walk(root)
    return dedupe_rows(found)


def dedupe_rows(rows: list[IncomeRow]) -> list[IncomeRow]:
    best = {}
    for r in rows:
        key = (r.source_line, fold(r.label), json.dumps(r.code, ensure_ascii=False, sort_keys=True) if isinstance(r.code, (dict,list)) else str(r.code or ''), json.dumps(r.note, ensure_ascii=False, sort_keys=True) if isinstance(r.note, (dict,list)) else str(r.note or ''))
        score = int(r.current is not None) + int(r.previous is not None) + int(bool(r.code)) + int(bool(r.note))
        if key not in best or score > best[key][0]:
            best[key] = (score, r)
    return [v[1] for v in sorted(best.values(), key=lambda z: ((z[1].source_line or 0), fold(z[1].label)))]


class IncomeMapper:
    def __init__(self, schema_path=DEFAULT_SCHEMA, aliases_path=DEFAULT_ALIASES,
                 sector="enterprise", regex_fallback=True, regex_min_score=0.93, regex_gap=0.08):
        self.schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self.aliases = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
        self.sector = sector
        self.regex_fallback = regex_fallback
        self.regex_min_score = regex_min_score
        self.regex_gap = regex_gap
        self.nodes = {n["node_id"]: n for n in self.schema["nodes"] if n.get("sector") == sector}
        self.exact = {}
        self.code_index = {}
        for nid, n in self.nodes.items():
            labels = [n["canonical_name"]]
            node_alias = self.aliases.get("nodes", {}).get(nid, {})
            labels += node_alias.get("exact", [])
            labels += node_alias.get("aliases", [])

            # v22.1 compatibility: older alias packs may contain node aliases
            # directly at the JSON top level instead of under `nodes`.
            # Merge those aliases conservatively so a malformed/legacy pack
            # does not silently lose sector coverage.
            legacy_alias = self.aliases.get(nid)
            if isinstance(legacy_alias, list):
                labels += legacy_alias
            elif isinstance(legacy_alias, dict):
                labels += legacy_alias.get("exact", [])
                labels += legacy_alias.get("aliases", [])
            for lab in labels:
                self.exact.setdefault(fold(lab), []).append(nid)
            if n.get("form_code"):
                self.code_index.setdefault(str(n["form_code"]).strip().upper(), []).append(nid)

    def map_row(self, row: IncomeRow) -> IncomeRow:
        fl = fold(row.label)
        cands = list(self.exact.get(fl, []))
        method = "exact_alias"

        if not cands and row.parent_context and fl in {"tong cong", "cong", "tong"}:
            pcands = list(self.exact.get(fold(row.parent_context), []))
            if len(set(pcands)) == 1:
                cands = pcands
                method = "parent_total"

        if not cands and row.code:
            cc = self.code_index.get(str(row.code).strip().upper(), [])
            if len(cc) == 1:
                cands = cc
                method = "form_code"

        if not cands and self.regex_fallback and len(fl) >= 8:
            scored = []
            for lab, nids in self.exact.items():
                if len(lab) < 8:
                    continue
                boundary1 = re.search(rf"(?:^| ){re.escape(lab)}(?: |$)", fl)
                boundary2 = re.search(rf"(?:^| ){re.escape(fl)}(?: |$)", lab)
                if boundary1 or boundary2:
                    score = min(len(lab), len(fl)) / max(len(lab), len(fl))
                    for nid in nids:
                        scored.append((score, nid, lab))
            scored.sort(reverse=True)
            if scored and scored[0][0] >= self.regex_min_score:
                top = scored[0]
                second = scored[1][0] if len(scored) > 1 else 0
                top_ids = {x[1] for x in scored if abs(x[0] - top[0]) < 1e-9}
                if len(top_ids) == 1 and top[0] - second >= self.regex_gap:
                    cands = [top[1]]
                    method = "regex_fallback"

        ids = list(dict.fromkeys(cands))
        if len(ids) == 1:
            nid = ids[0]
            n = self.nodes[nid]
            row.node_id = nid
            row.canonical_name = n["canonical_name"]
            row.mapping_method = method
            row.mapping_confidence = 1.0 if method in {"exact_alias", "form_code", "parent_total"} else 0.93
            row.mapping_status = "mapped"
        elif len(ids) > 1:
            row.mapping_status = "ambiguous"
        return row

    def map_rows(self, rows: Iterable[IncomeRow]) -> list[IncomeRow]:
        return [self.map_row(r) for r in rows]

    def canonical(self, rows: list[IncomeRow], source_name="input", current_year=None, previous_year=None):
        by = {nid: {
            "node_id": nid,
            "canonical_name": n["canonical_name"],
            "sector": self.sector,
            "form_code": n.get("form_code"),
            "value": {"current": None, "previous": None, "note": None, "unit": None, "raw_text": None},
            "extraction_meta": {"occurrences": []}
        } for nid, n in self.nodes.items()}
        conflicts = []
        for r in rows:
            if r.mapping_status != "mapped" or not r.node_id:
                continue
            node = by[r.node_id]
            v = node["value"]
            occ = {
                "source_line": r.source_line,
                "source_label": r.label,
                "pattern": r.pattern,
                "mapping_method": r.mapping_method,
                "mapping_confidence": r.mapping_confidence,
                "current": r.current,
                "previous": r.previous,
                "code": r.code,
                "note": r.note,
                "parent_context": r.parent_context,
            }
            node["extraction_meta"]["occurrences"].append(occ)
            for key in ("current", "previous"):
                rv = getattr(r, key)
                if rv is None:
                    continue
                if v[key] is None:
                    v[key] = rv
                elif v[key] != rv:
                    conflicts.append({
                        "node_id": r.node_id, "period": key,
                        "kept": v[key], "incoming": rv,
                        "source_line": r.source_line
                    })
            if v["note"] is None and r.note:
                v["note"] = r.note
            if v["unit"] is None and r.unit:
                v["unit"] = r.unit
            if v["raw_text"] is None:
                v["raw_text"] = r.label

        if self.sector == "bank":
            sign_normalizations = normalize_bank_semantic_signs(by)
        elif self.sector == "securities":
            sign_normalizations = normalize_securities_semantic_signs(by)
        elif self.sector == "enterprise":
            # Formula-only normalization: preserve source-facing canonical values.
            sign_normalizations = normalize_enterprise_formula_signs(by)
        elif self.sector == "insurance":
            sign_normalizations = []
        else:
            sign_normalizations = []

        mapped = sum(r.mapping_status == "mapped" for r in rows)
        ambiguous = sum(r.mapping_status == "ambiguous" for r in rows)
        unmapped = sum(r.mapping_status == "unmapped" for r in rows)
        valued = sum(1 for n in by.values() if n["value"]["current"] is not None or n["value"]["previous"] is not None)
        current_nodes = sum(1 for n in by.values() if n["value"]["current"] is not None)
        previous_nodes = sum(1 for n in by.values() if n["value"]["previous"] is not None)
        both_nodes = sum(1 for n in by.values() if n["value"]["current"] is not None and n["value"]["previous"] is not None)

        mapped_ids = {r.node_id for r in rows if r.mapping_status == "mapped" and r.node_id}
        anchors = CORE_ANCHORS.get(self.sector, set())
        valued_ids = {n["node_id"] for n in by.values() if n.get("value", {}).get("current") is not None or n.get("value", {}).get("previous") is not None}
        anchor_hits = sorted(anchors & (mapped_ids | valued_ids))
        anchor_ratio = (len(anchor_hits) / len(anchors)) if anchors else 1.0
        mapping_rate = (mapped / len(rows)) if rows else 0.0

        status = "ok"
        diagnostic = None
        if not rows:
            status = "source_rows_missing"
            diagnostic = "No income observations were discoverable in the supplied row JSON. This is upstream of semantic mapping."
        elif valued == 0:
            status = "source_values_missing"
            diagnostic = "Semantic rows exist, but none carries current/previous numeric payload. This is upstream period/value hydration, not alias mapping."
        elif mapped == 0:
            status = "mapping_failed"
            diagnostic = "Rows with values exist, but none mapped to the selected income profile."
        elif previous_nodes == 0 and current_nodes > 0:
            status = "period_hydration_incomplete"
            diagnostic = "Current-period values exist but previous-period values were not hydrated from source rows."
        elif mapping_rate < 0.95 or ambiguous > 0:
            status = "partial_mapping"
            diagnostic = "Some discovered income rows remain unmapped or ambiguous; inspect diagnostics.unmapped_rows / ambiguous_rows."
        elif anchor_ratio < 0.75:
            status = "partial_source_coverage"
            diagnostic = "Mapping succeeded for discovered rows, but too few core income-statement anchors were present. Row collection is likely incomplete or the sector profile is not appropriate."

        if self.sector == "bank":
            formula_checks = validate_bank_formulas(by)
        elif self.sector == "securities":
            formula_checks = validate_securities_formulas(by)
        elif self.sector == "insurance":
            formula_checks = validate_insurance_formulas(by)
        else:
            formula_checks = validate_enterprise_formulas(by)
        formula_summary = summarize_formula_checks(formula_checks)
        # Mapping/extraction status and accounting-validation status are separate in v17.
        # A formula mismatch must remain visible for debugging, but it must not relabel
        # a structurally complete extraction as a mapping failure/conflict.
        validation_status = "ok" if formula_summary["failed"] == 0 else "formula_warning"
        validation_diagnostic = None if validation_status == "ok" else (
            "One or more accounting identity checks failed. Canonical source values are preserved; "
            "inspect diagnostics.formula_checks and diagnostics.sign_normalizations."
        )
        unmapped_rows = [
            {"source_line": r.source_line, "label": r.label, "code": r.code, "current": r.current, "previous": r.previous, "parent_context": r.parent_context}
            for r in rows if r.mapping_status == "unmapped"
        ]
        ambiguous_rows = [
            {"source_line": r.source_line, "label": r.label, "code": r.code, "current": r.current, "previous": r.previous, "parent_context": r.parent_context}
            for r in rows if r.mapping_status == "ambiguous"
        ]

        return {
            "schema_id": self.schema["schema_id"],
            "schema_version": self.schema["schema_version"],
            "statement_type": "INCOME_STATEMENT",
            "sector": self.sector,
            "source_name": source_name,
            "periods": {"current": current_year, "previous": previous_year},
            "status": status,
            "diagnostic": diagnostic,
            "validation_status": validation_status,
            "validation_diagnostic": validation_diagnostic,
            "nodes": list(by.values()),
            "conflicts": conflicts,
            "mapping_summary": {
                "rows_total": len(rows),
                "mapped": mapped,
                "ambiguous": ambiguous,
                "unmapped": unmapped,
                "valued_nodes": valued,
                "current_nodes": current_nodes,
                "previous_nodes": previous_nodes,
                "both_period_nodes": both_nodes,
            },
            "diagnostics": {
                "core_anchor_hits": anchor_hits,
                "core_anchor_total": len(anchors),
                "core_anchor_ratio": round(anchor_ratio, 4),
                "unmapped_rows": unmapped_rows,
                "ambiguous_rows": ambiguous_rows,
                "formula_checks": formula_checks,
                "formula_summary": formula_summary,
                "sign_normalizations": sign_normalizations,
            }
        }



CORE_ANCHORS = {
    "bank": {
        "INCOME.BANK.NET_INTEREST_INCOME",
        "INCOME.BANK.PRE_PROVISION_OPERATING_PROFIT",
        "INCOME.BANK.PROFIT_BEFORE_TAX",
        "INCOME.BANK.PROFIT_AFTER_TAX",
    },
    "enterprise": {
        "INCOME.ENTERPRISE.REVENUE_NET",
        "INCOME.ENTERPRISE.GROSS_PROFIT",
        "INCOME.ENTERPRISE.PROFIT_BEFORE_TAX",
        "INCOME.ENTERPRISE.PROFIT_AFTER_TAX",
    },
    "securities": {
        "INCOME.SECURITIES.TOTAL_OPERATING_REVENUE",
        "INCOME.SECURITIES.OPERATING_RESULT",
        "INCOME.SECURITIES.PROFIT_BEFORE_TAX",
        "INCOME.SECURITIES.PROFIT_AFTER_TAX",
    },
    "insurance": {
        "INCOME.INSURANCE.GROSS_INSURANCE_PROFIT",
        "INCOME.INSURANCE.FINANCIAL_PROFIT",
        "INCOME.INSURANCE.PROFIT_BEFORE_TAX",
        "INCOME.INSURANCE.PROFIT_AFTER_TAX",
    },
}

SPECIAL_SECTOR_HINTS = {
    "insurance": (
        "doanh thu phi bao hiem",
        "phi bao hiem goc",
        "phi nhan tai bao hiem",
        "phi nhuong tai bao hiem",
        "doanh thu phi bao hiem thuan",
        "chi boi thuong",
        "kinh doanh bao hiem",
    ),
    "securities": (
        "tai san tai chinh fvtpl",
        "moi gioi chung khoan",
        "tu doanh chung khoan",
        "bao lanh phat hanh chung khoan",
        "luu ky chung khoan",
    ),
}


def detect_special_sector(rows: list[IncomeRow]) -> Optional[str]:
    labels = [fold(r.label) for r in rows]
    for sector, hints in SPECIAL_SECTOR_HINTS.items():
        hits = set()
        for lab in labels:
            for h in hints:
                if h in lab:
                    hits.add(h)
        # Two strong semantic hints are enough; this avoids triggering on a
        # single incidental insurance/security line in a bank/enterprise report.
        if len(hits) >= 2:
            return sector
    return None



BANK_ALWAYS_NEGATIVE_NODES = {
    "INCOME.BANK.INTEREST_EXPENSE",
    "INCOME.BANK.SERVICE_EXPENSE",
    "INCOME.BANK.OTHER_OPERATING_EXPENSE",
    "INCOME.BANK.OPERATING_EXPENSE",
    "INCOME.BANK.CREDIT_RISK_PROVISION_EXPENSE",
    "INCOME.BANK.CURRENT_TAX_EXPENSE",
    "INCOME.BANK.TAX_EXPENSE",
}


def _label_implies_income(label: str | None) -> bool:
    f = fold(label or "")
    return any(x in f for x in ("thu nhap", "loi ich", "hoan nhap"))


def _label_implies_expense(label: str | None) -> bool:
    f = fold(label or "")
    return any(x in f for x in ("chi phi", "lo", "du phong"))


def normalize_bank_semantic_signs(by: dict) -> list[dict]:
    """Normalize bank income-statement values to an additive signed convention.

    Bank formulas below use `sum(parts)`, therefore deduction/expense nodes must be
    negative. Some Vietnamese bank statements print expenses as positive magnitudes
    (BAB), while others already use parentheses/minus (ABB/ACB). We normalize only
    nodes whose semantic role is unambiguously deductive.

    Deferred tax is special: it may be an expense or an income/benefit. Its source
    label controls the sign whenever possible.
    """
    actions = []
    for nid, node in by.items():
        value = node.get("value") or {}
        occs = ((node.get("extraction_meta") or {}).get("occurrences") or [])
        source_label = next((o.get("source_label") for o in occs if o.get("source_label")), value.get("raw_text"))

        if nid in BANK_ALWAYS_NEGATIVE_NODES:
            target_sign = -1
        elif nid == "INCOME.BANK.DEFERRED_TAX_EXPENSE":
            if _label_implies_income(source_label):
                target_sign = 1
            elif _label_implies_expense(source_label):
                target_sign = -1
            else:
                # No semantic evidence: preserve the source sign.
                target_sign = 0
        else:
            continue

        for period in ("current", "previous"):
            old = value.get(period)
            if old is None or target_sign == 0 or not isinstance(old, (int, float)):
                continue
            new = abs(old) * target_sign
            if new != old:
                value[period] = new
                actions.append({
                    "node_id": nid,
                    "period": period,
                    "source_label": source_label,
                    "from": old,
                    "to": new,
                    "reason": "bank_semantic_sign_normalization",
                })
    return actions





ENTERPRISE_PRESENTATION_MAGNITUDE_NODES = {
    "INCOME.ENTERPRISE.REVENUE_DEDUCTIONS",
    "INCOME.ENTERPRISE.COGS",
    "INCOME.ENTERPRISE.FINANCIAL_EXPENSE",
    "INCOME.ENTERPRISE.INTEREST_EXPENSE",
    "INCOME.ENTERPRISE.SELLING_EXPENSE",
    "INCOME.ENTERPRISE.GENERAL_ADMIN_EXPENSE",
    "INCOME.ENTERPRISE.OTHER_EXPENSE",
    "INCOME.ENTERPRISE.CURRENT_TAX_EXPENSE",
}


def normalize_enterprise_formula_signs(by: dict) -> list[dict]:
    """Build a diagnostic sign-normalization view for enterprise formulas.

    Enterprise B02-DN statements are not consistent in presentation sign for cost
    rows: some sources print positive magnitudes, others use parentheses/minus.
    Canonical values are kept faithful to source. Formula validation consumes
    magnitudes for unambiguously deductive rows, so this function records what was
    normalized *for formula semantics only* without mutating canonical values.
    """
    actions = []
    for nid in ENTERPRISE_PRESENTATION_MAGNITUDE_NODES:
        node = by.get(nid) or {}
        value = node.get("value") or {}
        for period in ("current", "previous"):
            old = value.get(period)
            if not isinstance(old, (int, float)):
                continue
            normalized = abs(old)
            if normalized != old:
                actions.append({
                    "node_id": nid,
                    "period": period,
                    "source_value": old,
                    "formula_value": normalized,
                    "reason": "enterprise_formula_magnitude_normalization",
                    "canonical_mutated": False,
                })
    return actions


SECURITIES_ALWAYS_NEGATIVE_NODES = {
    "INCOME.SECURITIES.FVTPL_LOSS",
    "INCOME.SECURITIES.FVTPL_SALE_LOSS",
    "INCOME.SECURITIES.FVTPL_REVALUATION_LOSS",
    "INCOME.SECURITIES.FVTPL_TRANSACTION_EXPENSE",
    "INCOME.SECURITIES.WARRANT_REVALUATION_LOSS",
    "INCOME.SECURITIES.AFS_RECLASSIFICATION_LOSS",
    "INCOME.SECURITIES.PROPRIETARY_TRADING_EXPENSE",
    "INCOME.SECURITIES.BROKERAGE_EXPENSE",
    "INCOME.SECURITIES.UNDERWRITING_EXPENSE",
    "INCOME.SECURITIES.CUSTODY_EXPENSE",
    "INCOME.SECURITIES.FINANCIAL_ADVISORY_EXPENSE",
    "INCOME.SECURITIES.OTHER_SERVICE_EXPENSE",
    "INCOME.SECURITIES.TOTAL_OPERATING_EXPENSE",
    "INCOME.SECURITIES.FX_LOSS",
    "INCOME.SECURITIES.INTEREST_EXPENSE",
    "INCOME.SECURITIES.OTHER_FINANCIAL_EXPENSE",
    "INCOME.SECURITIES.TOTAL_FINANCIAL_EXPENSE",
    "INCOME.SECURITIES.MANAGEMENT_EXPENSE",
    "INCOME.SECURITIES.OTHER_EXPENSE",
    "INCOME.SECURITIES.CURRENT_TAX_EXPENSE",
    "INCOME.SECURITIES.TAX_EXPENSE",
}


def normalize_securities_semantic_signs(by: dict) -> list[dict]:
    """Normalize B02-CTCK to additive signed values.

    A number of CTCK PDFs print expenses as positive magnitudes (BSI), while others
    print them in parentheses (CTS). Canonical values use an additive convention:
    income/gain positive, expense/loss negative. Provision and deferred tax are
    label-sensitive because they may represent reversals/income.
    """
    actions = []
    for nid, node in by.items():
        value = node.get("value") or {}
        occs = ((node.get("extraction_meta") or {}).get("occurrences") or [])
        source_label = next((o.get("source_label") for o in occs if o.get("source_label")), value.get("raw_text"))
        if nid in SECURITIES_ALWAYS_NEGATIVE_NODES:
            target_sign = -1
        elif nid in {"INCOME.SECURITIES.PROVISION_EXPENSE", "INCOME.SECURITIES.DEFERRED_TAX_EXPENSE"}:
            if _label_implies_income(source_label):
                target_sign = 1
            elif _label_implies_expense(source_label):
                target_sign = -1
            else:
                target_sign = 0
        elif nid == "INCOME.SECURITIES.UNREALIZED_PROFIT":
            f = fold(source_label or "")
            target_sign = -1 if "lo chua thuc hien" in f else 0
        else:
            continue
        for period in ("current", "previous"):
            old = value.get(period)
            if old is None or target_sign == 0 or not isinstance(old, (int, float)):
                continue
            new = abs(old) * target_sign
            if new != old:
                value[period] = new
                actions.append({
                    "node_id": nid, "period": period, "source_label": source_label,
                    "from": old, "to": new, "reason": "securities_semantic_sign_normalization",
                })
    return actions


def validate_securities_formulas(by: dict) -> list[dict]:
    checks = []
    def val(nid, period):
        return by.get(nid, {}).get("value", {}).get(period)
    def emit(name, period, reported, expected):
        if reported is None or expected is None:
            checks.append({"name": name, "period": period, "status": "skipped_missing_operand"})
            return
        diff = reported - expected
        tol = max(1e-6, abs(expected) * 1e-9)
        checks.append({
            "name": name, "period": period,
            "status": "pass" if abs(diff) <= tol else "fail",
            "reported": reported, "expected": expected, "difference": diff,
        })
    for period in ("current", "previous"):
        op_rev = val("INCOME.SECURITIES.TOTAL_OPERATING_REVENUE", period)
        op_exp = val("INCOME.SECURITIES.TOTAL_OPERATING_EXPENSE", period)
        fin_inc = val("INCOME.SECURITIES.TOTAL_FINANCIAL_INCOME", period)
        fin_exp = val("INCOME.SECURITIES.TOTAL_FINANCIAL_EXPENSE", period)
        mgmt = val("INCOME.SECURITIES.MANAGEMENT_EXPENSE", period)
        op_result = val("INCOME.SECURITIES.OPERATING_RESULT", period)
        if all(x is not None for x in (op_rev, op_exp, fin_inc, fin_exp, mgmt, op_result)):
            emit("operating_result", period, op_result, op_rev + op_exp + fin_inc + fin_exp + mgmt)
        else:
            checks.append({"name":"operating_result","period":period,"status":"skipped_missing_operand"})

        other_i = val("INCOME.SECURITIES.OTHER_INCOME", period)
        other_e = val("INCOME.SECURITIES.OTHER_EXPENSE", period)
        other_r = val("INCOME.SECURITIES.OTHER_RESULT", period)
        if all(x is not None for x in (other_i, other_e, other_r)):
            emit("other_result", period, other_r, other_i + other_e)
        else:
            checks.append({"name":"other_result","period":period,"status":"skipped_missing_operand"})

        pbt = val("INCOME.SECURITIES.PROFIT_BEFORE_TAX", period)
        if op_result is not None and other_r is not None and pbt is not None:
            emit("profit_before_tax", period, pbt, op_result + other_r)
        else:
            checks.append({"name":"profit_before_tax","period":period,"status":"skipped_missing_operand"})

        cur_tax = val("INCOME.SECURITIES.CURRENT_TAX_EXPENSE", period)
        def_tax = val("INCOME.SECURITIES.DEFERRED_TAX_EXPENSE", period)
        tax_total = val("INCOME.SECURITIES.TAX_EXPENSE", period)
        if cur_tax is not None and def_tax is not None and tax_total is not None:
            emit("tax_expense", period, tax_total, cur_tax + def_tax)
        else:
            checks.append({"name":"tax_expense","period":period,"status":"skipped_missing_operand"})

        pat = val("INCOME.SECURITIES.PROFIT_AFTER_TAX", period)
        if pbt is not None and tax_total is not None and pat is not None:
            emit("profit_after_tax", period, pat, pbt + tax_total)
        else:
            checks.append({"name":"profit_after_tax","period":period,"status":"skipped_missing_operand"})

        oci = val("INCOME.SECURITIES.OTHER_COMPREHENSIVE_INCOME", period)
        total_ci = val("INCOME.SECURITIES.TOTAL_COMPREHENSIVE_INCOME", period)
        if pat is not None and oci is not None and total_ci is not None:
            emit("total_comprehensive_income", period, total_ci, pat + oci)
        else:
            checks.append({"name":"total_comprehensive_income","period":period,"status":"skipped_missing_operand"})
    return checks


def validate_insurance_formulas(by: dict) -> list[dict]:
    """Conservative validation for consolidated insurance income statements.

    Values are already signed in most insurance reports, so identities use
    additive arithmetic exactly as presented. Missing first-page operands are
    skipped rather than treated as failures.
    """
    checks = []
    def val(nid, period):
        return by.get(nid, {}).get("value", {}).get(period)
    def emit(name, period, target, parts):
        reported = val(target, period)
        vals = [val(x, period) for x in parts]
        if reported is None or any(v is None for v in vals):
            checks.append({"name": name, "period": period, "status": "skipped_missing_operand"})
            return
        expected = sum(vals)
        diff = reported - expected
        tol = max(1e-6, abs(expected) * 1e-9)
        checks.append({
            "name": name, "period": period,
            "status": "pass" if abs(diff) <= tol else "fail",
            "reported": reported, "expected": expected, "difference": diff,
        })
    for period in ("current", "previous"):
        emit("net_other_operations", period, "INCOME.INSURANCE.NET_OTHER_OPERATIONS", [
            "INCOME.INSURANCE.OTHER_OPERATING_REVENUE", "INCOME.INSURANCE.OTHER_OPERATING_EXPENSE"])
        emit("financial_profit", period, "INCOME.INSURANCE.FINANCIAL_PROFIT", [
            "INCOME.INSURANCE.FINANCIAL_REVENUE", "INCOME.INSURANCE.FINANCIAL_EXPENSE"])
        emit("other_profit", period, "INCOME.INSURANCE.OTHER_PROFIT", [
            "INCOME.INSURANCE.OTHER_INCOME", "INCOME.INSURANCE.OTHER_EXPENSE"])
        emit("profit_before_tax", period, "INCOME.INSURANCE.PROFIT_BEFORE_TAX", [
            "INCOME.INSURANCE.GROSS_INSURANCE_PROFIT",
            "INCOME.INSURANCE.NET_OTHER_OPERATIONS",
            "INCOME.INSURANCE.FINANCIAL_PROFIT",
            "INCOME.INSURANCE.SHARE_OF_PROFIT_ASSOCIATES",
            "INCOME.INSURANCE.SELLING_EXPENSE",
            "INCOME.INSURANCE.GENERAL_ADMIN_EXPENSE",
            "INCOME.INSURANCE.OTHER_PROFIT",
        ])
        emit("profit_after_tax", period, "INCOME.INSURANCE.PROFIT_AFTER_TAX", [
            "INCOME.INSURANCE.PROFIT_BEFORE_TAX",
            "INCOME.INSURANCE.CURRENT_TAX_EXPENSE",
            "INCOME.INSURANCE.DEFERRED_TAX_EXPENSE",
        ])
        emit("attributable_profit", period, "INCOME.INSURANCE.PROFIT_AFTER_TAX", [
            "INCOME.INSURANCE.PROFIT_ATTRIBUTABLE_PARENT",
            "INCOME.INSURANCE.PROFIT_ATTRIBUTABLE_NCI",
        ])
    return checks


def validate_enterprise_formulas(by: dict) -> list[dict]:
    """Conservative enterprise checks using presentation-magnitude conventions."""
    checks = []

    def val(nid, period):
        return by.get(nid, {}).get("value", {}).get(period)

    def emit(name, period, reported, expected):
        if reported is None or expected is None:
            checks.append({"name": name, "period": period, "status": "skipped_missing_operand"})
            return
        diff = reported - expected
        # Exact integer statements should match; allow tiny float noise.
        tol = max(1e-6, abs(expected) * 1e-9)
        checks.append({
            "name": name,
            "period": period,
            "status": "pass" if abs(diff) <= tol else "fail",
            "reported": reported,
            "expected": expected,
            "difference": diff,
        })

    for period in ("current", "previous"):
        gross = val("INCOME.ENTERPRISE.REVENUE_GROSS", period)
        deductions = val("INCOME.ENTERPRISE.REVENUE_DEDUCTIONS", period)
        net = val("INCOME.ENTERPRISE.REVENUE_NET", period)
        if gross is not None and deductions is not None and net is not None:
            emit("revenue_net", period, net, gross - abs(deductions))
        else:
            checks.append({"name": "revenue_net", "period": period, "status": "skipped_missing_operand"})

        cogs = val("INCOME.ENTERPRISE.COGS", period)
        gp = val("INCOME.ENTERPRISE.GROSS_PROFIT", period)
        if net is not None and cogs is not None and gp is not None:
            emit("gross_profit", period, gp, net - abs(cogs))
        else:
            checks.append({"name": "gross_profit", "period": period, "status": "skipped_missing_operand"})

        oi = val("INCOME.ENTERPRISE.OTHER_INCOME", period)
        oe = val("INCOME.ENTERPRISE.OTHER_EXPENSE", period)
        op = val("INCOME.ENTERPRISE.OTHER_PROFIT", period)
        if oi is not None and oe is not None and op is not None:
            emit("other_profit", period, op, oi - abs(oe))
        else:
            checks.append({"name": "other_profit", "period": period, "status": "skipped_missing_operand"})

        pbt = val("INCOME.ENTERPRISE.PROFIT_BEFORE_TAX", period)
        cur_tax = val("INCOME.ENTERPRISE.CURRENT_TAX_EXPENSE", period)
        def_tax = val("INCOME.ENTERPRISE.DEFERRED_TAX_EXPENSE", period)
        pat = val("INCOME.ENTERPRISE.PROFIT_AFTER_TAX", period)
        if pbt is not None and cur_tax is not None and pat is not None:
            # Deferred tax can be a benefit (negative source number) or expense.
            dt = def_tax if def_tax is not None else 0
            expected = pbt - abs(cur_tax) - dt if dt >= 0 else pbt - abs(cur_tax) + abs(dt)
            emit("profit_after_tax", period, pat, expected)
        else:
            checks.append({"name": "profit_after_tax", "period": period, "status": "skipped_missing_operand"})

    return checks


def summarize_formula_checks(checks: list[dict]) -> dict:
    evaluated = [x for x in checks if x.get("status") in {"pass", "fail"}]
    passed = sum(x.get("status") == "pass" for x in evaluated)
    failed = sum(x.get("status") == "fail" for x in evaluated)
    return {
        "evaluated": len(evaluated),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(evaluated), 6) if evaluated else None,
    }

def validate_bank_formulas(by: dict) -> list[dict]:
    checks = []
    formulas = [
        ("net_interest", "INCOME.BANK.NET_INTEREST_INCOME", ["INCOME.BANK.INTEREST_INCOME", "INCOME.BANK.INTEREST_EXPENSE"]),
        ("net_service", "INCOME.BANK.NET_SERVICE_INCOME", ["INCOME.BANK.SERVICE_INCOME", "INCOME.BANK.SERVICE_EXPENSE"]),
        ("net_other", "INCOME.BANK.NET_OTHER_OPERATING", ["INCOME.BANK.OTHER_OPERATING_INCOME", "INCOME.BANK.OTHER_OPERATING_EXPENSE"]),
        ("profit_before_tax", "INCOME.BANK.PROFIT_BEFORE_TAX", ["INCOME.BANK.PRE_PROVISION_OPERATING_PROFIT", "INCOME.BANK.CREDIT_RISK_PROVISION_EXPENSE"]),
    ]
    for period in ("current", "previous"):
        for name, target, parts in formulas:
            tv = by.get(target, {}).get("value", {}).get(period)
            vals = [by.get(n, {}).get("value", {}).get(period) for n in parts]
            if tv is None or any(v is None for v in vals):
                checks.append({"name": name, "period": period, "status": "skipped_missing_operand"})
                continue
            expected = sum(vals)
            checks.append({
                "name": name, "period": period, "status": "pass" if tv == expected else "fail",
                "reported": tv, "expected": expected, "difference": tv - expected,
            })
    return checks

def auto_sector(rows: list[IncomeRow], schema_path=DEFAULT_SCHEMA, aliases_path=DEFAULT_ALIASES) -> str:
    special = detect_special_sector(rows)
    if special:
        return special
    scores = {}
    for sector in ("bank", "enterprise", "securities", "insurance"):
        m = IncomeMapper(schema_path, aliases_path, sector=sector, regex_fallback=False)
        score = 0
        for r in rows:
            fl = fold(r.label)
            if fl in m.exact:
                score += 2
            if r.code and str(r.code).strip().upper() in m.code_index:
                score += 1
        scores[sector] = score
    if all(v == 0 for v in scores.values()):
        return "unknown"
    return max(scores, key=scores.get)


def infer_years(root: Any, explicit_current=None, explicit_previous=None):
    if explicit_current:
        return explicit_current, explicit_previous or explicit_current - 1
    if isinstance(root, dict):
        periods = root.get("periods")
        if isinstance(periods, dict):
            cy = _year_from_period(periods.get("current"))
            py = _year_from_period(periods.get("previous"))
            if cy:
                return cy, py or cy - 1
    text = json.dumps(root, ensure_ascii=False)
    years = [int(x) for x in re.findall(r"\b(20\d{2})\b", text)]
    if years:
        uniq = sorted(set(years), reverse=True)
        return uniq[0], uniq[1] if len(uniq) > 1 else uniq[0] - 1
    return None, None


def load_rows(path: str | Path, current_year=None, previous_year=None):
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            arr = list(csv.DictReader(f))
        rows = []
        for i, obj in enumerate(arr):
            try:
                rows.append(adapt_row(obj, i, current_year, previous_year))
            except ValueError:
                continue
        return dedupe_rows(rows), current_year, previous_year

    root = json.loads(p.read_text(encoding="utf-8"))
    cy, py = infer_years(root, current_year, previous_year)
    rows = discover_rows(root, cy, py)
    return rows, cy, py


def save_debug_rows(rows: list[IncomeRow], path: str | Path):
    fields = [
        "source_line", "label", "code", "note", "current", "previous", "unit",
        "parent_context", "pattern", "node_id", "canonical_name", "mapping_method",
        "mapping_confidence", "mapping_status"
    ]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: getattr(r, k) for k in fields})
