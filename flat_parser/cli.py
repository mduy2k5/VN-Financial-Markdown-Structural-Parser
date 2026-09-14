from __future__ import annotations

import argparse
from pathlib import Path

from .debug_writer import write_result_bundle
from .pipeline import FlatParserPipeline
from .coverage_reporter import build_coverage_report


def build_parser():
    p = argparse.ArgumentParser(
        description="Universal alias-first financial-position parser (A1-A5 guides)."
    )
    p.add_argument("input", help="Markdown file or folder")
    p.add_argument(
        "--schema",
        default="resources/universal_financial_position_schema_v1_1.json",
    )
    p.add_argument(
        "--aliases",
        default="resources/universal_financial_position_aliases_v1_1.json",
    )
    p.add_argument(
        "--guide",
        default="resources/universal_structural_guide_a1_a5.json",
    )
    p.add_argument("--output", default="output_flat_v0_4")
    p.add_argument(
        "--scope",
        choices=["financial_position", "whole"],
        default="financial_position",
    )
    p.add_argument("--fuzzy", action="store_true")
    p.add_argument("--allow-unknown-structure", action="store_true")
    p.add_argument(
        "--coverage-report", action="store_true",
        help="Write batch coverage diagnostics JSON/CSV under <output>/coverage/.",
    )
    p.add_argument(
        "--coverage-top", type=int, default=100,
        help="Maximum number of aggregate unknown labels in the coverage report.",
    )
    return p


def main():
    args = build_parser().parse_args()

    pipeline = FlatParserPipeline(
        schema_path=args.schema,
        aliases_path=args.aliases,
        universal_guide_path=args.guide,
        allow_fuzzy=args.fuzzy,
        scope_mode=args.scope,
        allow_unknown_structure=args.allow_unknown_structure,
    )

    inp = Path(args.input)
    if inp.is_file():
        files = [inp]
    elif inp.is_dir():
        files = sorted(
            x for x in inp.rglob("*")
            if x.is_file() and x.suffix.lower() in {".md", ".txt"}
        )
    else:
        raise SystemExit(f"Input not found: {inp}")

    if not files:
        raise SystemExit("No .md/.txt files found.")

    parsed_results = []
    for path in files:
        result = pipeline.parse_file(path)
        parsed_results.append((path, result))
        target = write_result_bundle(args.output, path, result)
        stats = result["debug"]["stats"]
        scope_health = stats.get("scope_health", "unknown")
        statement_health = stats.get("statement_health", "unknown")
        health_parts = []
        if scope_health != "healthy":
            health_parts.append(f"scope={scope_health}")
        if statement_health != "healthy":
            health_parts.append(f"statement={statement_health}")
        health_suffix = (" " + " ".join(health_parts)) if health_parts else ""
        coverage = stats.get("semantic_label_coverage")
        coverage_suffix = (
            f" coverage={coverage:.1%}"
            if isinstance(coverage, (int, float)) else ""
        )
        actionable_coverage = stats.get("actionable_semantic_label_coverage")
        actionable_coverage_suffix = (
            f" actionable_coverage={actionable_coverage:.1%}"
            if isinstance(actionable_coverage, (int, float)) else ""
        )
        unknown = stats.get("unknown_financial_labels", 0)
        actionable_unknown = stats.get("actionable_unknown_financial_labels", 0)
        true_actionable_unknown = stats.get("true_actionable_unknown_financial_labels", 0)
        true_coverage = stats.get("true_actionable_semantic_label_coverage")
        unknown_suffix = f" unknown={unknown}" if unknown else ""
        actionable_suffix = f" actionable_unknown={actionable_unknown}" if actionable_unknown else ""
        true_actionable_suffix = f" true_actionable_unknown={true_actionable_unknown}" if true_actionable_unknown else ""
        true_coverage_suffix = (
            f" true_actionable_coverage={true_coverage:.1%}"
            if isinstance(true_coverage, (int, float)) else ""
        )
        version = stats.get("parser_version", "?")
        print(
            f"{path.name}: parser={version} nodes={stats['structural_nodes']} "
            f"resolved={stats['resolved_before_dedup']} "
            f"unresolved={stats['unresolved']}"
            f"{coverage_suffix}{actionable_coverage_suffix}{true_coverage_suffix}{unknown_suffix}{actionable_suffix}{true_actionable_suffix}"
            f"{health_suffix} -> {target}"
        )

    # Folder/batch mode always writes coverage diagnostics in v0.4.12.2.
    # This preserves the user's long-standing command line: no extra flag needed.
    if args.coverage_report or inp.is_dir():
        report = build_coverage_report(
            parsed_results, args.output, top_n=max(1, args.coverage_top)
        )
        summary = report.get("summary", {})
        print(
            f"coverage_report: files={summary.get('files', 0)} "
            f"P0={summary.get('p0', 0)} P1={summary.get('p1', 0)} "
            f"P2={summary.get('p2', 0)} P3={summary.get('p3', 0)} "
            f"-> {Path(args.output) / 'coverage' / 'coverage_summary.json'}"
        )


if __name__ == "__main__":
    main()
