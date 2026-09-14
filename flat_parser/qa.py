from __future__ import annotations

import re
from typing import Iterable

from .models import StructuralNode
from .textnorm import fold


TOTAL_LABELS = {
    "TOTAL_ASSETS": {
        "tong tai san",
        "tong cong tai san",
        "tong tai san co",
        "tong cong tai san co",
    },
    "TOTAL_LIABILITIES": {
        "tong no phai tra",
        "tong cong no phai tra",
    },
    "TOTAL_EQUITY": {
        "tong von chu so huu",
        "tong cong von chu so huu",
        "tong von",
    },
    "TOTAL_LIABILITIES_AND_EQUITY": {
        "tong nguon von",
        "tong cong nguon von",
        "tong no phai tra va von chu so huu",
        "tong cong no phai tra va von chu so huu",
    },
}


def _clean_financial_label(text: str) -> str:
    f = fold(text or "").strip()
    # Strip markdown/key wrappers and common numbering/formula suffixes.
    f = re.sub(r"^(?:tieu de|ten bao cao|report title)\s*:\s*", "", f)
    f = re.sub(r"^(?:(?:[a-z]|[ivxlc]+|\d+(?:\.\d+)*)\s*[-–—.:)]\s*)+", "", f)
    f = re.sub(r"\s*\([^)]*(?:=|ma so|thuyet minh)[^)]*\)\s*$", "", f)
    return f.strip(" *_:-")


def detect_sector(raw_text: str, catalog) -> dict:
    f = fold(raw_text or "")
    evidence = []

    securities_hits = 0
    for token in (
        "b01 - ctck",
        "b01 – ctck",
        "b01-ctck",
        "cong ty chung khoan",
        "tai san tai chinh fvtpl",
        "tai san tai chinh afs",
        "tai san tai chinh htm",
    ):
        if token in f:
            securities_hits += 1
            evidence.append(token)

    insurance_tokens = (
        "bao hiem", "tai bao hiem", "du phong toan hoc",
        "du phong boi thuong", "du phong phi chua duoc huong",
    )
    insurance_hits = [tok for tok in insurance_tokens if tok in f]

    if securities_hits >= 1:
        detected = "securities"
    elif len(insurance_hits) >= 2:
        detected = "insurance"
        evidence.extend(insurance_hits[:6])
    elif "ngan hang" in f or "tctd" in f or "b02/tctd" in f:
        detected = "bank"
        evidence.append("bank/tctd marker")
    else:
        detected = "enterprise"
        evidence.append("default enterprise")

    schema_sectors = sorted({spec.sector for spec in catalog.nodes.values() if spec.sector})
    supported = detected in schema_sectors or detected in {"enterprise", "bank"} and detected in schema_sectors
    # common does not mean the sector taxonomy itself is covered.
    gap = detected if not supported else None

    return {
        "detected_sector": detected,
        "evidence": evidence[:12],
        "schema_sectors": schema_sectors,
        "schema_sector_gap": gap,
    }


def _node_has_local_payload(node: StructuralNode, nodes: list[StructuralNode]) -> bool:
    if node.values or node.periods or node.inherited_period:
        return True
    queue = [(idx, 1) for idx in node.children]
    seen = set()
    while queue:
        idx, depth = queue.pop(0)
        if idx in seen or depth > 2:
            continue
        seen.add(idx)
        d = nodes[idx]
        if d.pattern_id in {"SP_NAMED_ATTRIBUTE", "SP_PERIOD_VALUE_ATTRIBUTE"}:
            if d.values or d.periods or d.inherited_period:
                return True
            continue
        if d.values or d.periods or d.inherited_period:
            return True
        for c in d.children:
            queue.append((c, depth + 1))
    return False




