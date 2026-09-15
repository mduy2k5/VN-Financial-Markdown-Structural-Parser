from __future__ import annotations

from typing import Any, Optional

from .note_ir import NoteDocument, ReconciliationResult
from .sectionizer import fold_text


def _primary_node_index(primary: Optional[dict]) -> dict[str, dict]:
    out = {}
    if not primary or not isinstance(primary, dict):
        return out

    def consume(prefix, obj):
        canonical = obj.get("canonical") if isinstance(obj, dict) and isinstance(obj.get("canonical"), dict) else obj
        if not isinstance(canonical, dict):
            return
        for n in canonical.get("nodes") or []:
            nid = n.get("node_id")
            if nid:
                out[f"{prefix}:{nid}"] = n

    if isinstance(primary.get("nodes"), list):
        consume("UNKNOWN", primary)
    else:
        for key, obj in primary.items():
            if isinstance(obj, dict):
                consume(key, obj)
    return out


def _best_note_totals(section):
    """Return simple total candidates by period role, with source references."""
    out = {}
    total_labels = ("tong cong", "tong", "cong", "gia tri con lai", "doanh thu thuan", "tong chi phi")
    for block in section.blocks:
        if block.form != "table":
            continue
        for row in block.rows:
            is_total = row.row_role == "total" or any(x in row.label_normalized for x in total_labels)
            if not is_total:
                continue
            for val in row.values:
                if val.normalized is None:
                    continue
                role = val.period_role
                if role in {"current", "previous"}:
                    out.setdefault(role, []).append((val.normalized, f"{section.ref}:{block.block_id}:{row.source_line}"))
    return out


def reconcile_notes(doc: NoteDocument, primary: Optional[dict] = None) -> list[ReconciliationResult]:
    """Non-destructive reconciliation.

    Policy:
      - primary values remain authoritative;
      - equal note totals confirm;
      - conflicts are reported, never overwritten;
      - missing primary values are not mutated here. Recovery must be an explicit
        downstream decision based on an exact link and an exact reconciliation.
    """
    index = _primary_node_index(primary)
    section_map = {s.ref: s for s in doc.sections}
    results = []

    for link in doc.links:
        if link.confidence < 0.95 or link.target_ref not in index:
            continue
        section = section_map.get(link.source_ref)
        if not section:
            continue
        totals = _best_note_totals(section)
        node = index[link.target_ref]
        pv = node.get("value") or {}

        for period in ("current", "previous"):
            primary_value = pv.get(period)
            candidates = totals.get(period, [])
            if not candidates:
                results.append(ReconciliationResult(
                    source_ref=link.source_ref,
                    target_ref=link.target_ref,
                    status="no_note_total",
                    period=period,
                    primary_value=primary_value,
                    evidence=["explicit_link_but_no_simple_total"],
                ))
                continue

            # Exact match is preferred; otherwise use only when there is a single total candidate.
            exact = [x for x in candidates if primary_value is not None and x[0] == primary_value]
            if exact:
                note_value = exact[0][0]
                status = "confirmed"
                evidence = ["explicit_link", "exact_amount_match", exact[0][1]]
            elif len(candidates) == 1:
                note_value = candidates[0][0]
                if primary_value is None:
                    status = "recoverable_candidate"
                    evidence = ["explicit_link", "unique_note_total", "primary_missing", candidates[0][1]]
                else:
                    status = "conflict"
                    evidence = ["explicit_link", "unique_note_total_mismatch", candidates[0][1]]
            else:
                note_value = None
                status = "ambiguous_note_totals"
                evidence = ["explicit_link", f"candidate_count:{len(candidates)}"]

            diff = None
            if isinstance(primary_value, (int, float)) and isinstance(note_value, (int, float)):
                diff = note_value - primary_value

            results.append(ReconciliationResult(
                source_ref=link.source_ref,
                target_ref=link.target_ref,
                status=status,
                period=period,
                primary_value=primary_value,
                note_value=note_value,
                difference=diff,
                unit_status="not_scaled",
                evidence=evidence,
                metadata={"policy": "PRIMARY_GT_NOTES_non_destructive_v1"},
            ))

    doc.reconciliation = results
    return results
