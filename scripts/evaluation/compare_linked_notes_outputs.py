"""Compare two versioned Notes linking/reconciliation outputs.

The comparison is non-destructive.  It produces an aggregate/per-report
delta report and a focused review queue for reconciliation entries that are
new in the right-hand output or changed to ``conflict`` there.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _entry_key(source_file: str, entry: dict[str, Any]) -> tuple[str, ...]:
    # Values and references form the semantic identity.  Derived fields such as
    # ``difference`` may change when a sign convention is normalized, so they
    # must not make the same reconciliation look like a new/removed entry.
    # Status is deliberately excluded so a status transition can be detected.
    return (
        source_file,
        str(entry.get("source_ref") or ""),
        str(entry.get("target_ref") or ""),
        str(entry.get("period") or ""),
        _json_key(entry.get("primary_value")),
        _json_key(entry.get("note_value")),
        str(entry.get("unit_status") or ""),
    )


def _read_ir_entries(output_dir: Path) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    entries: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted((output_dir / "ir").glob("*.notes.ir.json")):
        document = _load(path)
        source_file = str(document.get("source_name") or path.stem)
        for entry in document.get("reconciliation", []) or []:
            record = {"source_file": source_file, **entry}
            entries[_entry_key(source_file, entry)].append(record)
    return entries


def _read_triage(path: Path) -> dict[tuple[str, ...], dict[str, Any]]:
    if not path.exists():
        return {}
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in _load(path):
        result[_entry_key(str(item.get("source_file") or ""), item)] = item
    return result


def _aggregate(summary: dict[str, Any]) -> dict[str, Any]:
    files = summary.get("files", []) or []
    reconciliation = Counter()
    primary_status = Counter(item.get("primary_status") or "missing" for item in files)
    for item in files:
        reconciliation.update(item.get("reconciliation", {}) or {})
    return {
        "files": len(files),
        "aggregate_rows": (summary.get("aggregate_rows") or {}).get("row_count", 0),
        "primary_status": dict(sorted(primary_status.items())),
        "links": sum(item.get("links", 0) or 0 for item in files),
        "high_confidence_links": sum(item.get("high_confidence_links", 0) or 0 for item in files),
        "reconciliation": dict(sorted(reconciliation.items())),
    }


def _summary_by_source(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("source_name")): item for item in summary.get("files", []) or []}


def _per_file_changes(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    left_label: str = "v2",
    right_label: str = "v3",
) -> list[dict[str, Any]]:
    left = _summary_by_source(left_summary)
    right = _summary_by_source(right_summary)
    fields = ["sector", "sections", "tables", "rows", "primary_status", "links", "high_confidence_links", "reconciliation"]
    changes: list[dict[str, Any]] = []
    for source_file in sorted(set(left) | set(right)):
        before = left.get(source_file, {})
        after = right.get(source_file, {})
        changed = {
            field: {left_label: before.get(field), right_label: after.get(field)}
            for field in fields
            if before.get(field) != after.get(field)
        }
        if changed:
            changes.append({"source_file": source_file, "changes": changed})
    return changes


def _compare_entries(
    v2_entries: dict[tuple[str, ...], list[dict[str, Any]]],
    v3_entries: dict[tuple[str, ...], list[dict[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    new_entries: list[dict[str, Any]] = []
    removed_entries: list[dict[str, Any]] = []
    status_changes: list[dict[str, Any]] = []
    new_conflicts: list[dict[str, Any]] = []

    for key in sorted(set(v2_entries) | set(v3_entries)):
        before = v2_entries.get(key, [])
        after = v3_entries.get(key, [])
        common = min(len(before), len(after))
        for index in range(common):
            old = before[index]
            new = after[index]
            if old.get("status") != new.get("status"):
                item = {
                    "change_type": "status_changed",
                    "source_file": new.get("source_file"),
                    "v2_status": old.get("status"),
                    "v3_status": new.get("status"),
                    "entry": new,
                }
                status_changes.append(item)
                if new.get("status") == "conflict" and old.get("status") != "conflict":
                    new_conflicts.append({
                        "change_type": "status_changed_to_conflict",
                        "v2_status": old.get("status"),
                        "v3_status": new.get("status"),
                        "entry": new,
                    })
        for item in after[common:]:
            new_entries.append(item)
            if item.get("status") == "conflict":
                new_conflicts.append({
                    "change_type": "new_conflict",
                    "v2_status": None,
                    "v3_status": item.get("status"),
                    "entry": item,
                })
        for item in before[common:]:
            removed_entries.append(item)

    transition_counts = Counter(
        f"{item.get('v2_status') or 'missing'}->{item.get('v3_status') or 'missing'}"
        for item in status_changes
    )
    unchanged_conflicts = sum(
        1
        for key in set(v2_entries) & set(v3_entries)
        for old, new in zip(v2_entries[key], v3_entries[key])
        if old.get("status") == "conflict" and new.get("status") == "conflict"
    )
    summary = {
        "v2_entries": sum(len(items) for items in v2_entries.values()),
        "v3_entries": sum(len(items) for items in v3_entries.values()),
        "new_entries": len(new_entries),
        "removed_entries": len(removed_entries),
        "status_changed_entries": len(status_changes),
        "unchanged_conflicts": unchanged_conflicts,
        "new_conflicts": len(new_conflicts),
        "status_transitions": dict(sorted(transition_counts.items())),
        "new_conflicts_by_file": dict(sorted(Counter(item["entry"].get("source_file") for item in new_conflicts).items())),
    }
    return {
        "summary": summary,
        "new_entries": new_entries,
        "removed_entries": removed_entries,
        "status_changes": status_changes,
    }, new_conflicts


def _queue_rows(
    new_conflicts: list[dict[str, Any]],
    triage: dict[tuple[str, ...], dict[str, Any]],
    left_label: str = "v2",
    right_label: str = "v3",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    left_status_field = "v2_status" if left_label == "v2" else f"{left_label}_status"
    right_status_field = "v3_status" if right_label == "v3" else f"{right_label}_status"
    for item in new_conflicts:
        entry = item["entry"]
        context = triage.get(_entry_key(str(entry.get("source_file") or ""), entry), {})
        row = {
            "change_type": item["change_type"],
            "source_file": entry.get("source_file"),
            left_status_field: item.get("v2_status") or "",
            right_status_field: item.get("v3_status") or "",
            "source_ref": entry.get("source_ref"),
            "target_ref": entry.get("target_ref"),
            "period": entry.get("period"),
            "primary_value": entry.get("primary_value"),
            "note_value": entry.get("note_value"),
            "difference": entry.get("difference"),
            "unit_status": entry.get("unit_status"),
            "primary_label": context.get("primary_label", ""),
            "primary_note": context.get("primary_note", ""),
            "primary_source_line": context.get("primary_source_line", ""),
            "note_titles": context.get("note_titles", ""),
            "note_lines": context.get("note_lines", ""),
            "evidence": json.dumps(entry.get("evidence") or [], ensure_ascii=False),
            "decision": "",
            "review_notes": "",
        }
        rows.append(row)
    rows.sort(key=lambda row: (row["source_file"] or "", row["target_ref"] or "", row["period"] or ""))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2", type=Path, default=Path("output/notes/linked_v2"))
    parser.add_argument("--v3", type=Path, default=Path("output/notes/linked"))
    parser.add_argument("--left-label", default="v2", help="Label for the left/older output in the report")
    parser.add_argument("--right-label", default="v3", help="Label for the right/newer output in the report")
    parser.add_argument("--v2-triage", "--left-triage", dest="left_triage", type=Path, default=Path("ground_truth/reconciliation_review_v2/triage.json"))
    parser.add_argument("--v3-triage", "--right-triage", dest="right_triage", type=Path, default=Path("ground_truth/reconciliation_review/triage.json"))
    parser.add_argument("--report", type=Path, default=Path("ground_truth/notes/comparison_linked_v2_v3.json"))
    parser.add_argument("--queue-dir", type=Path, default=Path("ground_truth/reconciliation_review"))
    parser.add_argument("--queue-stem", help="Output stem for the focused conflict queue")
    args = parser.parse_args()

    v2_summary_path = args.v2 / "notes_summary.json"
    v3_summary_path = args.v3 / "notes_summary.json"
    if not v2_summary_path.exists() or not v3_summary_path.exists():
        raise SystemExit("Both v2 and v3 notes_summary.json files are required")
    v2_summary = _load(v2_summary_path)
    v3_summary = _load(v3_summary_path)
    v2_entries = _read_ir_entries(args.v2)
    v3_entries = _read_ir_entries(args.v3)
    entry_diff, new_conflicts = _compare_entries(v2_entries, v3_entries)
    triage = _read_triage(args.right_triage)
    queue = _queue_rows(new_conflicts, triage, args.left_label, args.right_label)
    queue_stem = args.queue_stem or f"new_conflicts_vs_{args.left_label}"

    report = {
        "schema_version": "financial_notes_linked_output_comparison_v1",
        f"{args.left_label}_output": str(args.v2),
        f"{args.right_label}_output": str(args.v3),
        "aggregate": {args.left_label: _aggregate(v2_summary), args.right_label: _aggregate(v3_summary)},
        "per_file_changes": _per_file_changes(v2_summary, v3_summary, args.left_label, args.right_label),
        "reconciliation_entries": entry_diff["summary"],
        "new_conflict_queue": {
            "items": len(queue),
            "files": str(args.queue_dir / f"{queue_stem}.csv"),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    args.queue_dir.mkdir(parents=True, exist_ok=True)
    queue_fields = list(queue[0]) if queue else [
        "change_type", "source_file",
        ("v2_status" if args.left_label == "v2" else f"{args.left_label}_status"),
        ("v3_status" if args.right_label == "v3" else f"{args.right_label}_status"),
        "source_ref", "target_ref", "period",
        "primary_value", "note_value", "difference", "unit_status", "primary_label", "primary_note",
        "primary_source_line", "note_titles", "note_lines", "evidence", "decision", "review_notes",
    ]
    with (args.queue_dir / f"{queue_stem}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=queue_fields)
        writer.writeheader()
        writer.writerows(queue)
    (args.queue_dir / f"{queue_stem}.json").write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    queue_manifest = {
        "schema_version": "financial_notes_new_conflict_review_v1",
        "comparison_report": str(args.report),
        "items": len(queue),
        "by_change_type": dict(sorted(Counter(item["change_type"] for item in queue).items())),
        "by_source_file": dict(sorted(Counter(item["source_file"] for item in queue).items())),
        "files": {"csv": f"{queue_stem}.csv", "json": f"{queue_stem}.json"},
    }
    (args.queue_dir / f"{queue_stem}_manifest.json").write_text(json.dumps(queue_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"comparison": report, "new_conflict_queue": queue_manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
