from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional


BlockForm = Literal["table", "paragraph", "bullet_list", "mixed", "unknown"]
SemanticShape = Literal[
    "breakdown", "movement", "reconciliation", "aging",
    "matrix", "narrative", "unknown"
]
RowRole = Literal["detail", "subtotal", "total", "opening", "closing", "movement", "header", "unknown"]


@dataclass
class NoteValue:
    raw: Any
    normalized: Optional[float | int] = None
    period_label: Optional[str] = None
    period_role: Optional[str] = None
    movement_role: Optional[str] = None
    measure: Optional[str] = None
    unit: Optional[str] = None
    source_line: Optional[int] = None
    source_column: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NoteRow:
    label_raw: str
    label_normalized: str
    values: list[NoteValue] = field(default_factory=list)
    code: Optional[str] = None
    note_ref: Optional[str] = None
    row_role: RowRole = "detail"
    hierarchy_path: list[str] = field(default_factory=list)
    source_line: Optional[int] = None
    raw_cells: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "values": [x.to_dict() for x in self.values],
        }


@dataclass
class NoteBlock:
    block_id: str
    form: BlockForm
    semantic_shape: SemanticShape
    source_start_line: int
    source_end_line: int
    headers_raw: list[str] = field(default_factory=list)
    headers_normalized: list[str] = field(default_factory=list)
    rows: list[NoteRow] = field(default_factory=list)
    text: Optional[str] = None
    unit_raw: Optional[str] = None
    unit: Optional[str] = None
    source_page: Optional[int] = None
    dimensions: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "rows": [x.to_dict() for x in self.rows],
        }


@dataclass
class NoteLink:
    source_ref: str
    target_ref: str
    relation: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    statement_type: Optional[str] = None
    primary_note_reference: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReconciliationResult:
    source_ref: str
    target_ref: str
    status: str
    period: Optional[str] = None
    primary_value: Any = None
    note_value: Any = None
    difference: Optional[float] = None
    unit_status: str = "unknown"
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NoteSection:
    note_id_raw: Optional[str]
    note_id_normalized: Optional[str]
    title_raw: str
    title_normalized: str
    source_start_line: int
    source_end_line: int
    pages: list[int] = field(default_factory=list)
    unit_raw: Optional[str] = None
    unit: Optional[str] = None
    blocks: list[NoteBlock] = field(default_factory=list)
    links: list[NoteLink] = field(default_factory=list)
    sector_topic: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        nid = self.note_id_normalized or self.note_id_raw or f"LINE{self.source_start_line}"
        return f"NOTE:{nid}"

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "blocks": [x.to_dict() for x in self.blocks],
            "links": [x.to_dict() for x in self.links],
        }


@dataclass
class NoteDocument:
    source_name: str
    sector: str
    scope_start_line: Optional[int]
    scope_end_line: Optional[int]
    scope_confidence: float
    sections: list[NoteSection] = field(default_factory=list)
    links: list[NoteLink] = field(default_factory=list)
    reconciliation: list[ReconciliationResult] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    schema_id: str = "GENERIC_NOTE_IR_V1"
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "source_name": self.source_name,
            "sector": self.sector,
            "scope_start_line": self.scope_start_line,
            "scope_end_line": self.scope_end_line,
            "scope_confidence": self.scope_confidence,
            "sections": [x.to_dict() for x in self.sections],
            "links": [x.to_dict() for x in self.links],
            "reconciliation": [x.to_dict() for x in self.reconciliation],
            "diagnostics": self.diagnostics,
        }