NOISE_LABEL_PATTERNS = [
    # Page / extraction metadata.
    re.compile(r"^(?:page|trang)(?:\s*\d+)?$"),
    re.compile(r"^(?:_?id|s3_key|search_folder|category|created_at|file_name|page_ocr_at|page_ocr_status|period|status|symbol|updated_at|year|msdn)$"),

    # Units and unit-only cells.
    re.compile(r"^\(?\s*(?:don vi|unit|khong ro don vi|dong|vnd|trieu dong|trieu vnd|nghin dong|ty dong)\s*\)?$"),

    # People/signature/footer metadata.
    re.compile(r"^(?:nguoi lap|ke toan truong|tong giam doc|giam doc|chu tich)\b"),
    re.compile(r"^(?:ky ten|chu ky|signed|lap ngay|ngay lap)\b"),

    # Table/header vocabulary. These carry column semantics, not business fields.
    re.compile(r"^(?:stt(?:\s*\d+)?|ten chi tieu|chi tiet|gia tri|thoi diem bao cao|cong thuc tinh)$"),
    re.compile(r"^(?:ma so|thuyet minh|chi tieu|so cuoi nam|so dau nam)$"),
    re.compile(r"^(?:so lieu)(?:\s*\(trinh bay lai\))?$"),
    re.compile(r"^so dau nam\s*\(trinh bay lai\)$"),
    re.compile(r"^so lieu theo thuyet minh$"),

    # Pure dates / period headers, optionally with units or audit/restatement notes.
    re.compile(r"^\(?\s*(?:tai|vao|ngay|tai ngay)?\s*\d{1,2}[./-]\d{1,2}[./-]\d{4}(?:\s+trieu\s+(?:vnd|dong))?(?:\s*\([^)]*\))?\s*\)?$"),
    re.compile(r"^(?:tai|vao|ngay|tai ngay)?\s*ngay?\s*\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+\d{4}(?:\s*\([^)]*\))?$"),
    re.compile(r"^(?:tai|vao|ngay|tai ngay)\s+\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+\d{4}(?:\s*\([^)]*\))?$"),
    re.compile(r"^cho nam tai chinh ket thuc ngay\b"),
    re.compile(r"^\d{2}\s*[-/]\s*\d{4}$"),

    # Form identifiers / statement continuation headings.
    re.compile(r"^mau(?:\s+so)?\s+b\s*0?[1-4]\b"),
    re.compile(r"^(?:bang can doi ke toan|bao cao tinh hinh tai chinh).*\(tiep theo\)$"),

    # Legal circular text / boilerplate.
    re.compile(r"^\(?(?:ban hanh theo\s+)?thong tu\b"),
    re.compile(r"^\(ban hanh theo thong tu\b"),
    re.compile(r"^ban hanh theo$"),
    re.compile(r"^ngay\s+\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+\d{4}\s+cua\s+(?:bo tai chinh|nhnn)\b"),

    # Addresses / obvious location metadata seen in OCR/LLM front matter.
    re.compile(r"^dia chi$"),
    re.compile(r"^stt\s+chi tieu$"),
    re.compile(r"^(?:bao cao tinh hinh tai chinh|bang can doi ke toan)(?: hop nhat)?(?: tai)? ngay\b"),
    re.compile(r"^ngay\s+\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+\d{4}\s+cua\s+ngan hang nha nuoc\b"),
    re.compile(r"^(?:so\s+\d+|tang\s+\d+|mac dinh chi,|ly thuong kiet,|tran quang khai,|hau giang,|dai lo hung vuong,).*?(?:phuong|p\.|quan|ha noi|ho chi minh|thanh pho|tower|toa nha|nghia lo)"),

    # Numeric/note tokens and boilerplate notes.
    re.compile(r"^\d+(?:[.,]\d+)*(?:\([a-z]\))?$"),
    re.compile(r"^\d+\([a-z]\)$"),
    re.compile(r"^\(tham chieu\s+\d+\)$"),
    re.compile(r"^cac thuyet minh .*phan (?:cau|hop) thanh bao cao tai chinh"),
    re.compile(r"^cac thuyet minh .*khong the tach roi"),
]


SECTOR_SCHEMA_TOKENS = {
    "off_balance": (
        "bao lanh vay von", "bao lanh khac", "cam ket giao dich hoi doai",
        "cam ket mua ngoai te", "cam ket ban ngoai te", "cam ket giao dich hoan doi",
        "cam ket trong nghiep vu thu tin dung", "cam ket trong nghiep vu l/c",
        "cam ket khac", "cac cam ket khac",
        "no kho doi da xu ly", "lai cho vay va phi phai thu chua thu duoc",
        "lai cho vay va chi phi chua thu duoc", "tai san va chung tu khac",
    ),
    "securities": (
        "fvtpl", "afs", "htm", "b01-ctck", "b01 ctck",
        "tai san tai chinh fvtpl", "tai san tai chinh afs", "tai san tai chinh htm",
        "hoat dong moi gioi", "giao dich ky quy",
        "ung truoc tien ban", "phai tra nha dau tu",
    ),
}


