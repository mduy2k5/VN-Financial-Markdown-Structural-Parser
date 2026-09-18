from __future__ import annotations

import collections
import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from .source_recovery import clean, fold, parse_number
except ImportError:
    from source_recovery import clean, fold, parse_number


def _value_key(v: Any):
    parsed = parse_number(v)
    if parsed is not None:
        try:
            normalized = Decimal(str(parsed))
            if normalized == normalized.to_integral_value():
                return int(normalized)
            return round(float(normalized), 8)
        except (InvalidOperation, ValueError):
            return str(parsed)
    return clean(v).casefold() if v is not None else None


def _source_line(node: dict) -> int:
    occ = ((node.get("extraction_meta") or {}).get("occurrences") or [{}])[0]
    return occ.get("source_line") or 10**9


def _group_id(statement: str, section: str, label: str, context: str = "") -> str:
    raw = f"{statement}|{section}|{label}|{context}".encode("utf-8")
    return "SRCGRP." + hashlib.sha1(raw).hexdigest()[:14]


def _period_votes(nodes: list[dict], period: str):
    """Tạo bảng vote theo kỳ từ cả giá trị node và evidence occurrence.

    Giá trị node đóng góp một vote. Giá trị occurrence chỉ đóng góp khi khác
    giá trị cấp node của cùng observation, tránh vô tình tăng trọng số cùng evidence.
    """
    votes = collections.Counter()
    support: dict[Any, list[tuple[int, int]]] = collections.defaultdict(list)
    for n in nodes:
        nv = (n.get("value") or {}).get(period)
        if nv is not None:
            k = _value_key(nv)
            both = int((n.get("value") or {}).get("current") is not None and (n.get("value") or {}).get("previous") is not None)
            votes[k] += 1
            support[k].append((both, _source_line(n)))
        seen_occ_values = set()
        for occ in (n.get("extraction_meta") or {}).get("occurrences") or []:
            ov = occ.get(period)
            if ov is None:
                continue
            k = _value_key(ov)
            if k == _value_key(nv) or k in seen_occ_values:
                continue
            seen_occ_values.add(k)
            both = int(occ.get("current") is not None and occ.get("previous") is not None)
            votes[k] += 1
            support[k].append((both, occ.get("source_line") or _source_line(n)))
    return votes, support


def _resolve_period(nodes: list[dict], period: str):
    """Reconciliation thận trọng.

    - một giá trị khác biệt: nhận;
    - đa số tuyệt đối: nhận giá trị đa số;
    - hòa/xung đột: không tự tạo người thắng.
    """
    votes, support = _period_votes(nodes, period)
    if not votes:
        return None, "missing", {}
    if len(votes) == 1:
        value = next(iter(votes))
        return value, "unanimous", dict(votes)
    ranked = sorted(
        votes,
        key=lambda k: (
            votes[k],
            max((x[0] for x in support[k]), default=0),
            -min((x[1] for x in support[k]), default=10**9),
        ),
        reverse=True,
    )
    top = ranked[0]
    second = ranked[1]
    if votes[top] > votes[second]:
        return top, "majority", dict(votes)
    return None, "conflict", dict(votes)


def _preferred_node(bucket: list[dict], current: Any, previous: Any) -> dict:
    """Chọn observation nguồn ưu tiên để trình bày mà không bỏ phương án khác."""
    def score(n: dict):
        v = n.get("value") or {}
        exact = int((current is None or _value_key(v.get("current")) == _value_key(current)) and
                    (previous is None or _value_key(v.get("previous")) == _value_key(previous)))
        both = int(v.get("current") is not None and v.get("previous") is not None)
        recovered = int(bool((n.get("extraction_meta") or {}).get("source_recovery")))
        return (exact, both, recovered, -_source_line(n))
    return max(bucket, key=score)


def _semantic_candidates(semantic: list[dict], statement: str, section: str, label: str):
    out = []
    for n in semantic:
        if fold(n.get("canonical_name")) != label:
            continue
        if statement == "CASHFLOW" and clean(n.get("section") or "") != section:
            continue
        out.append(n)
    return out


