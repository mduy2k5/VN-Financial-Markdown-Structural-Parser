from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Any, Optional


@dataclass
class SourceLine:
    line_no: int
    raw: str
    clean: str
    indent: int
    bullet_depth: int
    is_bullet: bool
    bullet_marker: Optional[str]
    heading_level: int
    has_pipe: bool
    is_blank: bool
    page_no: Optional[int] = None


@dataclass
class TableContext:
    table_id: int
    start_line: int
    end_line: int
    header_line: int
    separator_line: int
    header_cells: list[str]


@dataclass
class PrimitiveValue:
    raw_value: str
    normalized_candidate: Optional[Decimal]
    line_no: int
    atom_index: Optional[int] = None
    unit: Optional[str] = None
    is_dash: bool = False
    role: Optional[str] = None


@dataclass
class PrimitivePeriod:
    raw_period: str
    normalized: str
    role: Optional[str]
    line_no: int


@dataclass
class StructuralNode:
    node_index: int
    line_no: int
    raw_text: str
    text: str
    indent: int
    is_bullet: bool
    bullet_marker: Optional[str]
    representation: str  # bullet | plain | table_row
    parent_index: Optional[int] = None
    children: list[int] = field(default_factory=list)

    table_id: Optional[int] = None
    table_header: list[str] = field(default_factory=list)
    table_cells: list[str] = field(default_factory=list)

    label_text: Optional[str] = None
    lhs: Optional[str] = None
    rhs: Optional[str] = None

    values: list[PrimitiveValue] = field(default_factory=list)
    periods: list[PrimitivePeriod] = field(default_factory=list)
    unit: Optional[str] = None
    note: Optional[str] = None
    code: Optional[str] = None
    qualifier: Optional[str] = None

    pattern_id: Optional[str] = None
    pattern_name: Optional[str] = None
    pattern_score: float = 0.0
    pattern_evidence: list[str] = field(default_factory=list)

    inherited_period: Optional[PrimitivePeriod] = None
    inherited_unit: Optional[str] = None


@dataclass
class CanonicalNodeSpec:
    node_id: str
    canonical_name: str
    parent_id: Optional[str]
    kind: str
    sector: str
    exact: list[str]
    aliases: list[str]
    parent_context: list[str]
    contains: list[str]
    exclude_if_contains: list[str]
    structural: dict[str, Any]


@dataclass
class AliasCandidate:
    node_id: str
    canonical_name: str
    parent_id: Optional[str]
    kind: str
    sector: str
    matched_alias: str
    method: str
    alias_score: float
    context_score: float
    final_score: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class FieldObservation:
    anchor_node_index: int
    line_no: int
    source_label: str
    selected: AliasCandidate
    all_candidates: list[AliasCandidate]
    pattern_id: Optional[str]
    pattern_name: Optional[str]

    values: list[PrimitiveValue] = field(default_factory=list)
    period_values: list[tuple[PrimitivePeriod, PrimitiveValue]] = field(default_factory=list)
    note: Optional[str] = None
    code: Optional[str] = None
    unit: Optional[str] = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class ResolvedValue:
    period_key: str
    period_label: Optional[str]
    raw_value: str
    normalized_candidate: Optional[str]
    unit: Optional[str]
    role: Optional[str]
    provenance: str
    source_line: int


@dataclass
class ResolvedField:
    node_id: str
    canonical_name: str
    source_label: str
    source_line: int
    kind: str
    sector: str
    pattern_id: Optional[str]
    pattern_name: Optional[str]
    alias_method: str
    confidence: float
    values: list[ResolvedValue] = field(default_factory=list)
    note: Optional[str] = None
    code: Optional[str] = None
    unit: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    # Source hierarchy is evidence/provenance only.  It must never replace
    # the schema node identity or become a code-based lookup key.
    source_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class StatementContext:
    report_year: Optional[int] = None
    current_label: Optional[str] = None
    previous_label: Optional[str] = None
    unit: Optional[str] = None
    scope_start: int = 1
    scope_end: int = 1


def jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "__dataclass_fields__"):
        return {k: jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj
