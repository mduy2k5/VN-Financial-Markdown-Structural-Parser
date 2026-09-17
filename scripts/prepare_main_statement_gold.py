"""Prepare a source-grounded gold-candidate set and review queue.

This command never overwrites the persisted ground truth.  It applies generic
quality gates to each observation, writes eligible candidates separately, and
queues ambiguous rows with evidence-backed reasons for adjudication.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.common.ground_truth_quality import (
        assess_observation,
        evidence_key,
        fold_text,
        infer_year_pair,
        iter_observations,
        normalize_label,
        extract_inline_period_values,
        source_period_hint,
        period_role,
    )
except ImportError:
    from common.ground_truth_quality import (
        assess_observation,
        evidence_key,
        fold_text,
        infer_year_pair,
        iter_observations,
        normalize_label,
        extract_inline_period_values,
        source_period_hint,
        period_role,
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if path.exists() else []


def analyze_baseline(path: Path, source_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    baseline = load_json(path)
    source_path = source_dir / str(baseline.get("source_file") or "")
    lines = source_lines(source_path)
    current_year, previous_year = infer_year_pair(
        baseline,
        source_text="\n".join(lines) if lines else None,
    )
    manual_review_required = bool((baseline.get("repair_meta") or {}).get("manual_review_required"))
    candidates: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str, str, int | float]] = set()
    observations_seen = 0

    for statement_name, statement in (baseline.get("statements") or {}).items():
        for row, observation in iter_observations(statement):
            observations_seen += 1
            try:
                line_number = int(observation.get("source_line"))
            except (TypeError, ValueError):
                line_number = 0
            line_text = lines[line_number - 1] if 0 < line_number <= len(lines) else None
            effective_observation = dict(observation)
            context_period = source_period_hint(lines, line_number, current_year, previous_year)
            raw_periods = {
                period_role(observation.get("period_raw"), current_year, previous_year),
                period_role(observation.get("raw_text"), current_year, previous_year),
            }
            if (
                context_period == "previous"
                and period_role(observation.get("period_key"), current_year, previous_year) == "current"
                and raw_periods.isdisjoint({"current", "previous"})
            ):
                effective_observation["period_key"] = context_period
            inline_values = extract_inline_period_values(
                observation.get("raw_text"),
                current_year,
                previous_year,
                observation.get("value"),
            )
            decision = assess_observation(
                row,
                effective_observation,
                current_year=current_year,
                previous_year=previous_year,
                source_line_text=line_text,
                manual_review_required=manual_review_required,
            )
            base = {
                "baseline": path.name,
                "source_file": baseline.get("source_file"),
                "statement": statement_name,
                "row_id": row.get("row_id"),
                "label": row.get("label"),
                "normalized_label": normalize_label(row.get("label")),
                "code": row.get("code"),
                "period": decision.period,
                "value": decision.value,
                "source_line": observation.get("source_line"),
                "raw_text": observation.get("raw_text"),
                "source_line_text": line_text,
                "reasons": list(decision.reasons),
                "inline_recovered": bool(inline_values),
            }
            if decision.eligible:
                recovered_values = inline_values or [(decision.period, decision.value)]
                for recovered_period, recovered_value in recovered_values:
                    candidate = dict(base)
                    candidate["period"] = recovered_period
                    candidate["value"] = recovered_value
                    dedupe = (statement_name, base["normalized_label"], recovered_period, recovered_value)
                    if dedupe in seen:
                        counts["duplicate_candidate"] += 1
                        continue
                    seen.add(dedupe)
                    candidates.append(candidate)
                    counts["eligible"] += 1
            else:
                review.append(base)
                counts.update(decision.reasons)

    report = {
        "baseline": path.name,
        "source_file": baseline.get("source_file"),
        "source_exists": source_path.exists(),
        "source_sha256": baseline.get("source_sha256"),
        "inferred_current_year": current_year,
        "inferred_previous_year": previous_year,
        "manual_review_required": manual_review_required,
        "observations_seen": observations_seen,
        "eligible_candidates": len(candidates),
        "review_rows": len(review),
        "counts": dict(sorted(counts.items())),
    }
    return report, candidates, review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baselines", type=Path, default=Path("ground_truth/main_statements"))
    parser.add_argument("--source-dir", type=Path, default=Path("md_reports"))
    parser.add_argument("--output", type=Path, default=Path("output/evaluations/main_statement_gold_queue"))
    args = parser.parse_args()

    reports: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for path in sorted(args.baselines.glob("*.baseline.json")):
        report, accepted, queued = analyze_baseline(path, args.source_dir)
        reports.append(report)
        candidates.extend(accepted)
        review.extend(queued)

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "financial_main_statement_gold_candidate_queue_v1",
        "baseline_directory": str(args.baselines),
        "source_directory": str(args.source_dir),
        "baseline_files": len(reports),
        "observations_seen": sum(item["observations_seen"] for item in reports),
        "eligible_candidates": len(candidates),
        "review_rows": len(review),
        "reports_with_manual_review": sum(item["manual_review_required"] for item in reports),
        "reason_counts": dict(sorted(Counter(reason for item in review for reason in item["reasons"]).items())),
        "files": {
            "reports": "reports.json",
            "candidates": "gold_candidates.json",
            "review_queue": "review_queue.csv",
        },
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "reports.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "gold_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = [
        "baseline", "source_file", "statement", "row_id", "label", "normalized_label",
        "code", "period", "value", "source_line", "raw_text", "source_line_text", "reasons", "inline_recovered",
    ]
    with (args.output / "review_queue.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in review:
            row = dict(item)
            row["reasons"] = ";".join(item.get("reasons") or [])
            writer.writerow({key: row.get(key) for key in fields})
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