def _node_occurrences(node: dict) -> list[dict]:
    """Trả về record provenance có thể dùng để liên kết nguồn với semantic."""

    meta = node.get("extraction_meta") or {}
    records = []
    for key in ("occurrences", "source_recovery_occurrences"):
        for occurrence in meta.get(key) or []:
            if isinstance(occurrence, dict):
                records.append(occurrence)
    if not records:
        records.append({
            "source_line": _source_line(node) if _source_line(node) < 10**9 else None,
            "source_label": node.get("canonical_name"),
            "current": (node.get("value") or {}).get("current"),
            "previous": (node.get("value") or {}).get("previous"),
        })
    return records


def _record_value(node: dict, occurrence: dict, period: str):
    value = occurrence.get(period)
    if value is not None:
        return value
    return (node.get("value") or {}).get(period)


def _record_label(node: dict, occurrence: dict) -> str:
    return fold(occurrence.get("source_label") or occurrence.get("label") or node.get("canonical_name"))


def _period_values_match(source_node: dict, source_occurrence: dict, semantic_node: dict, semantic_occurrence: dict) -> bool:
    """So sánh giá trị evidence mà không xem mã nguồn là identity."""

    compared = False
    for period in ("current", "previous"):
        source_value = _record_value(source_node, source_occurrence, period)
        semantic_value = _record_value(semantic_node, semantic_occurrence, period)
        if source_value is None or semantic_value is None:
            continue
        compared = True
        if _value_key(source_value) != _value_key(semantic_value):
            return False
    return compared


def _context_matches(source_node: dict, semantic_node: dict, statement: str) -> bool:
    if statement == "CASHFLOW":
        source_section = clean(source_node.get("section") or "")
        semantic_section = clean(semantic_node.get("section") or "")
        if source_section and semantic_section and source_section != semantic_section:
            return False
    if statement == "FINANCIAL_POSITION":
        source_context = fold(source_node.get("hierarchy_path") or source_node.get("parent_label") or "")
        semantic_context = fold(semantic_node.get("hierarchy_path") or semantic_node.get("parent_label") or "")
        if source_context and semantic_context and source_context != semantic_context:
            return False
    return True


