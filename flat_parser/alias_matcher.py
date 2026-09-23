from __future__ import annotations

from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
import re

from .document import ancestors
from .models import AliasCandidate, StructuralNode
from .semantic_catalog import SemanticCatalog
from .textnorm import fold, strip_numbering


def normalize_label(text: str) -> str:
    text = strip_numbering(text or "")
    text = text.strip(" |;:-")
    return fold(text)


def _is_period_wrapper_label(text: str) -> bool:
    """Return whether a source-path label is a reporting-period wrapper.

    Period-major Markdown commonly serializes the same semantic child once
    under each period wrapper.  That repeated label is not evidence that the
    second occurrence is a ``same_label_as_parent`` child.  We keep this
    helper local to alias selection so real nested same-label trees still use
    the stronger path evidence below.
    """

    normalized = normalize_label(text)
    if not normalized or not re.search(r"\b20\d{2}\b", normalized):
        return False
    return bool(
        re.search(r"\b(?:0?1|3?1)[./-]0?1[./-]20\d{2}\b", normalized)
        or re.search(r"\b31[./-]12[./-]20\d{2}\b", normalized)
        or "nam" in normalized
    )


def _base_match(text: str, spec, allow_fuzzy: bool):
    c = normalize_label(text)
    if not c:
        return None

    for bad in spec.exclude_if_contains:
        bad_n = normalize_label(bad)
        if bad_n and bad_n in c:
            return None

    if c == normalize_label(spec.canonical_name):
        return 1.00, spec.canonical_name, "exact_canonical"

    for x in spec.exact:
        if c == normalize_label(x):
            return 0.99, x, "exact"

    for x in spec.aliases:
        if c == normalize_label(x):
            return 0.97, x, "alias"

    for x in spec.contains:
        xn = normalize_label(x)
        if xn and xn in c:
            return 0.88, x, "contains"

    if allow_fuzzy:
        best = None
        for x in [spec.canonical_name] + spec.exact + spec.aliases:
            xn = normalize_label(x)
            if min(len(c), len(xn)) < 8:
                continue
            ratio = SequenceMatcher(None, c, xn).ratio()
            if ratio >= 0.93:
                score = 0.82 + 0.08 * ratio
                if not best or score > best[0]:
                    best = (score, x, "fuzzy")
        return best

    return None


def _has_value_descendant(node: StructuralNode, nodes: list[StructuralNode]) -> bool:
    pending = list(node.children)
    while pending:
        child_index = pending.pop()
        child = nodes[child_index]
        if child.values:
            return True
        pending.extend(child.children)
    return False


def _subtotal_owner_for_node(
    node: StructuralNode,
    nodes: list[StructuralNode],
    catalog: SemanticCatalog,
):
    """Find a schema group whose value is exactly the sum of its source children.

    Some flattened statements label a subtotal with the same text as its first
    detail row. Only reassign that subtotal to the schema parent when the group
    explicitly opts in, all value-bearing direct children resolve to distinct
    schema children, their period columns match, and every column sums exactly.
    """

    if not node.values or not node.children:
        return None

    source_label = normalize_label(node.label_text or node.text)
    if not source_label:
        return None

    for owner in catalog.nodes.values():
        if not (owner.structural or {}).get("subtotal_owner_reassignment"):
            continue

        child_specs = [
            spec for spec in catalog.nodes.values()
            if spec.parent_id == owner.node_id and spec.kind != "group"
        ]
        if len(child_specs) < 2:
            continue

        payload_children = []
        mapped_child_ids = set()
        has_repeated_child_label = False
        invalid = False
        for child_index in node.children:
            child = nodes[child_index]
            if not child.values:
                if _has_value_descendant(child, nodes):
                    invalid = True
                    break
                continue
            if _has_value_descendant(child, nodes):
                invalid = True
                break

            child_label = normalize_label(child.label_text or child.text)
            matches = [
                spec for spec in child_specs
                if _base_match(child_label, spec, allow_fuzzy=False)
            ]
            if len(matches) != 1 or matches[0].node_id in mapped_child_ids:
                invalid = True
                break
            mapped_child_ids.add(matches[0].node_id)
            payload_children.append(child)
            if child_label == source_label:
                has_repeated_child_label = True

        if invalid or len(payload_children) < 2 or not has_repeated_child_label:
            continue
        if len(mapped_child_ids) != len(payload_children):
            continue

        parent_periods = tuple(
            normalize_label(period.normalized or period.raw_period)
            for period in node.periods
        )
        if not parent_periods or len(parent_periods) != len(node.values):
            continue

        child_value_columns = []
        for child in payload_children:
            periods = tuple(
                normalize_label(period.normalized or period.raw_period)
                for period in child.periods
            )
            if periods != parent_periods or len(child.values) != len(node.values):
                invalid = True
                break
            child_value_columns.append(child.values)
        if invalid:
            continue

        all_values = [*node.values]
        for values in child_value_columns:
            all_values.extend(values)
        units = {normalize_label(value.unit or "") for value in all_values}
        units.discard("")
        if len(units) > 1:
            continue

        try:
            parent_numbers = [
                Decimal(str(value.normalized_candidate))
                if value.normalized_candidate is not None and not value.is_dash
                else None
                for value in node.values
            ]
            child_numbers = [
                [
                    Decimal(str(value.normalized_candidate))
                    if value.normalized_candidate is not None and not value.is_dash
                    else None
                    for value in values
                ]
                for values in child_value_columns
            ]
        except (InvalidOperation, ValueError):
            continue

        if any(value is None for value in parent_numbers) or any(
            value is None for column in child_numbers for value in column
        ):
            continue
        if all(
            sum(column[period_index] for column in child_numbers)
            == parent_numbers[period_index]
            for period_index in range(len(parent_numbers))
        ):
            return owner

    return None


