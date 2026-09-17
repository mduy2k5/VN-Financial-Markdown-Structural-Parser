"""Audit persisted three-statement baselines against their Markdown evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


NUMERIC_LABEL = re.compile(r"^\(?-?\d[\d., ]*\)?$")
EXPLICIT_PERIOD_PAIR = re.compile(r"năm\s*nay.*năm\s*trước|năm\s*trước.*năm\s*nay", re.I)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _line(lines: list[str], number: Any) -> str:
    try:
        index = int(number) - 1
    except (TypeError, ValueError):
        return ""
    return lines[index] if 0 <= index < len(lines) else ""


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_file(path: Path, source_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    baseline = _load(path)
    source_path = source_dir / baseline["source_file"]
    source_exists = source_path.exists()
    lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if source_exists else []
    issues: list[dict[str, Any]] = []
    counts = Counter()

    if not source_exists:
        issues.append({"baseline": path.name, "statement": None, "row_id": None, "severity": "error", "issue": "source_missing"})
    elif _source_hash(source_path) != baseline.get("source_sha256"):
        issues.append({"baseline": path.name, "statement": None, "row_id": None, "severity": "error", "issue": "source_hash_mismatch"})

    for statement_name, statement in baseline.get("statements", {}).items():
        for row in statement.get("rows", []):
            row_issues: list[str] = []
            label = str(row.get("label") or "").strip()
            note = str(row.get("note") or "").strip()
            if label and NUMERIC_LABEL.fullmatch(label) and note:
                row_issues.append("label_looks_like_shifted_numeric_value")

            observations = row.get("observations") or []
            if not label and any(observation.get("value") is not None for observation in observations):
                row_issues.append("unlabeled_valued_row")
            for observation in observations:
                raw_text = str(observation.get("raw_text") or "")
                source_line = _line(lines, observation.get("source_line"))
                if source_exists and source_line.strip() != raw_text.strip():
                    row_issues.append("observation_source_line_mismatch")
                value_raw = str(observation.get("value_raw") or "")
                if value_raw and value_raw not in raw_text:
                    row_issues.append("observation_value_missing_from_raw_text")

            raw_texts = "\n".join(str(item.get("raw_text") or "") for item in observations)
            if EXPLICIT_PERIOD_PAIR.search(raw_texts) and len(observations) < 2:
                row_issues.append("explicit_current_previous_pair_underextracted")

            for issue in sorted(set(row_issues)):
                severity = "error" if issue in {
                    "label_looks_like_shifted_numeric_value",
                    "observation_source_line_mismatch",
                    "observation_value_missing_from_raw_text",
                } else "warning"
                issue_row = {
                    "baseline": path.name,
                    "source_file": baseline["source_file"],
                    "statement": statement_name,
                    "row_id": row.get("row_id"),
                    "source_line": row.get("source_line"),
                    "label": label,
                    "note": note,
                    "observation_count": len(observations),
                    "severity": severity,
                    "issue": issue,
                }
                issues.append(issue_row)
                counts[issue] += 1

    return {
        "baseline": path.name,
        "source_file": baseline["source_file"],
        "source_exists": source_exists,
        "source_hash_matches": source_exists and _source_hash(source_path) == baseline.get("source_sha256"),
        "statement_rows": {key: len(value.get("rows") or []) for key, value in baseline.get("statements", {}).items()},
        "issues": dict(sorted(counts.items())),
    }, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baselines", type=Path, default=Path("ground_truth/main_statements"))
    parser.add_argument("--source-dir", type=Path, default=Path("md_reports"))
    parser.add_argument("--output", type=Path, default=Path("ground_truth/main_statements_audit"))
    args = parser.parse_args()

    reports: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for path in sorted(args.baselines.glob("*.baseline.json")):
        report, found = audit_file(path, args.source_dir)
        reports.append(report)
        issues.extend(found)

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "financial_main_statement_baseline_audit_v1",
        "baseline_files": len(reports),
        "source_hash_matches": sum(bool(report["source_hash_matches"]) for report in reports),
        "issues": dict(sorted(Counter(item["issue"] for item in issues).items())),
        "reports": reports,
        "files": {"issues": "issues.csv"},
    }
    (args.output / "audit.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["baseline", "source_file", "statement", "row_id", "source_line", "label", "note", "observation_count", "severity", "issue"]
    with (args.output / "issues.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(issues)
    print(json.dumps({key: value for key, value in manifest.items() if key not in {"reports"}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
