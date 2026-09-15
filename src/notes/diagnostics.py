from __future__ import annotations

from collections import Counter

from .note_ir import NoteDocument
from .scanner import primary_heading_decoys_in_scope, NotesScope


def build_diagnostics(doc: NoteDocument, text: str, scope: NotesScope) -> dict:
    shapes = Counter()
    forms = Counter()
    rows = 0
    tables = 0
    for section in doc.sections:
        for block in section.blocks:
            shapes[block.semantic_shape] += 1
            forms[block.form] += 1
            rows += len(block.rows)
            if block.form == "table":
                tables += 1

    recon = Counter(x.status for x in doc.reconciliation)
    return {
        "notes_found": scope.found,
        "scope": scope.to_dict(),
        "section_count": len(doc.sections),
        "block_count": sum(len(s.blocks) for s in doc.sections),
        "table_count": tables,
        "row_count": rows,
        "block_forms": dict(forms),
        "semantic_shapes": dict(shapes),
        "link_count": len(doc.links),
        "high_confidence_links": sum(1 for x in doc.links if x.confidence >= 0.95),
        "reconciliation": dict(recon),
        "primary_heading_decoys_inside_notes": primary_heading_decoys_in_scope(text, scope),
        "false_primary_capture_guard": "sticky_notes_scope",
        "numeric_scaling_policy": "never_scale_notes_values",
    }
