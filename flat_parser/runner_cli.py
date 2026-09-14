from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .abc_compare import compare_three, pairwise
from .bullet_mapped_pipeline import BulletMappedPipeline
from .flow_mapped_pipeline import FlowMappedPipeline
from .integrated_debug_writer import write_integrated_bundle
from .integrated_pipeline import IntegratedFinancialPipeline

ENGINE_V05 = "v05"
ENGINE_FLOW = "flow"
ENGINE_HYBRID = "hybrid"
ENGINES = [ENGINE_V05, ENGINE_FLOW, ENGINE_HYBRID]
MODE_COMPARE = "compare"
MODE_MAPPING_COMPARE = "mapping-compare"
MODE_FALLBACK_COMPARE = "fallback-compare"
MAPPING_LEGACY = "legacy"
MAPPING_REGEX = "regex"
MAPPING_ALIAS_REGEX_FALLBACK = "alias-regex-fallback"


def _dump(path: str | Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _input_files(inp: str | Path) -> list[Path]:
    inp = Path(inp)
    if inp.is_file():
        if inp.suffix.lower() not in {".md", ".txt"}:
            raise SystemExit(f"Unsupported input file: {inp}")
        return [inp]
    if inp.is_dir():
        return sorted(p for p in inp.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"})
    raise SystemExit(f"Input not found: {inp}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unified parser with switchable mapping strategies and feature flags.")
    p.add_argument("input", help="Markdown/TXT file or folder")
    p.add_argument(
        "--mode",
        choices=[ENGINE_V05, ENGINE_FLOW, ENGINE_HYBRID, MODE_COMPARE, MODE_MAPPING_COMPARE, MODE_FALLBACK_COMPARE],
        default=ENGINE_HYBRID,
        help=(
            "v05/flow/hybrid=run one engine; compare=compare 3 engines with selected mapper; "
            "mapping-compare=run all 3 with legacy and regex-only; fallback-compare=compare legacy against alias+regex-fallback"
        ),
    )
    p.add_argument("--mapping-strategy", choices=[MAPPING_LEGACY, MAPPING_REGEX, MAPPING_ALIAS_REGEX_FALLBACK], default=MAPPING_LEGACY)
    p.add_argument(
        "--regex-fallback",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="After legacy alias mapping fails, try strict unique/high-confidence regex search. Equivalent to --mapping-strategy alias-regex-fallback when enabled with legacy.",
    )
    p.add_argument(
        "--collect-alias-candidates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Collect successful regex fallback hits as alias candidates for review/promote.",
    )
    p.add_argument("--output", default="output_parser", help="Output root directory")
    p.add_argument("--financial-schema", default="resources/universal_financial_position_schema_v1_6.json")
    p.add_argument("--financial-aliases", default="resources/universal_financial_position_aliases_v1_6_1.json")
    p.add_argument("--off-balance-schema", default="resources/universal_off_balance_bank_schema_v1_3.json")
    p.add_argument("--off-balance-aliases", default="resources/universal_off_balance_bank_aliases_v1_3.json")
    p.add_argument("--guide", default="resources/universal_structural_guide_a1_a5.json")
    p.add_argument("--fuzzy", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--allow-unknown-structure", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument(
        "--hybrid-fill",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable/disable Flow fill stage inside hybrid. --no-hybrid-fill makes hybrid equal its v05 base.",
    )
    return p


def _effective_strategy(args, requested: str | None = None):
    strategy = requested or args.mapping_strategy
    if args.regex_fallback and strategy == MAPPING_LEGACY:
        return MAPPING_ALIAS_REGEX_FALLBACK
    return strategy


def _build_pipeline(engine: str, args, *, mapping_strategy: str | None = None):
    strategy = _effective_strategy(args, mapping_strategy)
    common = dict(
        financial_schema_path=args.financial_schema,
        financial_aliases_path=args.financial_aliases,
        off_balance_schema_path=args.off_balance_schema,
        off_balance_aliases_path=args.off_balance_aliases,
        allow_fuzzy=args.fuzzy,
        allow_unknown_structure=args.allow_unknown_structure,
        mapping_strategy=strategy,
    )
    if engine == ENGINE_V05:
        return IntegratedFinancialPipeline(universal_guide_path=args.guide, **common)
    if engine == ENGINE_FLOW:
        return FlowMappedPipeline(universal_guide_path=args.guide, **common)
    if engine == ENGINE_HYBRID:
        return BulletMappedPipeline(universal_guide_path=args.guide, hybrid_fill=args.hybrid_fill, **common)
    raise ValueError(f"Unknown engine: {engine}")


def _value_nodes(result: dict) -> int:
    canonical = (((result.get("statements") or {}).get("financial_position") or {}).get("canonical") or {})
    nodes = canonical.get("nodes") if isinstance(canonical, dict) else None
    if not isinstance(nodes, list):
        return 0
    return sum(1 for node in nodes if any(((node or {}).get("value") or {}).get(k) is not None for k in ("current", "previous")))


def _summary_row(source_name: str, comp: dict) -> dict:
    fp = comp["financial_position"]
    row = {
        "source_name": source_name,
        "v05_value_nodes": fp["v05"]["value_nodes"],
        "flow_value_nodes": fp["flow"]["value_nodes"],
        "hybrid_value_nodes": fp["hybrid"]["value_nodes"],
    }
    for key, val in fp["pairwise"].items():
        row[f"{key}_same"] = val["same_value_nodes"]
        row[f"{key}_different"] = val["different_value_nodes"]
        for subkey, subval in val.items():
            if subkey.startswith("only_") and subkey.endswith("_value_nodes"):
                row[f"{key}_{subkey}"] = subval
    return row


def _manifest(args, files: list[Path], mode: str) -> dict:
    return {
        "runner_version": "unified-runner-1.1-feature-flags",
        "mode": mode,
        "mapping_strategy": _effective_strategy(args),
        "requested_mapping_strategy": args.mapping_strategy,
        "input": str(args.input),
        "output": str(args.output),
        "file_count": len(files),
        "files": [p.name for p in files],
        "resources": {
            "financial_schema": args.financial_schema,
            "financial_aliases": args.financial_aliases,
            "off_balance_schema": args.off_balance_schema,
            "off_balance_aliases": args.off_balance_aliases,
            "guide": args.guide,
        },
        "features": {
            "regex_mapping": _effective_strategy(args) == MAPPING_REGEX,
            "legacy_mapping": _effective_strategy(args) == MAPPING_LEGACY,
            "regex_fallback": _effective_strategy(args) == MAPPING_ALIAS_REGEX_FALLBACK,
            "collect_alias_candidates": bool(args.collect_alias_candidates),
            "hybrid_fill": bool(args.hybrid_fill),
            "fuzzy": bool(args.fuzzy),
            "allow_unknown_structure": bool(args.allow_unknown_structure),
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _mark(result, *, engine: str, strategy: str, mode: str):
    result.setdefault("run_meta", {})
    result["run_meta"].update({
        "requested_mode": mode,
        "engine_slot": engine,
        "mapping_strategy": strategy,
        "runner_version": "unified-runner-1.1-feature-flags",
    })
    return result




def _collect_regex_fallback_alias_candidates(result: dict, source_name: str, engine: str) -> list[dict]:
    """Collect canonical occurrences created by regex fallback.

    This deliberately reads final canonical provenance rather than extractor internals,
    so it works for v05, flow and hybrid with one implementation.
    """
    out = []
    statements = result.get("statements") or {}
    for statement_key, statement in statements.items():
        canonical = (statement or {}).get("canonical") or {}
        nodes = canonical.get("nodes") if isinstance(canonical, dict) else None
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            meta = (node or {}).get("extraction_meta") or {}
            for occ in meta.get("occurrences") or []:
                method = str((occ or {}).get("alias_method") or "")
                if not method.startswith("regex_fallback_"):
                    continue
                out.append({
                    "source_name": source_name,
                    "engine": engine,
                    "statement": statement_key,
                    "source_line": occ.get("source_line"),
                    "source_label": occ.get("source_label"),
                    "node_id": node.get("node_id"),
                    "canonical_name": node.get("canonical_name"),
                    "mapping_method": method,
                    "confidence": occ.get("confidence"),
                    "suggested_alias": occ.get("source_label"),
                })
    return out


def _write_alias_candidates(out: Path, rows: list[dict]) -> None:
    if not rows:
        _dump(out / "alias_candidates.json", [])
        return
    # Aggregate repeated source-label -> node suggestions while preserving raw hits.
    agg = {}
    for row in rows:
        key = (row.get("source_label"), row.get("node_id"))
        item = agg.setdefault(key, {
            "source_label": row.get("source_label"),
            "suggested_alias": row.get("suggested_alias"),
            "node_id": row.get("node_id"),
            "canonical_name": row.get("canonical_name"),
            "count": 0,
            "files": set(),
            "engines": set(),
            "methods": set(),
            "max_confidence": 0.0,
        })
        item["count"] += 1
        item["files"].add(row.get("source_name"))
        item["engines"].add(row.get("engine"))
        item["methods"].add(row.get("mapping_method"))
        try:
            item["max_confidence"] = max(item["max_confidence"], float(row.get("confidence") or 0.0))
        except Exception:
            pass
    aggregate = []
    for item in agg.values():
        item["files"] = sorted(x for x in item["files"] if x)
        item["engines"] = sorted(x for x in item["engines"] if x)
        item["methods"] = sorted(x for x in item["methods"] if x)
        item["file_count"] = len(item["files"])
        aggregate.append(item)
    aggregate.sort(key=lambda x: (-x["count"], x.get("source_label") or ""))
    _dump(out / "alias_candidates.json", {"aggregate": aggregate, "hits": rows})
    _write_csv(out / "alias_candidates.csv", aggregate)


def run_single(args, engine: str, files: list[Path], out: Path) -> None:
    strategy = _effective_strategy(args)
    pipeline = _build_pipeline(engine, args, mapping_strategy=strategy)
    rows = []
    alias_candidate_rows = []
    engine_out = out / strategy / engine
    for path in files:
        result = _mark(pipeline.parse_file(path), engine=engine, strategy=strategy, mode=engine)
        write_integrated_bundle(engine_out, path, result)
        value_nodes = _value_nodes(result)
        if args.collect_alias_candidates:
            alias_candidate_rows.extend(_collect_regex_fallback_alias_candidates(result, path.name, engine))
        rows.append({"source_name": path.name, "engine": engine, "mapping_strategy": strategy, "financial_position_value_nodes": value_nodes})
        print(f"{path.name}: {engine}/{strategy} | value_nodes={value_nodes}")
    _write_csv(out / "run_summary.csv", rows)
    _dump(out / "run_summary.json", rows)
    if args.collect_alias_candidates:
        _write_alias_candidates(out, alias_candidate_rows)


def run_compare(args, files: list[Path], out: Path) -> None:
    strategy = _effective_strategy(args)
    pipes = {engine: _build_pipeline(engine, args, mapping_strategy=strategy) for engine in ENGINES}
    summaries, csv_rows = [], []
    alias_candidate_rows = []
    for path in files:
        results = {name: _mark(pipe.parse_file(path), engine=name, strategy=strategy, mode=MODE_COMPARE) for name, pipe in pipes.items()}
        for name, result in results.items():
            write_integrated_bundle(out / strategy / name, path, result)
            if args.collect_alias_candidates:
                alias_candidate_rows.extend(_collect_regex_fallback_alias_candidates(result, path.name, name))
        comp = compare_three(results[ENGINE_V05], results[ENGINE_FLOW], results[ENGINE_HYBRID])
        comp["source_name"] = path.name
        comp["mapping_strategy"] = strategy
        _dump(out / strategy / "comparison" / f"{path.stem}.comparison.json", comp)
        summaries.append(comp)
        row = _summary_row(path.name, comp)
        row["mapping_strategy"] = strategy
        csv_rows.append(row)
        fp = comp["financial_position"]
        print(f"{path.name}: {strategy} | v05={fp['v05']['value_nodes']} flow={fp['flow']['value_nodes']} hybrid={fp['hybrid']['value_nodes']}")
    _dump(out / strategy / "comparison_summary.json", summaries)
    _write_csv(out / strategy / "comparison_summary.csv", csv_rows)
    if args.collect_alias_candidates:
        _write_alias_candidates(out, alias_candidate_rows)


def run_mapping_compare(args, files: list[Path], out: Path) -> None:
    all_rows = []
    details = []
    for path in files:
        strategy_results = {}
        for strategy in (MAPPING_LEGACY, MAPPING_REGEX):
            engine_results = {}
            for engine in ENGINES:
                pipe = _build_pipeline(engine, args, mapping_strategy=strategy)
                result = _mark(pipe.parse_file(path), engine=engine, strategy=strategy, mode=MODE_MAPPING_COMPARE)
                engine_results[engine] = result
                write_integrated_bundle(out / strategy / engine, path, result)
            strategy_results[strategy] = engine_results

            comp3 = compare_three(engine_results[ENGINE_V05], engine_results[ENGINE_FLOW], engine_results[ENGINE_HYBRID])
            comp3["source_name"] = path.name
            comp3["mapping_strategy"] = strategy
            _dump(out / strategy / "comparison" / f"{path.stem}.comparison.json", comp3)

        item = {"source_name": path.name, "engines": {}}
        row = {"source_name": path.name}
        for engine in ENGINES:
            legacy = strategy_results[MAPPING_LEGACY][engine]
            regex = strategy_results[MAPPING_REGEX][engine]
            pw = pairwise("legacy", legacy, "regex", regex)
            legacy_n = _value_nodes(legacy)
            regex_n = _value_nodes(regex)
            item["engines"][engine] = {
                "legacy_value_nodes": legacy_n,
                "regex_value_nodes": regex_n,
                "regex_delta": regex_n - legacy_n,
                "legacy_vs_regex": pw,
            }
            row[f"{engine}_legacy_nodes"] = legacy_n
            row[f"{engine}_regex_nodes"] = regex_n
            row[f"{engine}_regex_delta"] = regex_n - legacy_n
            row[f"{engine}_same"] = pw["same_value_nodes"]
            row[f"{engine}_different"] = pw["different_value_nodes"]
            row[f"{engine}_only_legacy"] = pw["only_legacy_value_nodes"]
            row[f"{engine}_only_regex"] = pw["only_regex_value_nodes"]
        details.append(item)
        all_rows.append(row)
        print(
            f"{path.name}: "
            + " | ".join(f"{e} {row[f'{e}_legacy_nodes']}->{row[f'{e}_regex_nodes']} ({row[f'{e}_regex_delta']:+d})" for e in ENGINES)
        )

    _dump(out / "mapping_strategy_comparison.json", details)
    _write_csv(out / "mapping_strategy_comparison.csv", all_rows)


def run_fallback_compare(args, files: list[Path], out: Path) -> None:
    """Compare legacy baseline against alias-first + strict regex fallback."""
    all_rows = []
    details = []
    alias_candidate_rows = []
    strategies = (MAPPING_LEGACY, MAPPING_ALIAS_REGEX_FALLBACK)
    for path in files:
        strategy_results = {}
        for strategy in strategies:
            engine_results = {}
            for engine in ENGINES:
                pipe = _build_pipeline(engine, args, mapping_strategy=strategy)
                result = _mark(pipe.parse_file(path), engine=engine, strategy=strategy, mode=MODE_FALLBACK_COMPARE)
                engine_results[engine] = result
                write_integrated_bundle(out / strategy / engine, path, result)
                if args.collect_alias_candidates and strategy == MAPPING_ALIAS_REGEX_FALLBACK:
                    alias_candidate_rows.extend(_collect_regex_fallback_alias_candidates(result, path.name, engine))
            strategy_results[strategy] = engine_results

        item = {"source_name": path.name, "engines": {}}
        row = {"source_name": path.name}
        for engine in ENGINES:
            legacy = strategy_results[MAPPING_LEGACY][engine]
            fallback = strategy_results[MAPPING_ALIAS_REGEX_FALLBACK][engine]
            pw = pairwise("legacy", legacy, "fallback", fallback)
            legacy_n = _value_nodes(legacy)
            fallback_n = _value_nodes(fallback)
            item["engines"][engine] = {
                "legacy_value_nodes": legacy_n,
                "fallback_value_nodes": fallback_n,
                "fallback_delta": fallback_n - legacy_n,
                "legacy_vs_fallback": pw,
            }
            row[f"{engine}_legacy_nodes"] = legacy_n
            row[f"{engine}_fallback_nodes"] = fallback_n
            row[f"{engine}_fallback_delta"] = fallback_n - legacy_n
            row[f"{engine}_same"] = pw["same_value_nodes"]
            row[f"{engine}_different"] = pw["different_value_nodes"]
            row[f"{engine}_only_legacy"] = pw["only_legacy_value_nodes"]
            row[f"{engine}_only_fallback"] = pw["only_fallback_value_nodes"]
        details.append(item)
        all_rows.append(row)
        print(path.name + ": " + " | ".join(
            f"{e} {row[f'{e}_legacy_nodes']}->{row[f'{e}_fallback_nodes']} ({row[f'{e}_fallback_delta']:+d})"
            for e in ENGINES
        ))

    _dump(out / "fallback_comparison.json", details)
    _write_csv(out / "fallback_comparison.csv", all_rows)
    if args.collect_alias_candidates:
        _write_alias_candidates(out, alias_candidate_rows)


def main() -> None:
    args = build_parser().parse_args()
    files = _input_files(args.input)
    if not files:
        raise SystemExit("No .md/.txt files found")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    _dump(out / "run_manifest.json", _manifest(args, files, args.mode))

    if args.mode == MODE_MAPPING_COMPARE:
        run_mapping_compare(args, files, out)
    elif args.mode == MODE_FALLBACK_COMPARE:
        run_fallback_compare(args, files, out)
    elif args.mode == MODE_COMPARE:
        run_compare(args, files, out)
    else:
        run_single(args, args.mode, files, out)


if __name__ == "__main__":
    main()
