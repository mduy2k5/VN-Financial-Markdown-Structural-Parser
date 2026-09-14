from __future__ import annotations

from .alias_matcher import match_candidates as legacy_match_candidates, choose_candidate
from .regex_matcher import regex_match_candidates

MAPPING_LEGACY = "legacy"
MAPPING_REGEX = "regex"
MAPPING_ALIAS_REGEX_FALLBACK = "alias-regex-fallback"
MAPPING_STRATEGIES = {MAPPING_LEGACY, MAPPING_REGEX, MAPPING_ALIAS_REGEX_FALLBACK}


def _regex_fallback_candidates(
    node,
    nodes,
    catalog,
    prior_selected,
    *,
    allow_fuzzy=False,
    detected_sector=None,
):
    """Strict regex fallback used only after normal alias mapping fails.

    Policy:
      * regex never competes with a successful legacy/alias result;
      * fuzzy regex is disabled for automatic fallback;
      * top result must be high confidence;
      * if there is a runner-up, require a meaningful score gap;
      * ambiguous generic labels therefore remain unresolved/reviewable.
    """
    candidates = regex_match_candidates(
        node,
        nodes,
        catalog,
        prior_selected,
        allow_fuzzy=False,  # automatic fallback must stay deterministic
        detected_sector=detected_sector,
    )
    if not candidates:
        return []

    top = candidates[0]
    if top.final_score < 0.93:
        return []

    if len(candidates) > 1:
        gap = top.final_score - candidates[1].final_score
        if gap < 0.08:
            return []

    # Mark provenance explicitly so diagnostics/alias discovery can find it.
    for c in candidates:
        original = c.method
        c.method = f"regex_fallback_{original.removeprefix('regex_')}"
        c.evidence = list(c.evidence) + ["fallback_after_alias_failure", f"regex_original_method:{original}"]
    return candidates


def match_candidates_for_strategy(
    strategy,
    node,
    nodes,
    catalog,
    prior_selected,
    *,
    allow_fuzzy=False,
    detected_sector=None,
):
    strategy = (strategy or MAPPING_LEGACY).lower()

    if strategy == MAPPING_REGEX:
        return regex_match_candidates(
            node, nodes, catalog, prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
        )

    if strategy == MAPPING_LEGACY:
        return legacy_match_candidates(
            node, nodes, catalog, prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
        )

    if strategy == MAPPING_ALIAS_REGEX_FALLBACK:
        legacy = legacy_match_candidates(
            node, nodes, catalog, prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
        )
        selected, _ = choose_candidate(legacy)
        if selected is not None:
            return legacy
        return _regex_fallback_candidates(
            node,
            nodes,
            catalog,
            prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
        )

    raise ValueError(f"Unknown mapping strategy: {strategy}")