def _looks_like_inline_serialized_row(f: str) -> bool:
    """Detect labels that still contain code/value columns.

    These are structural-serialization gaps (for example column-major/plain-row
    text), not alias gaps. Recommending aliases for the whole serialized row
    would overfit values and form codes.
    """
    # Require a business-looking textual prefix plus at least two numeric cells.
    nums = re.findall(r"(?<!\w)\(?\d[\d.,]{2,}\)?(?!\w)", f)
    if len(nums) < 2:
        return False
    words = re.findall(r"[a-z]{3,}", f)
    return len(words) >= 2


def classify_unknown_financial_label(label: str, detected_sector: str | None = None) -> str:
    f = _clean_financial_label(label)
    if not f:
        return "noise"
    if any(rx.search(f) for rx in NOISE_LABEL_PATTERNS):
        return "noise"
    for sector, tokens in SECTOR_SCHEMA_TOKENS.items():
        if any(tok in f for tok in tokens):
            return f"likely_schema_gap:{sector}"
    if detected_sector == "securities":
        return "likely_schema_gap:securities"
    if detected_sector == "insurance":
        return "likely_schema_gap:insurance"
    if _looks_like_inline_serialized_row(f):
        return "likely_structural_gap"
    if f in {"tong", "tong cong", "cong", "khac", "cac khoan khac", "trong do", "von", "nam nay"}:
        return "review_generic_label"
    return "likely_alias_or_schema_gap"


def analyze_semantic_coverage(nodes, anchor_selection, semantic_anchor_indices, detected_sector: str | None = None) -> dict:
    candidates = []
    unknown = []
    ambiguous = []

    excluded_patterns = {
        "SP_PERIOD_VALUE_ATTRIBUTE",
        "SP_NAMED_ATTRIBUTE",
        "SP_VALUE_ONLY_POSITIONAL",
        "SP_PERIOD_CONTAINER",
        "SP_CONTEXT_CARRIER",
        "SP_PERIOD_VALUE_ATTRIBUTE",
    }
    excluded_labels = {
        "so cuoi nam", "so dau nam", "nam hien tai", "nam truoc",
        "thuyet minh", "ma so", "chi tieu", "ngay bao cao",
    }

    for node in nodes:
        if not node.label_text or node.pattern_id in excluded_patterns:
            continue
        f = fold(node.label_text).strip()
        if f in excluded_labels or f.startswith("tai ngay "):
            continue
        # Count business-row labels only. They must own a payload directly or
        # through immediate structural children; period/note attributes are
        # explicitly excluded above.
        if not _node_has_local_payload(node, nodes):
            continue
        candidates.append(node)
        selection = anchor_selection.get(node.node_index)
        if not selection or not selection.get("candidates"):
            classification = classify_unknown_financial_label(node.label_text, detected_sector)
            unknown.append({
                "line_no": node.line_no,
                "label": node.label_text,
                "normalized_label": _clean_financial_label(node.label_text),
                "pattern_id": node.pattern_id,
                "classification": classification,
            })
        elif selection.get("selected") is None:
            ambiguous.append({
                "line_no": node.line_no,
                "label": node.label_text,
                "reason": selection.get("reason"),
                "pattern_id": node.pattern_id,
            })

    matched = len([n for n in candidates if n.node_index in semantic_anchor_indices])
    total = len(candidates)

    class_counts = {}
    normalized_counts = {}
    for item in unknown:
        cls = item.get("classification") or "unclassified"
        class_counts[cls] = class_counts.get(cls, 0) + 1
        norm = item.get("normalized_label") or ""
        if norm:
            normalized_counts[norm] = normalized_counts.get(norm, 0) + 1

    top_unknown = [
        {"normalized_label": label, "count": count}
        for label, count in sorted(normalized_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:30]
    ]

    # v0.4.12.2: keep legacy actionable fields, but define a stricter
    # true-actionable metric after removing noise, generic labels and known
    # schema gaps. Schema gaps remain visible as their own counts; they should
    # not be treated as alias/parser work.
    actionable_unknown = [
        item for item in unknown
        if item.get("classification") not in {"noise", "review_generic_label"}
    ]
    actionable_total = matched + len(actionable_unknown) + len(ambiguous)
    actionable_coverage = (
        round(matched / actionable_total, 6) if actionable_total else None
    )

    semantic_classes = {"likely_alias_or_schema_gap", "likely_structural_gap"}
    true_actionable_unknown = list(actionable_unknown)
    true_actionable_total = matched + len(true_actionable_unknown) + len(ambiguous)
    true_actionable_coverage = (
        round(matched / true_actionable_total, 6) if true_actionable_total else None
    )

    return {
        "financial_label_candidates": total,
        "matched_financial_labels": matched,
        "unknown_financial_labels": len(unknown),
        "raw_unknown_financial_labels": len(unknown),
        "noise_unknown_financial_labels": class_counts.get("noise", 0),
        "off_balance_unknown_financial_labels": class_counts.get("likely_schema_gap:off_balance", 0),
        "sector_schema_unknown_financial_labels": class_counts.get("likely_schema_gap:securities", 0),
        "semantic_unknown_financial_labels": sum(class_counts.get(x, 0) for x in semantic_classes),
        "generic_review_financial_labels": class_counts.get("review_generic_label", 0),
        "structural_gap_financial_labels": class_counts.get("likely_structural_gap", 0),
        "actionable_unknown_financial_labels": len(actionable_unknown),
        "actionable_financial_label_candidates": actionable_total,
        "true_actionable_unknown_financial_labels": len(true_actionable_unknown),
        "true_actionable_financial_label_candidates": true_actionable_total,
        "ambiguous_financial_labels": len(ambiguous),
        "semantic_label_coverage": round(matched / total, 6) if total else None,
        "actionable_semantic_label_coverage": actionable_coverage,
        "true_actionable_semantic_label_coverage": true_actionable_coverage,
        "unknown_classification_counts": class_counts,
        "unknown_top_labels": top_unknown,
        "unknown_items": unknown,
        "unknown_examples": unknown[:100],
        "ambiguous_examples": ambiguous[:100],
    }