def _nearest_semantic_ancestor_texts(
    node: StructuralNode,
    nodes: list[StructuralNode],
    prior_selected: list[tuple[int, str, str]],
):
    """
    Trả về bằng chứng ancestor semantic theo thứ tự gần trước.

    Ưu tiên cây thụt lề. Nếu quan hệ ancestor trong cây yếu, dùng các anchor
    canonical đã chọn gần đây làm fallback với trọng số thấp hơn.
    """
    tree = ancestors(nodes, node.node_index)
    tree_texts = [normalize_label(x.label_text or x.text) for x in tree]

    prior = []
    for line_no, node_id, label in reversed(prior_selected[-50:]):
        if node.line_no - line_no > 100:
            break
        prior.append((line_no, node_id, normalize_label(label)))

    return tree_texts, prior


def _source_context_score(spec, catalog: SemanticCatalog, source_context: dict | None):
    """Chấm điểm candidate alias dựa trên bằng chứng hierarchy của nguồn.

    Điểm được giữ thận trọng: chỉ dùng nhãn context chuẩn hóa khớp chính xác.
    Nhờ đó, dòng chung bị tách như ``Nguyên giá`` có thể được giải quyết dưới
    nhóm tài sản cố định trước đó mà không biến một match chuỗi lỏng thành
    định danh semantic.
    """

    if not isinstance(source_context, dict):
        return 0.0, []

    path = [normalize_label(x) for x in source_context.get("path") or []]
    # ``path`` chứa dòng hiện tại ở phần tử cuối. Chỉ ancestor mới là bằng
    # chứng parent hợp lệ.
    ancestor_labels = [x for x in path[:-1] if x]
    parent_label = normalize_label(source_context.get("parent_label") or "")
    semantic_anchor = normalize_label(source_context.get("semantic_anchor") or "")

    candidate_contexts = {
        normalize_label(x)
        for x in (spec.parent_context or [])
        if normalize_label(x)
    }
    parent_chain = []
    current = catalog.nodes.get(spec.parent_id) if spec.parent_id else None
    seen = set()
    while current and current.node_id not in seen:
        seen.add(current.node_id)
        normalized = normalize_label(current.canonical_name)
        if normalized:
            parent_chain.append(normalized)

        # Alias của parent cũng là bằng chứng hierarchy hợp lệ. Nguồn thực tế
        # thường dùng ``Vốn đầu tư...``/``Vốn của tổ chức tín dụng`` cho dòng
        # cha trong khi schema canonical giữ tên chuẩn khác. Nếu chỉ nhìn
        # canonical_name, context đúng sẽ bị bỏ qua.
        for label in [
            current.canonical_name,
            *(current.exact or []),
            *(current.aliases or []),
        ]:
            normalized_alias = normalize_label(label)
            if normalized_alias:
                candidate_contexts.add(normalized_alias)
        current = catalog.nodes.get(current.parent_id) if current.parent_id else None
    candidate_contexts.update(parent_chain)

    # Khi Markdown chèn wrapper kỳ giữa group và dòng con, ``parent_label``
    # có thể là ``31/12/2024`` thay vì tên group. Vẫn phải ưu tiên ancestor
    # semantic trực tiếp của candidate (ví dụ ``Tài sản cố định vô hình``)
    # hơn một candidate chỉ khớp ancestor xa chung như ``Tài sản cố định``.
    direct_parent_contexts = set()
    direct_parent = catalog.nodes.get(spec.parent_id) if spec.parent_id else None
    if direct_parent:
        for label in [
            direct_parent.canonical_name,
            *(direct_parent.exact or []),
            *(direct_parent.aliases or []),
        ]:
            normalized = normalize_label(label)
            if normalized:
                direct_parent_contexts.add(normalized)

    score = 0.0
    evidence = []
    if semantic_anchor and semantic_anchor in candidate_contexts:
        score = max(score, 0.72)
        evidence.append("source_context_semantic_anchor")
    if parent_label and parent_label in candidate_contexts:
        score = max(score, 0.56)
        evidence.append("source_context_parent_label")
    if any(label in direct_parent_contexts for label in ancestor_labels):
        score = max(score, 0.68)
        evidence.append("source_context_direct_semantic_parent")
    if any(label in candidate_contexts for label in ancestor_labels):
        score = max(score, 0.40)
        evidence.append("source_context_ancestor_path")

    maturity = source_context.get("maturity")
    normalized_candidate = normalize_label(
        " ".join([spec.canonical_name] + list(spec.exact or []) + list(spec.aliases or []))
    )
    if maturity == "short_term" and "ngan han" in normalized_candidate:
        score = max(score, 0.28)
        evidence.append("source_context_short_term")
    elif maturity == "long_term" and "dai han" in normalized_candidate:
        score = max(score, 0.28)
        evidence.append("source_context_long_term")

    return score, evidence


