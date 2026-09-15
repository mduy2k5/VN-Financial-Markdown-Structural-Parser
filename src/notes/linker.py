from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from .note_ir import NoteDocument, NoteLink
from .sectionizer import normalize_note_id, fold_text
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

    for key, obj in primary.items():
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
    sections_by_id = {
        s.note_id_normalized: s
        for s in doc.sections if s.note_id_normalized
    }
    links: list[NoteLink] = []

    # Explicit primary note references are the strongest evidence.
    for statement_key, node in _iter_primary_nodes(primary):
        ref = _node_note_ref(node)
        if not ref:
            continue
        section = sections_by_id.get(ref)
        if section is None:
            # Allow a parent note reference V.4 to link to V.4(a), V.4(b), ...
            matches = [s for nid, s in sections_by_id.items() if nid and (nid.startswith(ref + ".") or nid.startswith(ref + "("))]
            if len(matches) == 1:
                section = matches[0]
        if section is None:
            continue

        node_id = node.get("node_id") or node.get("canonical_name") or "UNKNOWN"
        link = NoteLink(
            source_ref=section.ref,
            target_ref=f"{statement_key}:{node_id}",
            relation="explains",
            confidence=1.0,
            evidence=["explicit_primary_note_reference"],
            statement_type=statement_key,
            primary_note_reference=ref,
        )
        links.append(link)
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