def detect_explicit_totals(lines: Iterable, scope_start: int, scope_end: int, guide) -> dict:
    """Find explicit statement totals with nearby current/previous payload.

    We use a small margin around the selected scope so a truncated start/end can
    still be diagnosed instead of silently reporting a healthy canonical.
    """
    from .primitives import extract_periods, extract_values

    lines = list(lines)
    by_no = {x.line_no: x for x in lines}
    result = {k: [] for k in TOTAL_LABELS}
    lo = max(1, scope_start - 180)
    hi = scope_end + 40

    for line in lines:
        if not (lo <= line.line_no <= hi):
            continue
        label = _clean_financial_label(line.clean)
        matched_id = None
        for node_id, aliases in TOTAL_LABELS.items():
            if label in aliases:
                matched_id = node_id
                break
        if not matched_id:
            continue

        payload = []
        for ln in range(line.line_no, min(hi, line.line_no + 6) + 1):
            x = by_no.get(ln)
            if not x:
                continue
            vals = extract_values(x.clean or "", x.line_no, guide, mask_periods=True)
            periods = extract_periods(x.clean or "", x.line_no, guide)
            if vals:
                payload.extend({
                    "line_no": x.line_no,
                    "raw_value": v.raw_value,
                    "periods": [p.raw_period for p in periods],
                } for v in vals[:2])
        if payload:
            result[matched_id].append({
                "line_no": line.line_no,
                "label": line.clean,
                "payload": payload[:6],
                "inside_selected_scope": scope_start <= line.line_no <= scope_end,
            })
    return result


def canonical_completeness(canonical: dict, explicit_totals: dict) -> dict:
    nm = {n["node_id"]: n for n in canonical.get("nodes", [])}
    missed = []
    absent_in_source = []
    for node_id in TOTAL_LABELS:
        value = (nm.get(node_id) or {}).get("value") or {}
        has_value = value.get("current") is not None or value.get("previous") is not None
        source_occ = explicit_totals.get(node_id) or []
        if source_occ and not has_value:
            missed.append({"node_id": node_id, "source_occurrences": source_occ})
        elif not source_occ and not has_value:
            absent_in_source.append(node_id)
    return {
        "explicit_total_missed": len(missed),
        "explicit_total_missed_details": missed,
        "missing_but_not_explicit_in_source": absent_in_source,
    }
