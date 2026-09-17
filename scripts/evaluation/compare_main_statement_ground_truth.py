"""Compare current three-statement canonical output with source-grounded baselines.

The baseline stores observations by source row, while the current parser stores
semantic canonical nodes.  This comparator therefore compares normalized
``label + period + value`` evidence instead of requiring identical JSON shape
or node IDs.  It reports missing expected values separately from extra parser
observations so structural changes do not get misreported as numeric errors.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.common.ground_truth_quality import (
        assess_observation,
        evidence_key,
        fold_text as quality_fold_text,
        infer_year_pair,
        iter_observations,
        normalize_label,
        observation_period,
        extract_inline_period_values,
        source_period_hint,
        parse_number as quality_parse_number,
        period_role as quality_period_role,
    )
except ImportError:
    from common.ground_truth_quality import (
        assess_observation,
        evidence_key,
        fold_text as quality_fold_text,
        infer_year_pair,
        iter_observations,
        normalize_label,
        observation_period,
        extract_inline_period_values,
        source_period_hint,
        parse_number as quality_parse_number,
        period_role as quality_period_role,
    )


STATEMENT_FILES = {
    "financial_position": ".financial_position.canonical.json",
    "income_statement": ".income.canonical.json",
    "cash_flow": ".cashflow.canonical.json",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fold_text(value: Any) -> str:
    return normalize_label(value)


def number(value: Any) -> int | float | None:
    return quality_parse_number(value)


def period_role(value: Any, current_year: int | None = None, previous_year: int | None = None) -> str:
    return quality_period_role(value, current_year, previous_year)


def collect_expected_evidence(
    statement: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    statement_name: str = "",
    mode: str = "raw",
    source_lines: list[str] | None = None,
    period_context: dict[str, Any] | None = None,
) -> tuple[set[tuple[str, str, int | float]], dict[str, Any]]:
    evidence: set[tuple[str, str, int | float]] = set()
    excluded = Counter()
    current_year, previous_year = infer_year_pair(
        baseline or statement,
        source_text="\n".join(source_lines) if source_lines else None,
    )
    if isinstance(period_context, dict):
        try:
            context_current = period_context.get("current_year")
            context_previous = period_context.get("previous_year")
            if context_current is not None:
                current_year = int(context_current)
                previous_year = int(context_previous) if context_previous is not None else current_year - 1
        except (TypeError, ValueError):
            pass
    manual_review_required = bool((baseline or {}).get("repair_meta", {}).get("manual_review_required"))
    observations_seen = 0
    eligible_observations = 0
    for row, observation in iter_observations(statement):
        observations_seen += 1
        source_line_text = None
        if source_lines is not None:
            try:
                source_line_text = source_lines[int(observation.get("source_line")) - 1]
            except (TypeError, ValueError, IndexError):
                source_line_text = ""
        effective_observation = dict(observation)
        context_period = source_period_hint(
            source_lines,
            int(observation.get("source_line") or 0),
            current_year,
            previous_year,
        )
        raw_periods = {
            period_role(observation.get("period_raw"), current_year, previous_year),
            period_role(observation.get("raw_text"), current_year, previous_year),
        }
        # A generic ``Số liệu`` row inherits the nearest explicit section year;
        # this repairs baselines that flattened two year sections into one
        # current-period column without changing rows with explicit raw years.
        key_period = period_role(
            observation.get("period_key"), current_year, previous_year
        )
        if (
            context_period == "previous"
            and key_period == "current"
            and raw_periods.isdisjoint({"current", "previous"})
        ):
            effective_observation["period_key"] = context_period
        inline_values = extract_inline_period_values(
            observation.get("raw_text"),
            current_year,
            previous_year,
            observation.get("value"),
        )
        if mode == "eligible":
            decision = assess_observation(
                row,
                effective_observation,
                current_year=current_year,
                previous_year=previous_year,
                source_line_text=source_line_text,
                manual_review_required=manual_review_required,
            )
            if not decision.eligible:
                excluded.update(decision.reasons)
                continue
            label = fold_text(row.get("label"))
            if inline_values:
                for period, value in inline_values:
                    evidence.add((label, period, value))
                eligible_observations += len(inline_values)
            else:
                evidence.add(evidence_key(row, decision))
                eligible_observations += 1
            continue

        label = fold_text(row.get("label"))
        period = observation_period(effective_observation, current_year, previous_year)
        value = number(observation.get("value"))
        if label and period and value is not None:
            if inline_values:
                for inline_period, inline_value in inline_values:
                    evidence.add((label, inline_period, inline_value))
                eligible_observations += len(inline_values)
            else:
                evidence.add((label, period, value))
                eligible_observations += 1
    quality = {
        "mode": mode,
        "statement": statement_name,
        "inferred_current_year": current_year,
        "inferred_previous_year": previous_year,
        "period_context_source": "current_output" if period_context else "baseline_or_source",
        "manual_review_required": manual_review_required,
        "observations_seen": observations_seen,
        "eligible_observations": eligible_observations,
        "excluded_observations": sum(excluded.values()),
        "excluded_by_reason": dict(sorted(excluded.items())),
        "distinct_evidence_values": len(evidence),
    }
    return evidence, quality


def expected_evidence(statement: dict[str, Any]) -> set[tuple[str, str, int | float]]:
    """Backward-compatible raw evidence helper used by older callers."""

    return collect_expected_evidence(statement)[0]


def current_evidence(
    document: dict[str, Any],
    current_year: int | None = None,
    previous_year: int | None = None,
) -> set[tuple[str, str, int | float]]:
    evidence: set[tuple[str, str, int | float]] = set()
    # The source reconciliation view keeps the original recovered labels and
    # the consensus value even when the canonical mapper chose a different
    # semantic label.  Include it so a layout/label normalization difference
    # is not mistaken for a missing number.
    for row in document.get("reconciled_source_view") or []:
        label = fold_text(row.get("display_label") or row.get("normalized_label"))
        if label:
            for period in ("current", "previous"):
                value = number(row.get(period))
                if value is not None:
                    evidence.add((label, period, value))
    for node in document.get("nodes") or []:
        metadata = node.get("extraction_meta") or {}
        # Hydration/reconciliation may fill the canonical value while keeping
        # the original occurrence unchanged.  The canonical value is still
        # source-backed output and must participate in comparison; otherwise a
        # correctly recovered prior-period value is reported as missing merely
        # because it was added after the first occurrence was emitted.
        node_label = fold_text(node.get("canonical_name"))
        node_value = node.get("value") or {}
        if node_label and isinstance(node_value, dict):
            for period in ("current", "previous"):
                value = number(node_value.get(period))
                if value is not None:
                    evidence.add((node_label, period, value))
        for occurrence in metadata.get("occurrences") or []:
            label = fold_text(occurrence.get("source_label") or node.get("canonical_name"))
            nested_values = occurrence.get("values")
            if isinstance(nested_values, list):
                for item in nested_values:
                    period = period_role(
                        item.get("period_key")
                        or item.get("period_role")
                        or item.get("role")
                        or "",
                        current_year,
                        previous_year,
                    )
                    value = number(
                        item.get("normalized_candidate")
                        if item.get("normalized_candidate") is not None
                        else item.get("value")
                    )
                    if label and period and value is not None:
                        evidence.add((label, period, value))
                continue
            for period in ("current", "previous"):
                value = number(occurrence.get(period))
                if label and value is not None:
                    evidence.add((label, period, value))
    return evidence


def compare_statement(
    baseline: dict[str, Any],
    statement_name: str,
    current: dict[str, Any] | None,
    *,
    ground_truth_mode: str = "raw",
    source_lines: list[str] | None = None,
) -> dict[str, Any]:
    expected, ground_truth_quality = collect_expected_evidence(
        (baseline.get("statements") or {}).get(statement_name) or {},
        baseline=baseline,
        statement_name=statement_name,
        mode=ground_truth_mode,
        source_lines=source_lines,
        period_context=(
            ((current or {}).get("provenance") or {}).get("year_resolution")
            if isinstance(current, dict)
            else None
        ),
    )
    actual = current_evidence(
        current or {},
        ground_truth_quality.get("inferred_current_year"),
        ground_truth_quality.get("inferred_previous_year"),
    )
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    matched = len(expected) - len(missing)
    expected_numeric = {(period, value) for _label, period, value in expected}
    actual_numeric = {(period, value) for _label, period, value in actual}
    numeric_missing = expected_numeric - actual_numeric
    numeric_matched = len(expected_numeric) - len(numeric_missing)
    expected_values_only = {value for _label, _period, value in expected}
    actual_values_only = {value for _label, _period, value in actual}
    values_only_missing = expected_values_only - actual_values_only
    values_only_matched = len(expected_values_only) - len(values_only_missing)
    return {
        "expected_values": len(expected),
        "current_values": len(actual),
        "matched_values": matched,
        "missing_values": len(missing),
        "unexpected_values": len(unexpected),
        "value_match_rate": round(matched / len(expected), 6) if expected else None,
        "numeric_value_pairs": len(expected_numeric),
        "numeric_value_pairs_matched": numeric_matched,
        "numeric_value_match_rate": round(numeric_matched / len(expected_numeric), 6) if expected_numeric else None,
        "numeric_value_pairs_missing": len(numeric_missing),
        "expected_value_set_subset": not missing,
        "distinct_numeric_values": len(expected_values_only),
        "distinct_numeric_values_matched": values_only_matched,
        "distinct_numeric_values_missing": len(values_only_missing),
        "value_only_match_rate": round(
            values_only_matched / len(expected_values_only), 6
        ) if expected_values_only else None,
        "value_only_expected_subset": not values_only_missing,
        "missing_examples": [
            {"label": label, "period": period, "value": value}
            for label, period, value in missing[:20]
        ],
        "unexpected_examples": [
            {"label": label, "period": period, "value": value}
            for label, period, value in unexpected[:20]
        ],
        "current_file_missing": current is None,
        "ground_truth_quality": ground_truth_quality,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, default=Path("ground_truth/main_statements"))
    parser.add_argument("--current", type=Path, default=Path("output/current"))
    parser.add_argument(
        "--ground-truth-mode",
        choices=["raw", "eligible"],
        default="raw",
        help="raw keeps the persisted baseline; eligible excludes ambiguous observations from the primary score.",
    )
    parser.add_argument("--sources", type=Path, help="Optional Markdown source directory for source-line validation.")
    parser.add_argument("--report", type=Path, default=Path("output/evaluations/comparison_main_statements.json"))
    args = parser.parse_args()

    reports: list[dict[str, Any]] = []
    for gt_path in sorted(args.ground_truth.glob("*.baseline.json")):
        baseline = load_json(gt_path)
        source_name = str(baseline.get("source_file") or "")
        stem = Path(source_name).stem
        source_lines = None
        if args.sources:
            source_path = args.sources / source_name
            if source_path.exists():
                source_lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        statement_results: dict[str, Any] = {}
        for statement_name, suffix in STATEMENT_FILES.items():
            current_path = args.current / f"{stem}{suffix}"
            current = load_json(current_path) if current_path.exists() else None
            statement_results[statement_name] = compare_statement(
                baseline,
                statement_name,
                current,
                ground_truth_mode=args.ground_truth_mode,
                source_lines=source_lines,
            )

        current_hashes = {
            result.get("source_sha256")
            for result in (
                load_json(args.current / f"{stem}{suffix}")
                for suffix in STATEMENT_FILES.values()
                if (args.current / f"{stem}{suffix}").exists()
            )
        }
        expected_hash = baseline.get("source_sha256")
        all_subsets = all(item["expected_value_set_subset"] for item in statement_results.values())
        reports.append(
            {
                "source_file": source_name,
                "ground_truth_file": gt_path.name,
                "source_hash_equal": bool(expected_hash and current_hashes == {expected_hash}),
                "all_expected_values_found": all_subsets,
                "statements": statement_results,
            }
        )

    statement_summary: dict[str, dict[str, Any]] = {}
    for statement_name in STATEMENT_FILES:
        values = [report["statements"][statement_name] for report in reports]
        expected = sum(item["expected_values"] for item in values)
        matched = sum(item["matched_values"] for item in values)
        distinct_values = sum(item["distinct_numeric_values"] for item in values)
        distinct_values_matched = sum(item["distinct_numeric_values_matched"] for item in values)
        statement_summary[statement_name] = {
            "reports": len(values),
            "expected_values": expected,
            "current_values": sum(item["current_values"] for item in values),
            "matched_values": matched,
            "missing_values": sum(item["missing_values"] for item in values),
            "unexpected_values": sum(item["unexpected_values"] for item in values),
            "value_match_rate": round(matched / expected, 6) if expected else None,
            "numeric_value_pairs": sum(item["numeric_value_pairs"] for item in values),
            "numeric_value_pairs_matched": sum(item["numeric_value_pairs_matched"] for item in values),
            "numeric_value_pairs_missing": sum(item["numeric_value_pairs_missing"] for item in values),
            "numeric_value_match_rate": round(
                sum(item["numeric_value_pairs_matched"] for item in values)
                / sum(item["numeric_value_pairs"] for item in values),
                6,
            ) if sum(item["numeric_value_pairs"] for item in values) else None,
            "distinct_numeric_values": distinct_values,
            "distinct_numeric_values_matched": distinct_values_matched,
            "distinct_numeric_values_missing": sum(
                item["distinct_numeric_values_missing"] for item in values
            ),
            "value_only_match_rate": round(
                distinct_values_matched / distinct_values, 6
            ) if distinct_values else None,
            "reports_with_all_value_only_values": sum(
                item["value_only_expected_subset"] for item in values
            ),
            "reports_with_all_expected_values": sum(item["expected_value_set_subset"] for item in values),
            "reports_missing_current_file": sum(item["current_file_missing"] for item in values),
        }

    summary = {
        "schema_version": "financial_main_statement_ground_truth_comparison_v2",
        "ground_truth_directory": str(args.ground_truth),
        "current_output_directory": str(args.current),
        "ground_truth_mode": args.ground_truth_mode,
        "source_line_validation": bool(args.sources),
        "ground_truth_reports": len(reports),
        "source_hash_matches": sum(report["source_hash_equal"] for report in reports),
        "reports_with_all_expected_values": sum(report["all_expected_values_found"] for report in reports),
        "statement_summary": statement_summary,
        "reports": reports,
        "limitations": (
            "Comparison is against parser-assisted baselines. It measures whether current output "
            "contains the baseline label/period/value evidence; it is not a human-verified gold-standard score. "
            "numeric_value_match_rate requires the same normalized period and value, while "
            "value_only_match_rate intentionally ignores label and period to measure numeric evidence coverage "
            "when the baseline has layout- or period-label artifacts. The value-only metric must not be read as "
            "semantic-label or period correctness."
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {key: value for key, value in summary.items() if key not in {"reports", "limitations"}}
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
