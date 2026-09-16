"""Build an evidence-rich triage queue from audited Notes reconciliation output."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _primary_rows(path: Path) -> dict[str, dict]:
    result = {}
    for statement, payload in _load(path).get("statements", {}).items():
        for row in payload.get("rows", []):
            result[f"{statement}:{row.get('row_id')}"] = row
    return result


def _note_sections(document: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for section in document.get("sections", []):
        result.setdefault(f"NOTE:{section.get('note_id_normalized')}", []).append(section)
        result.setdefault(section.get("section_ref"), []).append(section)
    return result


def _unit(row: dict | None) -> str | None:
    for observation in (row or {}).get("observations", []):
        if observation.get("unit"):
            return observation["unit"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes-output", type=Path, default=Path("output_notes_linked_audited"))
    parser.add_argument("--baselines", type=Path, default=Path("ground_truth/main_statements"))
    parser.add_argument("--output", type=Path, default=Path("ground_truth/reconciliation_review"))
    args = parser.parse_args()

    items: list[dict] = []
    for ir_path in sorted((args.notes_output / "ir").glob("*.notes.ir.json")):
        document = _load(ir_path)
        baseline_path = args.baselines / f"{Path(document['source_name']).stem}.baseline.json"
        primary = _primary_rows(baseline_path) if baseline_path.exists() else {}
        sections = _note_sections(document)
        for entry in document.get("reconciliation", []):
            if entry.get("status") not in {"conflict", "ambiguous_note_totals", "recoverable_candidate"}:
                continue
            target = primary.get(entry.get("target_ref"))
            note_sections = sections.get(entry.get("source_ref"), [])
            note_unit = next((section.get("unit_canonical") or section.get("unit") for section in note_sections if section.get("unit_canonical") or section.get("unit")), None)
            primary_unit = _unit(target)
            status = entry["status"]
            priority = "high" if status == "conflict" else "medium"
            classification = "unit_mismatch" if note_unit and primary_unit and note_unit != primary_unit else "semantic_or_total_mismatch"
            items.append({
                "source_file": document["source_name"],
                "status": status,
                "priority": priority,
                "classification": classification,
                "source_ref": entry.get("source_ref"),
                "note_titles": " | ".join(section.get("title_raw") or "" for section in note_sections),
                "note_lines": ";".join(str(section.get("source_start_line")) for section in note_sections),
                "note_unit": note_unit,
                "target_ref": entry.get("target_ref"),
                "primary_label": (target or {}).get("label"),
                "primary_note": (target or {}).get("note"),
                "primary_source_line": (target or {}).get("source_line"),
                "primary_unit": primary_unit,
                "period": entry.get("period"),
                "primary_value": entry.get("primary_value"),
                "note_value": entry.get("note_value"),
                "difference": entry.get("difference"),
                "evidence": json.dumps(entry.get("evidence") or [], ensure_ascii=False),
                "decision": "",
                "review_notes": "",
            })

    items.sort(key=lambda item: (item["priority"] != "high", item["source_file"], item["target_ref"] or ""))
    args.output.mkdir(parents=True, exist_ok=True)
    fields = list(items[0]) if items else []
    with (args.output / "triage.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(items)
    (args.output / "triage.json").write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "financial_notes_reconciliation_triage_v1",
        "items": len(items),
        "by_status": dict(sorted(Counter(item["status"] for item in items).items())),
        "by_classification": dict(sorted(Counter(item["classification"] for item in items).items())),
        "files": {"json": "triage.json", "csv": "triage.csv"},
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
