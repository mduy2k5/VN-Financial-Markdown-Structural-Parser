from __future__ import annotations

import argparse
from pathlib import Path

from .integrated_debug_writer import write_integrated_bundle
from .integrated_pipeline import IntegratedFinancialPipeline


def build_parser():
    p = argparse.ArgumentParser(
        description="Financial statement router + B02/financial-position + bank OFF_BALANCE integration."
    )
    p.add_argument("input", help="Markdown file or folder")
    p.add_argument("--output", default="output_flat_v0_5")
    p.add_argument("--financial-schema", default="resources/universal_financial_position_schema_v1_6.json")
    p.add_argument("--financial-aliases", default="resources/universal_financial_position_aliases_v1_6_1.json")
    p.add_argument("--off-balance-schema", default="resources/universal_off_balance_bank_schema_v1_3.json")
    p.add_argument("--off-balance-aliases", default="resources/universal_off_balance_bank_aliases_v1_3.json")
    p.add_argument("--income-schema", default="income_schema/resources/income_statement_schema.json")
    p.add_argument("--income-aliases", default="income_schema/resources/income_statement_aliases.json")
    p.add_argument("--guide", default="resources/universal_structural_guide_a1_a5.json")
    p.add_argument("--fuzzy", action="store_true")
    p.add_argument("--allow-unknown-structure", action="store_true")
    return p


def main():
    args = build_parser().parse_args()
    pipeline = IntegratedFinancialPipeline(
        financial_schema_path=args.financial_schema,
        financial_aliases_path=args.financial_aliases,
        universal_guide_path=args.guide,
        off_balance_schema_path=args.off_balance_schema,
        off_balance_aliases_path=args.off_balance_aliases,
        income_schema_path=args.income_schema,
        income_aliases_path=args.income_aliases,
        allow_fuzzy=args.fuzzy,
        allow_unknown_structure=args.allow_unknown_structure,
    )

    inp = Path(args.input)
    if inp.is_file():
        files = [inp]
    elif inp.is_dir():
        files = sorted(x for x in inp.rglob("*") if x.is_file() and x.suffix.lower() in {".md", ".txt"})
    else:
        raise SystemExit(f"Input not found: {inp}")
    if not files:
        raise SystemExit("No .md/.txt files found.")

    status_counts = {}
    for path in files:
        result = pipeline.parse_file(path)
        target = write_integrated_bundle(args.output, path, result)
        sector = (result.get("document_sector") or {}).get("sector")
        routed = []
        for r in result.get("routing", []):
            token = f"{r.get('statement_type')}={r.get('status')}"
            routed.append(token)
            status_counts[token] = status_counts.get(token, 0) + 1
        print(f"{path.name}: sector={sector} {' '.join(routed)} -> {target}")

    print("summary:")
    for k in sorted(status_counts):
        print(f"  {k}: {status_counts[k]}")


if __name__ == "__main__":
    main()
