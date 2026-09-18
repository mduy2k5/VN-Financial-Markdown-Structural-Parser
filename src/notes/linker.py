from __future__ import annotations

from typing import Any, Optional

from .note_ir import NoteDocument, NoteLink
from .sectionizer import normalize_note_id
from .sector_profile import possible_targets


def _iter_primary_nodes(primary: Any):
    """Yield (statement_key, node) from several canonical container shapes."""
    if not primary:
        return
    if isinstance(primary, dict) and isinstance(primary.get("nodes"), list):
        for n in primary["nodes"]:
            yield "UNKNOWN", n
        return

    if not isinstance(primary, dict):
        return

    # The persisted financial baseline uses `statements.<name>.rows`, while the
    # integrated pipeline uses `statements.<name>.canonical.nodes`. Support both
    # shapes so Notes can be linked during batch evaluation as well as live runs.
    statements = primary.get("statements")
    if isinstance(statements, dict):
        for key, obj in statements.items():
            if not isinstance(obj, dict):
                continue
            for row in obj.get("rows") or []:
                if isinstance(row, dict):
                    yield key, row
            canonical = obj.get("canonical")
            if isinstance(canonical, dict):
                for node in canonical.get("nodes") or []:
                    if isinstance(node, dict):
                        yield key, node

    for key, obj in primary.items():
        if key == "statements":
            continue
        if not isinstance(obj, dict):
            continue
        canonical = obj.get("canonical") if isinstance(obj.get("canonical"), dict) else obj
        if isinstance(canonical, dict) and isinstance(canonical.get("nodes"), list):
            for n in canonical["nodes"]:
                yield key, n


def _node_note_ref(node: dict) -> Optional[str]:
    v = node.get("value") or {}
    raw = v.get("note") or node.get("note")
    if raw:
        return normalize_note_id(str(raw))

    for occ in (node.get("extraction_meta") or {}).get("occurrences") or []:
        raw = occ.get("note") or occ.get("note_ref") or occ.get("note_candidate")
        if raw:
            return normalize_note_id(str(raw))
    return None


def link_notes_to_primary(doc: NoteDocument, primary: Optional[dict] = None) -> list[NoteLink]:
    sections_by_id: dict[str, list] = {}
    for section in doc.sections:
        if section.note_id_normalized:
            sections_by_id.setdefault(section.note_id_normalized, []).append(section)
    links: list[NoteLink] = []

    # Explicit primary note references are the strongest evidence.
    for statement_key, node in _iter_primary_nodes(primary):
        ref = _node_note_ref(node)
        if not ref:
            continue
        matching_sections = sections_by_id.get(ref) or []
        if not matching_sections:
            # Allow a parent note reference V.4 to link to V.4(a), V.4(b), ...
            matching_sections = [
                section
                for nid, candidates in sections_by_id.items()
                if nid and (nid.startswith(ref + ".") or nid.startswith(ref + "("))
                for section in candidates
            ]
        if not matching_sections:
            continue

        node_id = (
            node.get("node_id")
            or node.get("row_id")
            or node.get("canonical_name")
            or "UNKNOWN"
        )
        # A logical note can span many page/continuation sections. Keep the
        # source reference logical when ambiguous and record all instances in
        # metadata rather than silently selecting the last section.
        source_ref = (
            matching_sections[0].ref
            if len(matching_sections) == 1
            else f"NOTE:{ref}"
        )
        link = NoteLink(
            source_ref=source_ref,
            target_ref=f"{statement_key}:{node_id}",
            relation="explains",
            confidence=1.0,
            evidence=["explicit_primary_note_reference"],
            statement_type=statement_key,
            primary_note_reference=ref,
            metadata={
                "section_instance_count": len(matching_sections),
                "section_instance_refs": [section.ref for section in matching_sections],
            },
        )
        links.append(link)
        for section in matching_sections:
            section.links.append(link)

    # Sector ontology is only a low-confidence candidate generator; it never replaces
    # an explicit link and it never writes primary values.
    already = {(x.source_ref, x.target_ref) for x in links}
    for section in doc.sections:
        for target in possible_targets(section.title_raw, doc.sector):
            target_ref = f"ONTOLOGY:{target}"
            key = (section.ref, target_ref)
            if key in already:
                continue
            link = NoteLink(
                source_ref=section.ref,
                target_ref=target_ref,
                relation="topic_candidate",
                confidence=0.55,
                evidence=["sector_profile_title_match"],
                statement_type=None,
            )
            links.append(link)
            section.links.append(link)

    doc.links = links
    return links
