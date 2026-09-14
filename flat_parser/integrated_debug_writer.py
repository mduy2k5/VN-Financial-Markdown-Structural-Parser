from __future__ import annotations

import json
from pathlib import Path


def dump_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_integrated_bundle(output_dir, input_path, result):
    output_dir = Path(output_dir)
    input_path = Path(input_path)
    stem = input_path.stem

    report_path = output_dir / "reports" / f"{stem}.financial_report.json"
    dump_json(report_path, result)

    scanner_dir = output_dir / "scanner"
    dump_json(scanner_dir / f"{stem}.statement_scanner.json", result.get("statement_scanner", {}))
    dump_json(scanner_dir / f"{stem}.routing.json", result.get("routing", []))

    for key, statement_result in (result.get("statements") or {}).items():
        statement_dir = output_dir / "statements" / key
        dump_json(statement_dir / f"{stem}.canonical.json", statement_result.get("canonical", {}))
        debug_dir = statement_dir / "debug"
        for dkey, value in (statement_result.get("debug") or {}).items():
            dump_json(debug_dir / f"{stem}.{dkey}.json", value)

    return report_path