def match_candidates(
    node: StructuralNode,
    nodes: list[StructuralNode],
    catalog: SemanticCatalog,
    prior_selected: list[tuple[int, str, str]],
    *,
    allow_fuzzy: bool = False,
    detected_sector: str | None = None,
    source_context: dict | None = None,
    same_label_recovery: bool = True,
):
    text = node.label_text or ""
    if not text:
        return []

    # ``Trong đó: X`` được tách thành lhs=``Trong đó`` và rhs=``X``. Với
    # record cấu trúc, rhs là nhãn tài chính thật, không phải thuộc tính giá trị.
    # Thử rhs như nhãn thay thế nhưng vẫn giữ text nguồn ban đầu cho provenance.
    label_options = [text]
    if (
        fold(node.lhs or "") in {"trong do", "bao gom", "including"}
        and node.rhs
        and not node.values
    ):
        label_options.insert(0, node.rhs.strip())

    candidates = []
    tree_texts, prior = _nearest_semantic_ancestor_texts(
        node, nodes, prior_selected
    )
    subtotal_owner = (
        _subtotal_owner_for_node(node, nodes, catalog)
        if same_label_recovery
        else None
    )

    for spec in catalog.nodes.values():
        structural_subtotal_match = bool(
            subtotal_owner and spec.node_id == subtotal_owner.node_id
        )
        if structural_subtotal_match:
            base = (0.99, text, "structural_subtotal_owner_reassignment")
        elif subtotal_owner and spec.parent_id == subtotal_owner.node_id:
            # The source row is the verified sum of its children; do not
            # assign that aggregate to the child whose label happens to match.
            continue
        else:
            base = None
        matched_source_text = text
        if not structural_subtotal_match:
            for label_option in label_options:
                base = _base_match(label_option, spec, allow_fuzzy)
                if base:
                    matched_source_text = label_option
                    break
        if not base:
            continue

        # v0.4.14: guard theo sector cho các nhãn chung mới được bổ sung.
        # Cách này không làm thay đổi hành vi mapping cũ của catalog còn lại.
        normalized_source = normalize_label(matched_source_text)
        sector_guard = {
            "vay ngan han": "enterprise",
            "vay dai han": "enterprise",
            "cac khoan du phong rui ro cho cac tai san co noi bang khac": "bank",
            "du phong cho tai san co khac": "bank",
            "von cua tctd": "bank",
            "von cua to chuc tin dung": "bank",
            "quy cua to chuc tin dung": "bank",
        }.get(normalized_source)
        if sector_guard and detected_sector and detected_sector != sector_guard:
            # Bản schema 1.11 xác nhận hai nhãn vay ngắn/dài hạn cũng là
            # chỉ tiêu chuẩn ở công ty chứng khoán và bảo hiểm. Chỉ mở rộng
            # đúng hai trường hợp này trong profile mới để schema_v1_11 cũ
            # vẫn là điểm rollback nguyên trạng.
            borrowing_sector_extension = (
                catalog.schema.get("schema_version") == "1.11.0"
                and normalized_source in {"vay ngan han", "vay dai han"}
                and detected_sector in {"securities", "insurance"}
            )
            if not borrowing_sector_extension:
                continue
            # Một số Markdown của CTCK lặp cùng nhãn cho hai mã chỉ tiêu
            # khác nhau (ví dụ 311 và 312 đều thành "Vay ngắn hạn"). Khi hai
            # dòng có cùng cha và đều mang giá trị, không thể gán chắc chắn
            # chúng vào cùng một node canonical; giữ cả hai ở trạng thái chưa
            # map để tránh gộp/mất một bộ giá trị khi consolidate.
            duplicate_value_siblings = any(
                other.node_index != node.node_index
                and other.parent_index == node.parent_index
                and bool(other.values)
                and normalize_label(other.label_text or other.text)
                == normalized_source
                for other in nodes
            )
            if duplicate_value_siblings:
                continue

        alias_score, matched_alias, method = base
        context_score = 0.0
        evidence = []
        if structural_subtotal_match:
            context_score = 0.60
            evidence.append("subtotal_owner_value_sum_matches_children")

        source_score, source_evidence = _source_context_score(
            spec,
            catalog,
            source_context,
        )
        if source_score:
            context_score = max(context_score, source_score)
            evidence.extend(source_evidence)

        parent_context = [normalize_label(x) for x in spec.parent_context if x]
        ancestor_ids = catalog.ancestor_ids(spec.node_id)

        # Ancestor gần nhất trong cây là bằng chứng semantic mạnh nhất.
        for distance, tree_text in enumerate(tree_texts):
            if not tree_text:
                continue

            if tree_text in parent_context:
                boost = 0.58 if distance == 0 else max(0.16, 0.30 - distance * 0.04)
                context_score = max(context_score, boost)
                evidence.append(f"nearest_tree_parent_context:d{distance}")
                break

        # Parent canonical trực tiếp gần đây là bằng chứng mạnh tiếp theo.
        # Tính trọng số theo khoảng cách dòng nguồn, không chỉ theo thứ hạng
        # gần đây: thụt lề Markdown hỏng có thể làm lộ nhiều parent cũ cùng lúc.
        for rank, (line_no, prior_id, prior_label) in enumerate(prior):
            if spec.parent_id and prior_id == spec.parent_id:
                delta = max(0, node.line_no - line_no)
                if delta <= 1:
                    boost = 0.52
                elif delta <= 2:
                    boost = 0.48
                elif delta <= 3:
                    boost = 0.44
                elif delta <= 5:
                    boost = 0.38
                elif delta <= 10:
                    boost = 0.32
                elif delta <= 15:
                    boost = 0.26
                elif delta <= 30:
                    boost = 0.17
                elif delta <= 60:
                    boost = 0.10
                else:
                    boost = 0.05
                context_score = max(context_score, boost)
                evidence.append(f"recent_direct_parent:{prior_id}:d{delta}")
                break

        # Dòng bảng thường bị làm phẳng, nên dòng semantic trước đó có thể là
        # sibling thay vì parent rõ ràng trong cây. Parent canonical chung vẫn
        # là context yếu hữu ích (ví dụ ASSET.OTHER.* so với LIABILITY.*).
        if spec.parent_id:
            for rank, (line_no, prior_id, prior_label) in enumerate(prior[:16]):
                prior_spec = catalog.nodes.get(prior_id)
                if prior_spec and prior_spec.parent_id == spec.parent_id:
                    delta = max(0, node.line_no - line_no)
                    if delta <= 8:
                        boost = 0.24
                    elif delta <= 18:
                        boost = 0.16
                    elif delta <= 35:
                        boost = 0.10
                    else:
                        boost = 0.05
                    context_score = max(context_score, boost)
                    evidence.append(f"recent_sibling_parent:{spec.parent_id}:d{delta}")
                    break

        # Ancestor canonical xa hơn có trọng số yếu hơn.
        for rank, (line_no, prior_id, prior_label) in enumerate(prior):
            if prior_id in ancestor_ids:
                context_score = max(context_score, 0.07)
                evidence.append(f"recent_ancestor:{prior_id}")
                break

        structural = spec.structural or {}
        schema_same_label_overlap = (
            catalog.same_label_parent_overlap(spec.node_id)
            if same_label_recovery
            else set()
        )
        same_label_parent_required = bool(
            same_label_recovery
            and (
                structural.get("same_label_as_parent_required")
                or schema_same_label_overlap
            )
        )
        source_path = [
            normalize_label(x)
            for x in (source_context or {}).get("path") or []
            if normalize_label(x)
        ]
        source_has_same_label_ancestor = normalized_source in source_path[:-1]
        period_wrapper_in_path = any(
            _is_period_wrapper_label(x) for x in source_path[:-1]
        )

        # Nếu nguồn lặp đúng nhãn của dòng cha nhưng schema không có node con
        # tương ứng, không được đẩy dòng con vào lại node group của cha. Giữ
        # dòng đó ở source-observation để báo cáo cấu trúc nguồn, thay vì tạo
        # semantic duplicate giả. Candidate child có cờ
        # same_label_as_parent_required sẽ đi qua nhánh dưới đây.
        if (
            same_label_recovery
            and source_has_same_label_ancestor
            and spec.kind == "group"
            and not same_label_parent_required
        ):
            continue

        if same_label_parent_required:
            # QUAN TRỌNG: không được nhầm các sibling lặp lại theo vị trí thành
            # cặp parent/child. Phải yêu cầu parent gần nhất THỰC TẾ trong cây
            # có cùng nhãn. Điều này giữ được cấu trúc thật như:
            #   Cho vay khách hàng
            #       Cho vay khách hàng -> .GROSS
            # đồng thời giữ hai dòng cùng nhãn liền nhau trong một node để
            # consolidator có thể gộp cột hiện tại/trước đây.
            actual_parent_same_label = bool(
                tree_texts
                and tree_texts[0]
                and tree_texts[0] == normalize_label(text)
            )
            recent_same_label_semantic_parent = any(
                spec.parent_id
                and prior_id == spec.parent_id
                and prior_label == normalize_label(matched_source_text)
                and max(0, node.line_no - line_no) <= 12
                for line_no, prior_id, prior_label in prior
            )
            if actual_parent_same_label:
                context_score += 0.30
                evidence.append("same_label_actual_tree_parent")
            elif source_has_same_label_ancestor:
                # Markdown serializer có thể chèn wrapper kỳ giữa parent và
                # child, nên tree parent trực tiếp không còn là nhãn lặp.
                # Full source_context.path vẫn giữ được bằng chứng này.
                context_score += 0.30
                evidence.append("same_label_source_context_parent")
            elif recent_same_label_semantic_parent and (
                not period_wrapper_in_path or source_has_same_label_ancestor
            ):
                # Bảng theo mẫu bị làm phẳng thường chèn dòng số/mã biểu mẫu
                # giữa parent và child lặp nhãn. Khi đó parent thụt lề thực tế
                # là dòng mã, nên kiểm tra chỉ dùng cây nghiêm ngặt sẽ loại
                # child hợp lệ (ví dụ Hàng tồn kho -> Hàng tồn kho trước dự phòng).
                # Parent semantic gần đây có cùng nhãn là dạng thứ hai an toàn
                # của cùng bằng chứng cấu trúc.
                context_score = max(context_score, 0.52)
                evidence.append("same_label_recent_semantic_parent")
            else:
                context_score -= 0.34
                evidence.append("missing_same_label_actual_tree_parent")

            if schema_same_label_overlap:
                evidence.append("schema_parent_label_overlap")

        candidates.append(
            AliasCandidate(
                node_id=spec.node_id,
                canonical_name=spec.canonical_name,
                parent_id=spec.parent_id,
                kind=spec.kind,
                sector=spec.sector,
                matched_alias=matched_alias,
                method=method,
                alias_score=alias_score,
                context_score=context_score,
                final_score=alias_score + context_score,
                evidence=evidence,
            )
        )

    best_by_id = {}
    for c in candidates:
        if c.node_id not in best_by_id or c.final_score > best_by_id[c.node_id].final_score:
            best_by_id[c.node_id] = c

    return sorted(best_by_id.values(), key=lambda x: x.final_score, reverse=True)


def choose_candidate(candidates: list[AliasCandidate]):
    if not candidates:
        return None, "unknown_label"

    top = candidates[0]
    if top.final_score < 0.80:
        return None, "low_alias_score"

    if len(candidates) > 1 and abs(top.final_score - candidates[1].final_score) < 0.03:
        return None, "ambiguous_mapping"

    return top, None
