from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .source_recovery import RecoveredRow

try:
    from .source_recovery import clean, fold, parse_number
    from .structural_identity import occurrence_rank, structural_identity
    from .report_period import resolve_report_years
except ImportError:
    from source_recovery import clean, fold, parse_number
    from structural_identity import occurrence_rank, structural_identity
    from report_period import resolve_report_years


def _normalized_value_key(value: Any):
    """Trả về khóa độc lập với dạng biểu diễn cho một giá trị nguồn."""

    if value is None:
        return None
    parsed = parse_number(value)
    if parsed is not None:
        try:
            return ("number", Decimal(str(parsed)))
        except (InvalidOperation, ValueError):
            return ("number", str(parsed))
    return ("text", clean(value).casefold())


def _values_equal(left: Any, right: Any) -> bool:
    """So sánh giá trị nguồn sau khi chuẩn hóa số."""

    return _normalized_value_key(left) == _normalized_value_key(right)


def _context_label_key(value: Any) -> str:
    """Chuẩn hóa nhãn hierarchy để match nguồn một cách thận trọng.

    Khôi phục nguồn thường thêm số mẫu trước nhãn thật (``IV. Hàng tồn kho`` /
    ``1. Hàng tồn kho``) hoặc thêm viết tắt. Các phần đó là nhiễu cấu trúc trong
    phép so sánh này; nhãn semantic và giá trị vẫn là nguồn chính.
    """

    text = fold(value)
    text = re.sub(r"^\s*(?:\(?\d+(?:\.\d+)*\)?|[ivxlcdm]+|[a-z])\s*[.)-]?\s+", "", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    return " ".join(text.split())


def _source_id(
    statement: str,
    label: str,
    code: str,
    line: Optional[int],
    hierarchy_path: str = "",
    *,
    section: str = "",
    occurrence: int | None = None,
) -> str:
    # ``code`` và dòng nguồn là provenance, không phải semantic identity.
    # Context cấu trúc cùng occurrence rank giữ các nhãn lặp tách biệt mà không
    # biến cột mã tách rời thành nguồn quyết định.
    key = "|".join(structural_identity(
        statement=statement,
        label=label,
        section=section,
        hierarchy_path=hierarchy_path,
        occurrence_rank=occurrence,
    ))
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
    return f"SOURCE.{statement}.{h}"


def extract_code_period_table(text: str, start_line: int, end_line: int, current_year: int | None = None, previous_year: int | None = None):
    """Trích xuất evidence kỳ từ bảng pipe không có nhãn.

    Mã thô chỉ được giữ làm provenance. Không được dùng hàm này để định danh
    hoặc hydrate node semantic bằng mã.
    """
    if current_year is None or previous_year is None:
        period = resolve_report_years(
            text,
            source_name="input",
            current_year=current_year,
            previous_year=previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
    lines = text.splitlines()
    s, e = max(0, start_line - 1), min(len(lines), end_line)
    out = []
    for idx, raw in enumerate(lines[s:e]):
        if raw.count("|") < 3:
            continue
        cells = [clean(x) for x in raw.strip().strip("|").split("|")]
        if not cells or any(fold(c) in {"ma so", "chi tieu"} for c in cells):
            continue
        code = next((c for c in cells[:2] if re.fullmatch(r"\d{2,4}(?:\.\d+)?", c)), None)
        if not code:
            continue
        # Hai ô cuối là cột hiện tại/trước đây. Giữ vị trí: dấu gạch theo mẫu
        # nghĩa là kỳ thực sự không có giá trị và không được đẩy giá trị kia
        # sang sai kỳ.
        current = parse_number(cells[-2])
        previous = parse_number(cells[-1])
        if current is None and previous is None:
            continue
        out.append({
            "code": code,
            "statement_code": code,
            "current": current,
            "previous": previous,
            "source_line": s + idx + 1,
            "pattern": "PERIOD_PIPE_EVIDENCE_ONLY",
            "raw_text": raw.strip(),
        })
    return out


def _form_code_key(value: Any) -> str | None:
    """Chuẩn hóa mã biểu mẫu để tra cứu profile có guard."""

    text = clean(value)
    if not text:
        return None
    match = re.fullmatch(r"0*(\d+)", text)
    if match:
        return str(int(match.group(1)))
    return text.casefold()


def hydrate_canonical_by_form_code(canonical: dict | None, evidence: list[dict], sector: str, method: str):
    if not canonical:
        return canonical

    # Bảng chỉ có mã không được tự định nghĩa semantic identity nói chung:
    # profile ngân hàng có thể dùng lại mã giữa section kinh doanh/đầu tư/tài
    # chính. Tuy nhiên, có thể hydrate khi profile sector+method đã chọn chỉ có
    # đúng một node schema cho mã đó. Đây là bố cục B03 bị làm phẳng thường gặp,
    # trong đó nhãn người đọc nằm ở block bullet còn hai giá trị kỳ nằm sau trong
    # bảng tách rời `Mã số | ... | hiện tại | trước đây`.
    by_code: dict[str, list[dict]] = {}
    for node in canonical.get("nodes") or []:
        if node.get("kind") == "source_observation":
            continue
        node_sector = node.get("sector")
        if node_sector and sector and node_sector != sector:
            continue
        node_method = node.get("method")
        if node_method and method and node_method not in {"any", method}:
            continue
        code_key = _form_code_key(node.get("form_code") or node.get("statement_code"))
        if code_key:
            by_code.setdefault(code_key, []).append(node)

    filled_nodes = 0
    filled_periods = 0
    filled_node_ids: set[str] = set()
    equivalent_matches = 0
    conflicts: list[dict[str, Any]] = []
    ambiguous_codes: set[str] = set()
    unmatched_codes: set[str] = set()
    period_evidence = []

    for raw in evidence or []:
        if not isinstance(raw, dict):
            continue
        code = raw.get("statement_code") or raw.get("code")
        code_key = _form_code_key(code)
        if not code_key:
            continue
        period_evidence.append(raw)
        candidates = by_code.get(code_key, [])
        if not candidates:
            unmatched_codes.add(code_key)
            continue
        if len(candidates) != 1:
            ambiguous_codes.add(code_key)
            continue

        node = candidates[0]
        value = node.setdefault("value", {})
        incoming = {
            "current": raw.get("current"),
            "previous": raw.get("previous"),
        }
        conflict_periods = []
        for period, incoming_value in incoming.items():
            existing_value = value.get(period)
            if incoming_value is None:
                continue
            if existing_value is not None and not _values_equal(existing_value, incoming_value):
                conflict_periods.append(period)

        if conflict_periods:
            conflicts.append({
                "code": str(code),
                "node_id": node.get("node_id"),
                "periods": conflict_periods,
                "existing": {period: value.get(period) for period in conflict_periods},
                "recovered": {period: incoming[period] for period in conflict_periods},
                "source_line": raw.get("source_line"),
            })
            # Không trình bày bằng chứng mã xung đột như provenance semantic.
            # Observation nguồn vẫn được giữ để xem xét.
            continue

        changed = False
        for period, incoming_value in incoming.items():
            if value.get(period) is None and incoming_value is not None:
                value[period] = incoming_value
                filled_periods += 1
                changed = True

        if any(
            incoming[period] is not None
            and value.get(period) is not None
            and _values_equal(value.get(period), incoming[period])
            for period in incoming
        ) and not changed:
            equivalent_matches += 1

        if any(incoming[period] is not None for period in incoming):
            if not any(
                occurrence.get("source_line") == raw.get("source_line")
                and _form_code_key(occurrence.get("code") or occurrence.get("statement_code")) == code_key
                for occurrence in (node.setdefault("extraction_meta", {}).setdefault("occurrences", []))
                if isinstance(occurrence, dict)
            ):
                node["extraction_meta"]["occurrences"].append({
                    "source_line": raw.get("source_line"),
                    "source_label": f"Mã số {code}",
                    "raw_text": raw.get("raw_text"),
                    "pattern": raw.get("pattern"),
                    "current": incoming["current"],
                    "previous": incoming["previous"],
                    "code": str(code),
                    "statement_code": str(code),
                    "mapping_method": "form_code_period_recovery",
                    "mapping_confidence": 0.99,
                })
                if changed:
                    filled_node_ids.add(str(node.get("node_id") or id(node)))

    filled_nodes = len(filled_node_ids)

    canonical.setdefault("diagnostics", {})["form_code_period_recovery"] = {
        "policy": "unique_form_code_period_hydration_v24",
        "sector": sector,
        "method": method,
        "evidence_rows": len(period_evidence),
        "filled_nodes": filled_nodes,
        "filled_periods": filled_periods,
        "equivalent_matches": equivalent_matches,
        "conflicts": len(conflicts),
        "conflict_details": conflicts,
        "ambiguous_codes": sorted(ambiguous_codes),
        "unmatched_codes": sorted(unmatched_codes),
    }
    canonical.setdefault("diagnostics", {}).setdefault("period_evidence", []).extend(period_evidence)
    return canonical


def augment_canonical_with_recovered_rows(canonical: dict | None, rows: list[Any], statement: str) -> dict | None:
    """Thêm dòng nguồn mà không đổi giá trị semantic đã có.

    Dòng chỉ có thể điền kỳ còn thiếu khi nhãn và context cấu trúc xác định đúng
    một node canonical. Dòng mơ hồ vẫn là observation nguồn; mã biểu mẫu và
    tham chiếu thuyết minh không bao giờ trở thành khóa identity.
    """
    if not canonical:
        return canonical
    nodes = canonical.setdefault("nodes", [])
    # Index chỉ bằng nhãn cấu trúc/semantic. Mã và tham chiếu thuyết minh là
    # metadata, cố ý loại khỏi identity và tra cứu candidate.
    by_l: dict[str, list[dict]] = {}
    for n in nodes:
        fl = fold(n.get("canonical_name"))
        if not fl:
            continue
        by_l.setdefault(fl, []).append(n)

    added = filled = conflicts = equivalent_existing = 0
    seen_source = set()
    source_ranks: dict[tuple[str, ...], int] = {}

    def section_matches(node: dict, row: Any) -> bool:
        """Giữ schedule dòng tiền có giới hạn trong domain identity riêng."""
        if statement != "CASHFLOW":
            return True
        row_section = clean(getattr(row, "section", None) or "")
        if not row_section:
            return True
        return clean(node.get("section") or "") == row_section

    def source_identity_matches(node: dict, row: Any) -> bool:
        """Không gộp nhãn chung lặp lại từ các hierarchy khác nhau."""

        if node.get("kind") != "source_observation" or statement != "FINANCIAL_POSITION":
            return True
        node_context = fold(node.get("hierarchy_path") or node.get("parent_label") or "")
        row_context = fold(getattr(row, "hierarchy_path", None) or getattr(row, "parent_label", None) or "")
        return not node_context or not row_context or node_context == row_context

    semantic_nodes = [
        node for node in nodes
        if node.get("kind") != "source_observation"
    ]
    semantic_by_id = {
        str(node.get("node_id")): node
        for node in semantic_nodes
        if node.get("node_id")
    }

    def _node_context_keys(node: dict) -> set[str]:
        """Trả về các nhãn cấu trúc gắn với một node semantic."""

        keys: set[str] = set()
        current = node
        seen: set[str] = set()
        while isinstance(current, dict):
            node_id = str(current.get("node_id") or "")
            if node_id and node_id in seen:
                break
            if node_id:
                seen.add(node_id)
            key = _context_label_key(current.get("canonical_name"))
            if key:
                keys.add(key)
            parent_id = current.get("parent_id")
            current = semantic_by_id.get(str(parent_id)) if parent_id else None

        meta = node.get("extraction_meta") or {}
        for occurrence in meta.get("occurrences") or []:
            if not isinstance(occurrence, dict):
                continue
            source_context = occurrence.get("source_context") or {}
            if not isinstance(source_context, dict):
                continue
            for label in source_context.get("path") or []:
                key = _context_label_key(label)
                if key:
                    keys.add(key)
            for label in (source_context.get("parent_label"), source_context.get("section")):
                key = _context_label_key(label)
                if key:
                    keys.add(key)
        return keys

    def _node_source_labels(node: dict) -> set[str]:
        labels = set()
        key = _context_label_key(node.get("canonical_name"))
        if key:
            labels.add(key)
        meta = node.get("extraction_meta") or {}
        for occurrence in meta.get("occurrences") or []:
            if isinstance(occurrence, dict):
                key = _context_label_key(occurrence.get("source_label"))
                if key:
                    labels.add(key)
        return labels

    def _find_representation_equivalent(row: Any, excluded: set[str]):
        """Tìm node child/chi tiết được biểu diễn bằng nhãn parent khôi phục.

        Một số serializer Markdown làm phẳng dòng ``Cho vay khách hàng`` rồi
        đến chi tiết gross thành hai dòng thô cùng nhãn. Khôi phục nguồn thấy
        dòng chi tiết như nhãn parent nên báo xung đột với dòng net đã parse.
        Chỉ phân loại lại thành tương đương biểu diễn khi *cả hai kỳ* khớp node
        semantic hiện có và hierarchy khôi phục gọi đúng ancestor cấu trúc.
        Trùng giá trị nhưng thiếu context vẫn là xung đột thật.
        """

        parent_key = _context_label_key(getattr(row, "parent_label", None))
        hierarchy_keys = {
            _context_label_key(part)
            for part in re.split(r"\s*>\s*", clean(getattr(row, "hierarchy_path", None) or ""))
            if _context_label_key(part)
        }
        if not parent_key and not hierarchy_keys:
            return None

        row_label_key = _context_label_key(getattr(row, "label", None))
        matches = []
        for node in semantic_nodes:
            node_id = str(node.get("node_id") or "")
            if not node_id or node_id in excluded:
                continue
            value = node.get("value") or {}
            periods = []
            for period, incoming in (("current", row.current), ("previous", row.previous)):
                if incoming is None:
                    continue
                existing = value.get(period)
                if existing is None or not _values_equal(existing, incoming):
                    break
                periods.append(period)
            else:
                if not periods or len(periods) < sum(
                    incoming is not None
                    for incoming in (row.current, row.previous)
                ):
                    continue

                context_keys = _node_context_keys(node)
                context_match = bool(
                    (parent_key and parent_key in context_keys)
                    or hierarchy_keys.intersection(context_keys)
                )
                if not context_match:
                    continue

                source_label_match = row_label_key in _node_source_labels(node)
                score = 2 if source_label_match else 0
                score += 1 if parent_key and parent_key in context_keys else 0
                matches.append((score, node, periods))

        if len(matches) != 1:
            return None
        return matches[0][1], matches[0][2]

    def _record_representation_equivalent(node: dict, row: Any, periods: list[str]):
        meta = node.setdefault("extraction_meta", {})
        occurrence = {
            "source_line": row.source_line,
            "source_label": row.label,
            "pattern": row.pattern,
            "current": row.current,
            "previous": row.previous,
            "code": row.code,
            "statement_code": getattr(row, "statement_code", None),
            "note": row.note,
            "note_ref": getattr(row, "note_ref", None),
            "parent_label": row.parent_label,
            "hierarchy_path": row.hierarchy_path,
            "unit": row.unit,
            "unit_source": row.unit_source,
            "mapping_method": "source_recovery_representation_equivalent",
            "mapping_confidence": 0.99,
            "representation_equivalent": True,
            "matched_periods": periods,
        }
        meta.setdefault("source_recovery_equivalent_occurrences", []).append(occurrence)
        return occurrence

    for r in rows:
        fl = fold(r.label)
        if not fl:
            continue
        candidates = [
            node for node in by_l.get(fl, [])
            if node.get("kind") != "source_observation"
            and section_matches(node, r)
            and source_identity_matches(node, r)
        ]
        # Điền kỳ thiếu khi identity không mơ hồ; không bao giờ thay giá trị
        # semantic non-null đã có.
        if len(candidates) == 1:
            n = candidates[0]
            v = n.setdefault("value", {})
            changed = False
            if v.get("current") is None and r.current is not None:
                v["current"] = r.current
                changed = True
            if v.get("previous") is None and r.previous is not None:
                v["previous"] = r.previous
                changed = True
            stmt_unit = canonical.get("unit")
            eff_u = r.unit or stmt_unit
            if eff_u and (not v.get("unit") or v.get("unit") == "unknown"):
                cname = fold(n.get("canonical_name", ""))
                if "lai co ban" in cname or "lai suy giam" in cname:
                    v["unit"] = "vnd_per_share"
                else:
                    v["unit"] = eff_u
            if changed:
                filled += 1
                em = n.setdefault("extraction_meta", {})
                em.setdefault("source_recovery_occurrences", []).append({
                    "source_line": r.source_line, "source_label": r.label, "pattern": r.pattern,
                    "current": r.current, "previous": r.previous,
                    "code": r.code, "statement_code": getattr(r, "statement_code", None),
                    "note": r.note, "note_ref": getattr(r, "note_ref", None),
                    "parent_label": r.parent_label, "hierarchy_path": r.hierarchy_path,
                    "unit": r.unit, "unit_source": r.unit_source,
                })
                continue
            # Identity chính xác nhưng giá trị khác là evidence debug hữu ích,
            # nhưng tránh tạo nhãn chính xác trùng khiến chọn dòng phía sau không ổn định.
            current_differs = (
                r.current is not None
                and v.get("current") is not None
                and not _values_equal(r.current, v.get("current"))
            )
            previous_differs = (
                r.previous is not None
                and v.get("previous") is not None
                and not _values_equal(r.previous, v.get("previous"))
            )
            if current_differs or previous_differs:
                equivalent = _find_representation_equivalent(
                    r,
                    excluded={str(n.get("node_id") or "")},
                )
                if equivalent:
                    equivalent_node, matched_periods = equivalent
                    _record_representation_equivalent(
                        equivalent_node,
                        r,
                        matched_periods,
                    )
                    equivalent_existing += 1
                    canonical.setdefault("diagnostics", {}).setdefault(
                        "source_recovery_representation_equivalents", []
                    ).append({
                        "label": r.label,
                        "source_line": r.source_line,
                        "target_node_id": equivalent_node.get("node_id"),
                        "matched_periods": matched_periods,
                        "parent_label": r.parent_label,
                        "hierarchy_path": r.hierarchy_path,
                    })
                    continue
                conflicts += 1
                canonical.setdefault("diagnostics", {}).setdefault("source_recovery_conflicts", []).append({
                    "label": r.label, "code": r.code, "source_line": r.source_line,
                    "recovered_current": r.current, "recovered_previous": r.previous,
                    "existing_current": v.get("current"), "existing_previous": v.get("previous"),
                })
            elif (
                (r.current is not None and v.get("current") is not None)
                or (r.previous is not None and v.get("previous") is not None)
            ):
                equivalent_existing += 1
            continue

        parent_label = fold(r.parent_label or "")
        hierarchy_path = fold(r.hierarchy_path or "")
        base_identity = structural_identity(
            statement=statement,
            label=r.label,
            section=r.section or "",
            parent_label=r.parent_label or "",
            hierarchy_path=r.hierarchy_path or "",
        )
        duplicate_key = (base_identity, r.current, r.previous)
        if duplicate_key in seen_source:
            continue
        rank = occurrence_rank(
            source_ranks,
            statement=statement,
            label=r.label,
            section=r.section or "",
            parent_label=r.parent_label or "",
            hierarchy_path=r.hierarchy_path or "",
        )
        key = (structural_identity(
            statement=statement,
            label=r.label,
            section=r.section or "",
            parent_label=r.parent_label or "",
            hierarchy_path=r.hierarchy_path or "",
            occurrence_rank=rank,
        ), r.current, r.previous)
        if key in seen_source:
            continue
        seen_source.add(duplicate_key)
        stmt_u = canonical.get("unit")
        eff_u = r.unit or stmt_u
        cname = fold(r.label)
        if "lai co ban" in cname or "lai suy giam" in cname:
            node_u = "vnd_per_share"
        else:
            node_u = eff_u
        node = {
            "node_id": _source_id(
                statement,
                r.label,
                getattr(r, "statement_code", None) or r.code or "",
                r.source_line,
                r.hierarchy_path or r.parent_label or "",
                section=r.section or "",
                occurrence=rank,
            ),
            "canonical_name": clean(r.label),
            "kind": "source_observation",
            "semantic_role": "recovered_source_row",
            "sector": canonical.get("sector"),
            "method": canonical.get("method"),
            "section": r.section,
            "parent_label": r.parent_label,
            "hierarchy_path": r.hierarchy_path,
            "form_code": getattr(r, "statement_code", None) or r.code or None,
            "statement_code": getattr(r, "statement_code", None) or r.code or None,
            "note_ref": getattr(r, "note_ref", None) or r.note or None,
            "value": {
                "current": r.current, "previous": r.previous,
                "note": getattr(r, "note_ref", None) or r.note,
                "unit": node_u, "raw_text": clean(r.label),
            },
            "extraction_meta": {
                "source_recovery": True,
                "occurrences": [{
                    "source_line": r.source_line, "source_label": clean(r.label), "pattern": r.pattern,
                    "current": r.current, "previous": r.previous,
                    "code": r.code, "statement_code": getattr(r, "statement_code", None),
                    "note": r.note, "note_ref": getattr(r, "note_ref", None),
                    "parent_label": r.parent_label, "hierarchy_path": r.hierarchy_path,
                    "occurrence_rank": rank,
                }],
            },
        }
        nodes.append(node)
        by_l.setdefault(fl, []).append(node)
        added += 1

        # v16.1: nhãn ngắn mơ hồ thường cần hierarchy để khôi phục identity dòng thật.
        # Giữ nguyên dòng nguồn literal và thêm alias evidence theo context; không thay nó.
        if statement == "FINANCIAL_POSITION" and r.parent_label:
            generic = {
                "nguyen gia", "hao mon luy ke", "gia tri hao mon luy ke", "khau hao luy ke",
                "du phong", "gia tri con lai", "tong cong", "cong", "khac"
            }
            if fl in generic:
                if fl in {"tong cong", "cong"}:
                    contextual_label = clean(r.parent_label)
                else:
                    contextual_label = clean(f"{r.label} {r.parent_label}")
                cfl = fold(contextual_label)
                if cfl and cfl != fl and not by_l.get(cfl):
                    ctx = {
                        "node_id": _source_id(
                            statement,
                            contextual_label,
                            getattr(r, "statement_code", None) or r.code or "",
                            r.source_line,
                            (r.hierarchy_path or "") + "|contextual",
                            section=r.section or "",
                            occurrence=rank,
                        ),
                        "canonical_name": contextual_label,
                        "kind": "source_observation",
                        "semantic_role": "contextual_source_identity",
                        "sector": canonical.get("sector"),
                        "method": canonical.get("method"),
                        "section": r.section,
                        "parent_label": r.parent_label,
                        "hierarchy_path": r.hierarchy_path,
                        "form_code": getattr(r, "statement_code", None) or r.code or None,
                        "statement_code": getattr(r, "statement_code", None) or r.code or None,
                        "note_ref": getattr(r, "note_ref", None) or r.note or None,
                        "value": {"current": r.current, "previous": r.previous, "note": getattr(r, "note_ref", None) or r.note, "unit": node_u, "raw_text": clean(r.label)},
                        "extraction_meta": {
                            "source_recovery": True, "contextual_identity": True,
                            "occurrences": [{"source_line": r.source_line, "source_label": clean(r.label), "contextual_label": contextual_label, "pattern": r.pattern}]
                        },
                    }
                    nodes.append(ctx)
                    by_l.setdefault(cfl, []).append(ctx)
                    added += 1

    canonical.setdefault("diagnostics", {})["source_statement_recovery"] = {
        "statement": statement, "rows_recovered": len(rows), "added_nodes": added,
        "filled_existing_nodes": filled, "conflicts": conflicts,
        "representation_equivalent_matches": equivalent_existing,
        "policy": "source_scope_structural_identity_repair_v22_4_1",
    }
    return canonical
