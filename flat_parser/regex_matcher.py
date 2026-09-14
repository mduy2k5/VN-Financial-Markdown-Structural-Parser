from __future__ import annotations

import re
from difflib import SequenceMatcher

from .alias_matcher import normalize_label
from .models import AliasCandidate, StructuralNode
from .semantic_catalog import SemanticCatalog


def _phrase_regex(normalized_phrase: str) -> re.Pattern | None:
    phrase = " ".join((normalized_phrase or "").split())
    if not phrase:
        return None
    # normalize_label() leaves a whitespace-token stream, so token boundaries
    # are safer than Python \b for Vietnamese-normalized text.
    return re.compile(r"(?:^|\s)" + re.escape(phrase) + r"(?:\s|$)")


def _matches_phrase(text: str, phrase: str) -> bool:
    pat = _phrase_regex(normalize_label(phrase))
    return bool(pat and pat.search(text))


def _sector_allowed(spec, detected_sector: str | None) -> bool:
    if not detected_sector or spec.sector in {None, "", "common"}:
        return True
    return spec.sector == detected_sector


def regex_match_candidates(
    node: StructuralNode,
    nodes: list[StructuralNode],
    catalog: SemanticCatalog,
    prior_selected: list[tuple[int, str, str]],
    *,
    allow_fuzzy: bool = False,
    detected_sector: str | None = None,
):
    """Flat regex matcher.

    Deliberately ignores source hierarchy, prior semantic anchors and parent
    context. It maps only from the normalized source label to the schema alias
    catalog. This makes it suitable for testing the hypothesis that once rows
    are resolved, schema hierarchy is sufficient for final classification.
    """
    source = normalize_label(node.label_text or node.text or "")
    if not source:
        return []

    candidates: list[AliasCandidate] = []

    for spec in catalog.nodes.values():
        if not _sector_allowed(spec, detected_sector):
            continue

        excluded = False
        for bad in spec.exclude_if_contains:
            bad_n = normalize_label(bad)
            if bad_n and _matches_phrase(source, bad_n):
                excluded = True
                break
        if excluded:
            continue

        matches = []
        canonical_n = normalize_label(spec.canonical_name)
        if source == canonical_n:
            matches.append((1.000, spec.canonical_name, "regex_exact_canonical", len(canonical_n)))

        for x in spec.exact:
            xn = normalize_label(x)
            if source == xn:
                matches.append((0.995, x, "regex_exact", len(xn)))

        for x in spec.aliases:
            xn = normalize_label(x)
            if source == xn:
                matches.append((0.990, x, "regex_alias_exact", len(xn)))

        # Search all configured names with token boundaries. Exact matches above
        # always dominate. The specificity bonus favors the longest phrase and
        # avoids generic aliases winning only because they were listed first.
        phrase_sources = (
            [(spec.canonical_name, "regex_canonical_search", 0.925)]
            + [(x, "regex_exact_search", 0.920) for x in spec.exact]
            + [(x, "regex_alias_search", 0.915) for x in spec.aliases]
            + [(x, "regex_contains_search", 0.900) for x in spec.contains]
        )
        for x, method, base in phrase_sources:
            xn = normalize_label(x)
            if not xn or source == xn:
                continue
            if _matches_phrase(source, xn):
                specificity = min(0.045, len(xn) / max(1, len(source)) * 0.045)
                matches.append((base + specificity, x, method, len(xn)))

        if not matches and allow_fuzzy:
            fuzzy_pool = [spec.canonical_name] + list(spec.exact) + list(spec.aliases)
            best = None
            for x in fuzzy_pool:
                xn = normalize_label(x)
                if min(len(source), len(xn)) < 8:
                    continue
                ratio = SequenceMatcher(None, source, xn).ratio()
                if ratio >= 0.94:
                    score = 0.82 + 0.08 * ratio
                    item = (score, x, "regex_fuzzy", len(xn))
                    if best is None or item[0] > best[0]:
                        best = item
            if best:
                matches.append(best)

        if not matches:
            continue

        score, alias, method, alias_len = max(matches, key=lambda x: (x[0], x[3]))
        candidates.append(
            AliasCandidate(
                node_id=spec.node_id,
                canonical_name=spec.canonical_name,
                parent_id=spec.parent_id,
                kind=spec.kind,
                sector=spec.sector,
                matched_alias=alias,
                method=method,
                alias_score=score,
                context_score=0.0,
                final_score=score,
                evidence=["flat_regex_no_hierarchy", f"matched_length:{alias_len}"],
            )
        )

    best_by_id = {}
    for c in candidates:
        old = best_by_id.get(c.node_id)
        if old is None or c.final_score > old.final_score:
            best_by_id[c.node_id] = c
    return sorted(best_by_id.values(), key=lambda x: x.final_score, reverse=True)
