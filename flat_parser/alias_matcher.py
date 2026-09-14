from __future__ import annotations

from difflib import SequenceMatcher

from .document import ancestors
from .models import AliasCandidate, StructuralNode
from .semantic_catalog import SemanticCatalog
from .textnorm import fold, strip_numbering


def normalize_label(text: str) -> str:
    text = strip_numbering(text or "")
    text = text.strip(" |;:-")
    return fold(text)


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


def _nearest_semantic_ancestor_texts(
    node: StructuralNode,
    nodes: list[StructuralNode],
    prior_selected: list[tuple[int, str, str]],
):
    """
    Return semantic ancestor evidence ordered nearest-first.

    Tree indentation is preferred. If tree ancestry is weak, use recently
    selected canonical anchors as a fallback, but with lower weight.
    """
    tree = ancestors(nodes, node.node_index)
    tree_texts = [normalize_label(x.label_text or x.text) for x in tree]

    prior = []
    for line_no, node_id, label in reversed(prior_selected[-50:]):
        if node.line_no - line_no > 100:
            break
        prior.append((line_no, node_id, normalize_label(label)))

    return tree_texts, prior


def match_candidates(
    node: StructuralNode,
    nodes: list[StructuralNode],
    catalog: SemanticCatalog,
    prior_selected: list[tuple[int, str, str]],
    *,
    allow_fuzzy: bool = False,
    detected_sector: str | None = None,
):
    text = node.label_text or ""
    if not text:
        return []

    candidates = []
    tree_texts, prior = _nearest_semantic_ancestor_texts(
        node, nodes, prior_selected
    )

    for spec in catalog.nodes.values():
        base = _base_match(text, spec, allow_fuzzy)
        if not base:
            continue

        # v0.4.14 targeted sector guards for newly enriched generic labels.
        # This avoids changing legacy matching behavior for the rest of the catalog.
        normalized_source = normalize_label(text)
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
            continue

        alias_score, matched_alias, method = base
        context_score = 0.0
        evidence = []

        parent_context = [normalize_label(x) for x in spec.parent_context if x]
        ancestor_ids = catalog.ancestor_ids(spec.node_id)

        # Nearest tree ancestor is strongest semantic evidence.
        for distance, tree_text in enumerate(tree_texts):
            if not tree_text:
                continue

            if tree_text in parent_context:
                boost = 0.58 if distance == 0 else max(0.16, 0.30 - distance * 0.04)
                context_score = max(context_score, boost)
                evidence.append(f"nearest_tree_parent_context:d{distance}")
                break

        # Recent canonical direct parent is next strongest.  Weight by
        # source-line distance, not only by recency rank: damaged Markdown
        # indentation can make several historical parents visible at once.
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

        # Table rows are often flat, so the previous semantic row may be a
        # sibling rather than an explicit tree parent.  A shared canonical
        # parent is useful weak context (e.g. ASSET.OTHER.* vs LIABILITY.*).
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

        # More distant canonical ancestor is weaker.
        for rank, (line_no, prior_id, prior_label) in enumerate(prior):
            if prior_id in ancestor_ids:
                context_score = max(context_score, 0.07)
                evidence.append(f"recent_ancestor:{prior_id}")
                break

        structural = spec.structural or {}
        if structural.get("same_label_as_parent_required"):
            # IMPORTANT: repeated positional siblings must NOT be mistaken for
            # parent/child pairs.  Require the ACTUAL nearest tree parent to
            # carry the same label.  This preserves true structures such as:
            #   Cho vay khách hàng
            #       Cho vay khách hàng -> .GROSS
            # while keeping two adjacent same-label rows in the same node so
            # the consolidator can merge current/previous columns.
            actual_parent_same_label = bool(
                tree_texts
                and tree_texts[0]
                and tree_texts[0] == normalize_label(text)
            )
            if actual_parent_same_label:
                context_score += 0.30
                evidence.append("same_label_actual_tree_parent")
            else:
                context_score -= 0.34
                evidence.append("missing_same_label_actual_tree_parent")

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
