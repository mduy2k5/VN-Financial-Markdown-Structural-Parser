from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .abc_compare import compare_three
from .bullet_mapped_pipeline import BulletMappedPipeline
from .flow_mapped_pipeline import FlowMappedPipeline
from .integrated_debug_writer import write_integrated_bundle
from .integrated_pipeline import IntegratedFinancialPipeline


def _dump(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser():
    p = argparse.ArgumentParser(description="A/B/C runner: v0.5 vs flat-row P1-P34 flow vs hybrid")
    p.add_argument("input", help="Markdown file or folder")
    p.add_argument("--output", default="output_abc_v051")
    p.add_argument(
        "--engine",
        choices=["v05", "flow", "hybrid"],
        default="hybrid",
        help="Run one engine only. v05=original 0.5, flow=flat-row P1-P34+mapping, hybrid=v0.5+safe fill.",
    )
    p.add_argument("--compare-all", action="store_true", help="Run all 3 engines and write three-way comparison")
    # backwards compatibility
    p.add_argument("--compare", action="store_true", help="Alias of --compare-all")
    p.add_argument("--financial-schema", default="resources/universal_financial_position_schema_v1_6.json")
    p.add_argument("--financial-aliases", default="resources/universal_financial_position_aliases_v1_6_1.json")
    p.add_argument("--off-balance-schema", default="resources/universal_off_balance_bank_schema_v1_3.json")
    p.add_argument("--off-balance-aliases", default="resources/universal_off_balance_bank_aliases_v1_3.json")
    p.add_argument("--guide", default="resources/universal_structural_guide_a1_a5.json")
    p.add_argument("--fuzzy", action="store_true")
    p.add_argument("--allow-unknown-structure", action="store_true")
    return p


def _files(inp):
    inp = Path(inp)
    if inp.is_file():
        return [inp]
    if inp.is_dir():
        return sorted(x for x in inp.rglob("*") if x.is_file() and x.suffix.lower() in {".md", ".txt"})
    raise SystemExit(f"Input not found: {inp}")


def _hybrid(args):
    return BulletMappedPipeline(
        financial_schema_path=args.financial_schema,
        financial_aliases_path=args.financial_aliases,
        universal_guide_path=args.guide,
        off_balance_schema_path=args.off_balance_schema,
        off_balance_aliases_path=args.off_balance_aliases,
        allow_fuzzy=args.fuzzy,
        allow_unknown_structure=args.allow_unknown_structure,
    )


def _flow(args):
    return FlowMappedPipeline(
        financial_schema_path=args.financial_schema,
        financial_aliases_path=args.financial_aliases,
        universal_guide_path=args.guide,
        off_balance_schema_path=args.off_balance_schema,
        off_balance_aliases_path=args.off_balance_aliases,
        allow_fuzzy=args.fuzzy,
        allow_unknown_structure=args.allow_unknown_structure,
    )


def _v05(args):
    return IntegratedFinancialPipeline(
        financial_schema_path=args.financial_schema,
        financial_aliases_path=args.financial_aliases,
        universal_guide_path=args.guide,
        off_balance_schema_path=args.off_balance_schema,
        off_balance_aliases_path=args.off_balance_aliases,
        allow_fuzzy=args.fuzzy,
        allow_unknown_structure=args.allow_unknown_structure,
    )


def _summary_row(source_name, comp):
    fp = comp["financial_position"]
    r = {
        "source_name": source_name,
        "v05_value_nodes": fp["v05"]["value_nodes"],
        "flow_value_nodes": fp["flow"]["value_nodes"],
        "hybrid_value_nodes": fp["hybrid"]["value_nodes"],
    }
    for key, val in fp["pairwise"].items():
        r[f"{key}_same"] = val["same_value_nodes"]
        r[f"{key}_different"] = val["different_value_nodes"]
        for k2, v2 in val.items():
            if k2.startswith("only_") and k2.endswith("_value_nodes"):
                r[f"{key}_{k2}"] = v2
    return r


def _write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    args = build_parser().parse_args()
    compare_all = args.compare_all or args.compare
    files = _files(args.input)
    if not files:
        raise SystemExit("No .md/.txt files found")

    out = Path(args.output)
    v05_pipe = _v05(args) if (compare_all or args.engine == "v05") else None
    flow_pipe = _flow(args) if (compare_all or args.engine == "flow") else None
    hybrid_pipe = _hybrid(args) if (compare_all or args.engine == "hybrid") else None
    summaries = []
    csv_rows = []

    for path in files:
        if compare_all:
            vr = v05_pipe.parse_file(path)
            fr = flow_pipe.parse_file(path)
            hr = hybrid_pipe.parse_file(path)
            write_integrated_bundle(out / "v05", path, vr)
            write_integrated_bundle(out / "flow", path, fr)
            write_integrated_bundle(out / "hybrid", path, hr)
            comp = compare_three(vr, fr, hr)
            comp.update({"source_name": path.name})
            _dump(out / "comparison" / f"{path.stem}.comparison.json", comp)
            summaries.append(comp)
            csv_rows.append(_summary_row(path.name, comp))
            fp = comp["financial_position"]
            print(
                f"{path.name}: v05={fp['v05']['value_nodes']} | "
                f"flow={fp['flow']['value_nodes']} | hybrid={fp['hybrid']['value_nodes']} | "
                f"v05-flow diff={fp['pairwise']['v05_vs_flow']['different_value_nodes']} | "
                f"v05-hybrid diff={fp['pairwise']['v05_vs_hybrid']['different_value_nodes']}"
            )
        else:
            if args.engine == "v05":
                result = v05_pipe.parse_file(path)
            elif args.engine == "flow":
                result = flow_pipe.parse_file(path)
            else:
                result = hybrid_pipe.parse_file(path)
            write_integrated_bundle(out / args.engine, path, result)
            print(f"{path.name}: {args.engine} -> {out/args.engine}")

    if compare_all:
        _dump(out / "comparison_summary.json", summaries)
        _write_csv(out / "comparison_summary.csv", csv_rows)


if __name__ == "__main__":
    main()
