from __future__ import annotations

import re

from .models import FieldObservation, ResolvedField, ResolvedValue, StatementContext
from .textnorm import fold


YEAR_RE = re.compile(r"\b20\d{2}\b")


def _period_key(period, context: StatementContext):
    if period.role in {"current", "previous"}:
        return period.role

    f = fold(period.raw_period)
    if any(x in f for x in ("so cuoi nam", "cuoi nam", "nam nay", "du no cuoi nam")):
        return "current"
    if any(x in f for x in ("so dau nam", "dau nam", "nam truoc", "du no dau nam")):
        return "previous"

    # Balance-sheet opening date 01/01/YYYY represents previous-period end,
    # even though it has the same calendar year as the current 31/12/YYYY.
    if context.report_year and re.search(
        rf"\b0?1[./]0?1[./]{context.report_year}\b",
        period.raw_period or "",
    ):
        return "previous"

    # Exact context labels should beat generic year classification.
    if context.current_label and fold(context.current_label) == f:
        return "current"
    if context.previous_label and fold(context.previous_label) == f:
        return "previous"

    years = [int(x) for x in YEAR_RE.findall(period.raw_period)]
    if years and context.report_year:
        if years[0] == context.report_year:
            return "current"
        if years[0] == context.report_year - 1:
            return "previous"

    f = fold(period.raw_period)
    return f"additional:{period.raw_period}"



def _financial_unit(value_unit, observation_unit, context_unit):
    """
    Prefer local explicit monetary unit, otherwise statement context.
    Avoid propagating unrelated structural units such as 'cổ phần' to money rows.
    """
    monetary_markers = (
        "đồng", "vnd", "vnđ", "usd", "eur",
        "triệu", "tỷ", "nghìn"
    )
    for candidate in (value_unit, observation_unit):
        if candidate and any(x in candidate.casefold() for x in monetary_markers):
            return candidate
    return context_unit or value_unit or observation_unit

def resolve_observation(
    obs: FieldObservation,
    context: StatementContext,
    *,
    allow_structure_unknown: bool = False,
):
    c = obs.selected
    if not obs.pattern_id and not allow_structure_unknown:
        return None, "unknown_structure"

    values = []

    if obs.period_values:
        for p, v in obs.period_values:
            key = _period_key(p, context)
            values.append(
                ResolvedValue(
                    period_key=key,
                    period_label=p.raw_period,
                    raw_value=v.raw_value,
                    normalized_candidate=(
                        str(v.normalized_candidate)
                        if v.normalized_candidate is not None
                        else None
                    ),
                    unit=_financial_unit(v.unit, obs.unit, context.unit),
                    role=v.role or p.role,
                    provenance="explicit_period_or_inherited_context",
                    source_line=v.line_no,
                )
            )
    else:
        raw = list(obs.values)

        # Generic BCTC positional payload. Small first number may be code/note.
        if len(raw) > 2:
            first = raw[0]
            if (
                first.normalized_candidate is not None
                and first.normalized_candidate == first.normalized_candidate.to_integral()
                and 0 <= first.normalized_candidate < 1000
            ):
                raw = raw[1:]

        # Role-bearing A4 pipe segments are not forced into current/previous.
        if raw and any(v.role for v in raw):
            for v in raw:
                values.append(
                    ResolvedValue(
                        period_key=f"additional:{v.role or 'value'}",
                        period_label=None,
                        raw_value=v.raw_value,
                        normalized_candidate=(
                            str(v.normalized_candidate)
                            if v.normalized_candidate is not None else None
                        ),
                        unit=_financial_unit(v.unit, obs.unit, context.unit),
                        role=v.role,
                        provenance="explicit_role",
                        source_line=v.line_no,
                    )
                )
        else:
            for i, v in enumerate(raw[:2]):
                key = "current" if i == 0 else "previous"
                label = context.current_label if i == 0 else context.previous_label
                values.append(
                    ResolvedValue(
                        period_key=key,
                        period_label=label,
                        raw_value=v.raw_value,
                        normalized_candidate=(
                            str(v.normalized_candidate)
                            if v.normalized_candidate is not None else None
                        ),
                        unit=_financial_unit(v.unit, obs.unit, context.unit),
                        role=key,
                        provenance="positional_context",
                        source_line=v.line_no,
                    )
                )

    # Off-balance disclosures are especially prone to damaged indentation:
    # a heading with no payload may be followed by the next heading carrying
    # two distinct current/previous pairs (one pair actually belongs to the
    # preceding heading).  Never let canonical first-wins silently choose a
    # value when one observation contains conflicting values for the same
    # period.  Surface the source/structure ambiguity for review instead.
    if c.node_id.startswith("OFF_BALANCE.") and values:
        by_period = {}
        for v in values:
            by_period.setdefault(v.period_key, set()).add(v.raw_value.strip())
        if any(len(raws) > 1 for raws in by_period.values()):
            return None, "conflicting_period_payloads"

    # A malformed indentation tree can expose the same period attributes
    # through two structural paths.  One semantic observation still has at
    # most one identical value per period; keep the earliest provenance.
    deduped_values = []
    seen_values = set()
    for v in values:
        key = (v.period_key, v.raw_value)
        if key in seen_values:
            continue
        seen_values.add(key)
        deduped_values.append(v)
    values = deduped_values

    meaningful = bool(values or obs.note or obs.code)
    if not meaningful and c.kind not in {"section", "group"}:
        return None, "no_payload"

    warnings = []
    if c.method == "fuzzy":
        warnings.append("fuzzy_alias_match")
    if not values and c.kind in {"section", "group"}:
        warnings.append("structural_anchor_without_direct_value")

    confidence = min(1.0, c.final_score + (0.03 if obs.pattern_id else 0.0))

    return ResolvedField(
        node_id=c.node_id,
        canonical_name=c.canonical_name,
        source_label=obs.source_label,
        source_line=obs.line_no,
        kind=c.kind,
        sector=c.sector,
        pattern_id=obs.pattern_id,
        pattern_name=obs.pattern_name,
        alias_method=c.method,
        confidence=round(confidence, 4),
        values=values,
        note=obs.note,
        code=obs.code,
        unit=_financial_unit(None, obs.unit, context.unit),
        warnings=warnings,
    ), None
