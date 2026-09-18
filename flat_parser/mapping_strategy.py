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
    source_context=None,
):
    """Fallback regex nghiêm ngặt, chỉ dùng sau khi mapping alias thường thất bại.

    Chính sách:
      * regex không cạnh tranh với kết quả legacy/alias đã thành công;
      * tắt regex fuzzy trong fallback tự động;
      * kết quả đầu phải có độ tin cậy cao;
      * nếu có kết quả thứ hai, phải có khoảng cách điểm đủ lớn;
      * vì vậy nhãn chung mơ hồ sẽ ở trạng thái chưa giải quyết/cần xem xét.
    """
    candidates = regex_match_candidates(
        node,
        nodes,
        catalog,
        prior_selected,
        allow_fuzzy=False,  # fallback tự động phải có tính quyết định
        detected_sector=detected_sector,
        source_context=source_context,
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

    # Ghi rõ provenance để chẩn đoán và phát hiện alias có thể truy vết.
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
    source_context=None,
):
    strategy = (strategy or MAPPING_LEGACY).lower()

    if strategy == MAPPING_REGEX:
        return regex_match_candidates(
            node, nodes, catalog, prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
            source_context=source_context,
        )

    if strategy == MAPPING_LEGACY:
        return legacy_match_candidates(
            node, nodes, catalog, prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
            source_context=source_context,
        )

    if strategy == MAPPING_ALIAS_REGEX_FALLBACK:
        legacy = legacy_match_candidates(
            node, nodes, catalog, prior_selected,
            allow_fuzzy=allow_fuzzy,
            detected_sector=detected_sector,
            source_context=source_context,
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
            source_context=source_context,
        )

    raise ValueError(f"Unknown mapping strategy: {strategy}")