def _link_source_observations(semantic: list[dict], source: list[dict], statement: str) -> dict:
    """Liên kết evidence nguồn được giữ với node semantic khi không mơ hồ.

    Đây là bước reconciliation provenance, không phải quy tắc identity mới. Nó
    dùng dòng nguồn đã trích xuất, nhãn nguồn chuẩn hóa, giá trị kỳ và context
    cấu trúc. Mã biểu mẫu cố ý vắng mặt trong mọi khóa tra cứu.
    """

    by_line: dict[str, list[tuple[dict, dict]]] = collections.defaultdict(list)
    by_label_values: dict[tuple[str, Any, Any], list[tuple[dict, dict]]] = collections.defaultdict(list)
    for semantic_node in semantic:
        seen_records = set()
        for occurrence in _node_occurrences(semantic_node):
            record_key = (
                occurrence.get("source_line"),
                _record_label(semantic_node, occurrence),
                _value_key(_record_value(semantic_node, occurrence, "current")),
                _value_key(_record_value(semantic_node, occurrence, "previous")),
            )
            if record_key in seen_records:
                continue
            seen_records.add(record_key)
            line = occurrence.get("source_line")
            if line is not None:
                by_line[str(line)].append((semantic_node, occurrence))
            by_label_values[
                (
                    _record_label(semantic_node, occurrence),
                    _value_key(_record_value(semantic_node, occurrence, "current")),
                    _value_key(_record_value(semantic_node, occurrence, "previous")),
                )
            ].append((semantic_node, occurrence))

    linked = 0
    source_only = 0
    ambiguous = 0
    for source_node in source:
        candidates: list[tuple[dict, dict, str, float]] = []
        for source_occurrence in _node_occurrences(source_node):
            line = source_occurrence.get("source_line")
            if line is not None:
                for semantic_node, semantic_occurrence in by_line.get(str(line), []):
                    if not _context_matches(source_node, semantic_node, statement):
                        continue
                    if not _period_values_match(source_node, source_occurrence, semantic_node, semantic_occurrence):
                        continue
                    candidates.append((semantic_node, semantic_occurrence, "source_line_and_values", 1.0))

            label_key = (
                _record_label(source_node, source_occurrence),
                _value_key(_record_value(source_node, source_occurrence, "current")),
                _value_key(_record_value(source_node, source_occurrence, "previous")),
            )
            for semantic_node, semantic_occurrence in by_label_values.get(label_key, []):
                if _context_matches(source_node, semantic_node, statement):
                    candidates.append((semantic_node, semantic_occurrence, "normalized_label_and_values", 0.98))

        unique: dict[str, tuple[dict, dict, str, float]] = {}
        for candidate in candidates:
            semantic_node = candidate[0]
            key = str(semantic_node.get("node_id") or id(semantic_node))
            previous = unique.get(key)
            if previous is None or candidate[3] > previous[3]:
                unique[key] = candidate

        meta = source_node.setdefault("extraction_meta", {})
        if len(unique) == 1:
            semantic_node, semantic_occurrence, method, confidence = next(iter(unique.values()))
            mapped_node_id = semantic_node.get("node_id")
            meta["mapping_status"] = "mapped"
            meta["mapping_method"] = "source_evidence_link"
            meta["mapping_confidence"] = confidence
            meta["mapped_node_id"] = mapped_node_id
            meta["source_semantic_link"] = {
                "mapped_node_id": mapped_node_id,
                "relation": "source_evidence_for",
                "method": method,
                "confidence": confidence,
            }
            source_node["mapping"] = {
                "status": "mapped",
                "mapped_node_id": mapped_node_id,
                "method": "source_evidence_link",
                "confidence": confidence,
            }
            linked += 1
        else:
            if len(unique) > 1:
                ambiguous += 1
                meta["mapping_status"] = "ambiguous"
                meta["mapping_method"] = "source_evidence_conflict"
                meta["source_only_reason"] = "multiple_semantic_evidence_links"
            else:
                meta.setdefault("mapping_status", "source_only")
                meta.setdefault("mapping_method", "source_preservation")
                meta.setdefault("source_only_reason", "no_unique_semantic_evidence_link")
            source_node["mapping"] = {
                "status": meta["mapping_status"],
                "method": meta["mapping_method"],
            }
            if meta.get("source_only_reason"):
                source_node["mapping"]["reason"] = meta["source_only_reason"]
            source_only += 1

    return {
        "policy": "source_evidence_link_v1",
        "source_nodes": len(source),
        "linked_source_nodes": linked,
        "source_only_nodes": source_only,
        "ambiguous_source_nodes": ambiguous,
    }


