from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flat_parser.coverage_reporter import build_coverage_report
from flat_parser.pipeline import FlatParserPipeline


def main():
    ap = argparse.ArgumentParser(description="Parse a corpus and build v0.4.12.1 coverage diagnostics.")
    ap.add_argument("input")
    ap.add_argument("--output", default="output_flat_v0_4_12_1")
    ap.add_argument("--schema", default=str(ROOT / "resources/schemas/financial_position_schema.json"))
    ap.add_argument("--aliases", default=str(ROOT / "resources/schemas/financial_position_aliases.json"))
    ap.add_argument("--guide", default=str(ROOT / "resources/guides/compiled/structural_guide.json"))
    ap.add_argument("--top", type=int, default=100)
    args = ap.parse_args()

    inp = Path(args.input)
    files = [inp] if inp.is_file() else sorted(x for x in inp.rglob("*.md") if x.is_file())
    pipe = FlatParserPipeline(schema_path=args.schema, aliases_path=args.aliases, universal_guide_path=args.guide)
    results = []
    for path in files:
        result = pipe.parse_file(path)
        results.append((path, result))
        s = result["debug"]["stats"]
        print(f"{path.name}: coverage={s.get('semantic_label_coverage')} unknown={s.get('unknown_financial_labels')} statement={s.get('statement_health')}")
    report = build_coverage_report(results, args.output, top_n=max(1,args.top))
    print(Path(args.output) / "coverage" / "coverage_summary.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
