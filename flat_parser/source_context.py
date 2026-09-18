from __future__ import annotations

from .document import ancestors
from .models import StructuralNode
from .textnorm import fold


def _label(node: StructuralNode) -> str:
    return (node.label_text or node.text or "").strip()


def source_context_for_node(
    node: StructuralNode,
    nodes: list[StructuralNode],
    prior_selected: list[tuple[int, str, str]] | None = None,
    catalog=None,
) -> dict:
    """Tạo bằng chứng hierarchy nguồn không semantic cho một dòng đã map.

    Context cố ý được suy ra từ ancestor cấu trúc và nhãn, không từ mã biểu mẫu
    hay node id canonical. Nó giúp phân biệt các chiều nguồn như nợ ngắn/dài hạn
    mà vẫn giữ quan hệ parent của schema hiện tại.
    """

    chain = list(reversed(ancestors(nodes, node.node_index)))
    labels = [_label(item) for item in chain]
    current_label = _label(node)
    if current_label:
        labels.append(current_label)
    # Header bảng có thể đi vào stream cấu trúc như một nhãn plain duy nhất;
    # đó là metadata truyền tải, không phải một cấp hierarchy nghiệp vụ.
    header_terms = ("ma so", "thuyet minh", "so cuoi nam", "so dau nam")
    labels = [
        label for label in labels
        if label and not (
            "," in label
            and sum(term in fold(label) for term in header_terms) >= 2
        )
    ]
    if not labels:
        return {}

    folded = [fold(label) for label in labels]
    maturity = None
    maturity_source = None
    for label, normalized in zip(labels, folded):
        if "ngan han" in normalized:
            maturity = "short_term"
            maturity_source = label
            break
        if "dai han" in normalized and normalized not in {
            "tai san dai han",
            "tai san ngan han",
        }:
            maturity = "long_term"
            maturity_source = label
            break

    # Nhãn cấu trúc đầu là section nguồn tổng quát. Giữ toàn bộ path vì nhãn
    # chung có thể lặp dưới các parent khác nhau.
    context = {
        "path": labels,
        "parent_label": labels[-2] if len(labels) >= 2 else None,
        "section": labels[0] if labels else None,
    }
    if maturity:
        context["maturity"] = maturity
        context["maturity_source"] = maturity_source

    # Một số bảng nguồn đặt child chung (``Nguyên giá`` / ``Khấu hao``) cùng
    # mức thụt lề với dòng nhóm trước đó. Chỉ dùng ancestor cây không thấy được
    # nhóm này, nên giữ group đã map gần nhất làm bằng chứng bổ sung. Semantic
    # matching ở đây chỉ phục vụ hiển thị provenance; không đổi node identity
    # hay khóa loại trùng.
    if prior_selected and catalog is not None:
        generic_labels = {
            "nguyen gia",
            "gia tri hao mon luy ke",
            "gia tri khau hao luy ke",
            "hao mon luy ke",
            "khau hao luy ke",
        }
        if fold(current_label) not in generic_labels:
            return context
        normalized_path = {fold(label) for label in labels}
        for line_no, node_id, selected_label in reversed(prior_selected):
            if line_no >= node.line_no:
                continue
            if node.line_no - line_no > 12:
                break
            spec = catalog.nodes.get(node_id)
            if not spec or spec.kind not in {"group", "section"}:
                continue
            if fold(selected_label) in normalized_path:
                break
            context["semantic_anchor"] = selected_label
            break
    return context
