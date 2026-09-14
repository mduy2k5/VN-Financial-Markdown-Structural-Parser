from __future__ import annotations

import json
from pathlib import Path


def dump_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_result_bundle(output_dir, input_path, result):
    output_dir = Path(output_dir)
    input_path = Path(input_path)
    stem = input_path.stem

    canonical_path = output_dir / f"{stem}.canonical.json"
    dump_json(canonical_path, result["canonical"])

    debug = result["debug"]
    debug_dir = output_dir / "debug"
    for key, value in debug.items():
        dump_json(debug_dir / f"{stem}.{key}.json", value)

    return canonical_path
