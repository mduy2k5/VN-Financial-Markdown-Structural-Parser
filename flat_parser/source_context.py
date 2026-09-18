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
    """Build non-semantic source hierarchy evidence for one mapped row.

    The context is intentionally derived from structural ancestry and labels,
    not from form codes or the canonical node id.  It lets consumers
    distinguish source dimensions such as current/non-current liabilities
    while preserving the existing schema parent relationship.
    """

    chain = list(reversed(ancestors(nodes, node.node_index)))
    labels = [_label(item) for item in chain]
    current_label = _label(node)
    if current_label:
        labels.append(current_label)
    # Table headers can enter the structural stream as a single plain label;
    # they are transport metadata, not a business hierarchy level.
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

    # The first structural label is the broad source section.  Keep the full
    # path because generic labels may repeat under different parents.
    context = {
        "path": labels,
        "parent_label": labels[-2] if len(labels) >= 2 else None,
        "section": labels[0] if labels else None,
    }
    if maturity:
        context["maturity"] = maturity
        context["maturity_source"] = maturity_source

    # Some source tables put generic children (``Nguyên giá`` / ``Khấu hao``)
    # at the same indentation as their preceding category row.  Tree ancestry
    # alone cannot see that category, so retain the nearest previously mapped
    # group as additional evidence.  This uses semantic matching only for
    # provenance display; it does not alter the node identity or dedup key.
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
