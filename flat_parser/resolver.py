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

    # Ngày mở đầu bảng cân đối 01/01/YYYY đại diện cho cuối kỳ trước,
    # dù cùng năm lịch với ngày hiện tại 31/12/YYYY.
    if context.report_year and re.search(
        rf"\b0?1[./]0?1[./]{context.report_year}\b",
        period.raw_period or "",
    ):
        return "previous"

    # Nhãn context khớp chính xác phải được ưu tiên hơn phân loại năm chung.
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
    """Ưu tiên đơn vị tiền tệ rõ ở local, nếu không dùng context báo cáo.

    Không lan truyền đơn vị cấu trúc không liên quan như ``cổ phần`` vào dòng tiền.
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
    source_context: dict | None = None,
):
    """Chuyển payload observation thô thành giá trị đã giải quyết theo kỳ.

    Nhãn kỳ rõ ràng được ưu tiên. Giá trị theo vị trí chỉ dùng context cục bộ
    khi bộ phân loại cấu trúc đã xác định pattern an toàn; cấu trúc chưa biết
    vẫn chưa giải quyết để xem xét.
    """
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

        # Payload BCTC theo vị trí dạng chung. Số đầu nhỏ có thể là mã/thuyết minh.
        if len(raw) > 2:
            first = raw[0]
            if (
                first.normalized_candidate is not None
                and first.normalized_candidate == first.normalized_candidate.to_integral()
                and 0 <= first.normalized_candidate < 1000
            ):
                raw = raw[1:]

        # Segment pipe A4 có role không bị ép vào hiện tại/trước đây.
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

    # Thuyết minh ngoại bảng đặc biệt dễ hỏng thụt lề: một tiêu đề không có
    # payload có thể theo sau bởi tiêu đề kế tiếp mang hai cặp hiện tại/trước đây
    # khác nhau (một cặp thực ra thuộc tiêu đề trước). Không để canonical
    # first-wins âm thầm chọn một giá trị khi một observation có giá trị xung đột
    # cho cùng kỳ; đưa mơ hồ nguồn/cấu trúc ra để xem xét.
    if c.node_id.startswith("OFF_BALANCE.") and values:
        by_period = {}
        for v in values:
            by_period.setdefault(v.period_key, set()).add(v.raw_value.strip())
        if any(len(raws) > 1 for raws in by_period.values()):
            return None, "conflicting_period_payloads"

    # Cây thụt lề hỏng có thể lộ cùng thuộc tính kỳ qua hai nhánh cấu trúc.
    # Một observation semantic vẫn chỉ có tối đa một giá trị giống nhau cho mỗi
    # kỳ; giữ provenance sớm nhất.
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
        source_context=dict(source_context or {}),
    ), None