def reconcile_source_observations(canonical: dict | None, statement: str) -> dict | None:
    """Reconciliation nguồn v16 theo identity cấu trúc, không phá hủy.

    Observation nguồn được giữ nguyên. Nhóm trùng của báo cáo tình hình tài chính
    dùng thêm context hierarchy để không gộp nhãn chung lặp dưới parent khác.
    Reconciliation là một view song song:

    * mọi observation gốc vẫn có thể truy cập;
    * nhóm trùng được annotate, không xóa;
    * một observation được đánh dấu ưu tiên và đặt trước phương án khác;
    * giá trị kỳ của observation nguồn gốc không bao giờ bị tạo/chỉnh tổng hợp;
    * node semantic chỉ hydrate khi identity duy nhất và kỳ đang null;
    * evidence xung đột được giữ nguyên để debug.
    """
    if not canonical:
        return canonical

    nodes = canonical.get("nodes") or []
    semantic = [n for n in nodes if n.get("kind") != "source_observation"]
    src = [n for n in nodes if n.get("kind") == "source_observation"]
    source_mapping = _link_source_observations(semantic, src, statement)

    # Identity của family cố ý bỏ qua mã biểu mẫu: mã chỉ là evidence hỗ trợ và
    # trang tiếp nối thường bỏ mã. Section dòng tiền vẫn thuộc identity vì nhãn/mã có thể lặp.
    groups: dict[tuple[str, str, str], list[dict]] = collections.defaultdict(list)
    ungrouped = []
    for n in src:
        label = fold(n.get("canonical_name"))
        section = clean(n.get("section") or "") if statement == "CASHFLOW" else ""
        # Nhãn báo cáo tình hình tài chính như "Nguyên giá" hoặc "Dự phòng" có
        # thể lặp hợp lệ dưới parent khác. Giữ identity nguồn thay vì chỉ gộp theo nhãn.
        context = fold(n.get("hierarchy_path") or n.get("parent_label") or "") if statement == "FINANCIAL_POSITION" else ""
        if not label:
            ungrouped.append(n)
            continue
        groups[(section, label, context)].append(n)

    ordered_src: list[dict] = []
    view = []
    duplicate_groups = 0
    conflicts = 0
    semantic_fills = 0
    preferred_completed = 0

    for (section, label, context), bucket in sorted(groups.items(), key=lambda kv: min(_source_line(n) for n in kv[1])):
        gid = _group_id(statement, section, label, context)
        if len(bucket) > 1:
            duplicate_groups += 1

        cur, cur_state, cur_votes = _resolve_period(bucket, "current")
        prev, prev_state, prev_votes = _resolve_period(bucket, "previous")
        if cur_state == "conflict" or prev_state == "conflict":
            conflicts += 1

        preferred = _preferred_node(bucket, cur, prev)
        # v16 giữ observation nguồn theo đúng nghĩa dữ liệu gốc: reconciliation
        # chỉ là view song song. Không bao giờ tự tạo kỳ trong observation nguồn.

        member_ids = []
        for rank, n in enumerate(sorted(bucket, key=_source_line), start=1):
            em = n.setdefault("extraction_meta", {})
            em["duplicate_group_id"] = gid
            em["duplicate_group_size"] = len(bucket)
            em["preferred_observation"] = (n is preferred)
            em["reconciliation_rank"] = 0 if n is preferred else rank
            em["reconciliation_policy"] = "structural_identity_non_destructive_v16"
            member_ids.append(n.get("node_id"))

        # Chỉ điền node semantic khi identity chuẩn hóa chính xác là duy nhất và kỳ semantic đang null.
        sem = _semantic_candidates(semantic, statement, section, label)
        if len(sem) == 1:
            sv = sem[0].setdefault("value", {})
            changed = False
            if sv.get("current") is None and cur is not None:
                sv["current"] = cur
                changed = True
            if sv.get("previous") is None and prev is not None:
                sv["previous"] = prev
                changed = True
            if changed:
                semantic_fills += 1
                sem[0].setdefault("extraction_meta", {}).setdefault("source_reconciliation_fills", []).append({
                    "group_id": gid,
                    "current": cur,
                    "previous": prev,
                    "policy": "fill_missing_only_v16",
                })

        # Đặt phương án ưu tiên trước, nhưng vẫn giữ mọi phương án khác trong node
        # để recall/evidence debug.
        ordered_src.append(preferred)
        ordered_src.extend(n for n in sorted(bucket, key=_source_line) if n is not preferred)
        view.append({
            "group_id": gid,
            "statement": statement,
            "section": section or None,
            "normalized_label": label,
            "identity_context": context or None,
            "display_label": preferred.get("canonical_name"),
            "preferred_node_id": preferred.get("node_id"),
            "member_node_ids": member_ids,
            "member_count": len(bucket),
            "current": cur,
            "previous": prev,
            "current_state": cur_state,
            "previous_state": prev_state,
            "current_votes": cur_votes,
            "previous_votes": prev_votes,
            "conflict": cur_state == "conflict" or prev_state == "conflict",
        })

    ordered_src.extend(ungrouped)
    canonical["nodes"] = semantic + ordered_src
    canonical["reconciled_source_view"] = view
    canonical.setdefault("diagnostics", {})["source_observation_reconciliation"] = {
        "statement": statement,
        "policy": "structural_identity_non_destructive_v16",
        "input_source_nodes": len(src),
        "output_source_nodes": len(ordered_src),
        "duplicate_groups": duplicate_groups,
        "removed_duplicate_nodes": 0,
        "conflicting_groups": conflicts,
        "preferred_completed_nodes": 0,
        "semantic_nodes_filled": semantic_fills,
        "preserves_all_source_observations": True,
        "source_mapping": source_mapping,
    }
    canonical.setdefault("diagnostics", {})["source_observation_mapping"] = source_mapping
    return canonical
