"""Scan Markdown financial reports and save fresh parser artifacts.

Every statement is parsed from the current Markdown corpus. Existing output,
comparison and ground-truth files are never used as parser input.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "md_reports"
DEFAULT_OUTPUT = ROOT / "output" / "demo" / "latest"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _source_files(input_dir: Path) -> list[Path]:
    return sorted(path for path in input_dir.rglob("*.md") if path.is_file())


def _ensure_output_is_outside_input(input_dir: Path, output_dir: Path) -> None:
    source_root = input_dir.resolve()
    candidate = output_dir.resolve()
    try:
        candidate.relative_to(source_root)
    except ValueError:
        return
    raise SystemExit(
        f"Output directory must be outside the Markdown input directory: {candidate}"
    )


def _run_pipeline(command: list[str], output_dir: Path) -> dict[str, Any]:
    log_path = output_dir / "scan.log"
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    log_path.write_text(
        (result.stdout or "") + ("\n[stderr]\n" + result.stderr if result.stderr else ""),
        encoding="utf-8",
    )
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "return_code": result.returncode,
        "command": [str(item) for item in command],
        "log": _relative(log_path),
        "stdout_tail": (result.stdout or "").strip().splitlines()[-5:],
        "stderr_tail": (result.stderr or "").strip().splitlines()[-5:],
    }


def _artifact_path(results_dir: Path, name: str | None) -> str | None:
    return _relative(results_dir / name) if name else None


def _snapshot(results_dir: Path, source_files: list[Path]) -> dict[str, Any]:
    summary_path = results_dir / "comparison_summary.json"
    if not summary_path.exists():
        raise SystemExit(f"Parser did not create summary: {summary_path}")

    rows = _load(summary_path)
    if not isinstance(rows, list):
        raise SystemExit(f"Invalid parser summary: {summary_path}")

    status = Counter(str(row.get("status") or "unknown") for row in rows)
    fp_status = Counter(str(row.get("financial_position_status") or "unknown") for row in rows)
    cf_status = Counter(str(row.get("cashflow_status") or "unknown") for row in rows)
    notes_status = Counter(str(row.get("notes_status") or "unknown") for row in rows)
    reports = []
    for row in rows:
        reports.append({
            "source_name": row.get("source_name"),
            "status": row.get("status"),
            "current_year": row.get("current_year"),
            "previous_year": row.get("previous_year"),
            "year_resolution": row.get("year_resolution"),
            "financial_position_status": row.get("financial_position_status"),
            "cashflow_status": row.get("cashflow_status"),
            "notes_status": row.get("notes_status"),
            "artifacts": {
                "comparison": _artifact_path(results_dir, row.get("comparison_file")),
                "financial_position": _artifact_path(results_dir, row.get("financial_position_canonical_file")),
                "income": _artifact_path(results_dir, row.get("canonical_file")),
                "cashflow": _artifact_path(results_dir, row.get("cashflow_canonical_file")),
                "notes_ir": _artifact_path(results_dir, row.get("notes_ir_file")),
                "notes_rows_csv": _artifact_path(results_dir, row.get("notes_rows_csv")),
            },
        })

    processed = {str(row.get("source_name")) for row in rows if row.get("source_name")}
    expected = {path.name for path in source_files}
    return {
        "source_reports": len(source_files),
        "processed_reports": len(rows),
        "missing_source_reports": sorted(expected - processed),
        "status_counts": dict(sorted(status.items())),
        "financial_position_status_counts": dict(sorted(fp_status.items())),
        "cashflow_status_counts": dict(sorted(cf_status.items())),
        "notes_status_counts": dict(sorted(notes_status.items())),
        "artifacts": {
            "summary_json": _relative(summary_path),
            "summary_csv": _relative(results_dir / "comparison_summary.csv"),
            "results_dir": _relative(results_dir),
        },
        "reports": reports,
    }


def _write_summary(path: Path, manifest: dict[str, Any]) -> None:
    scan = manifest["scan"]
    lines = [
        f"# Demo scan — {scan['source_reports']} báo cáo tài chính",
        "",
        f"Generated: `{manifest['generated_at_utc']}`",
        "",
        "Demo chỉ quét Markdown đầu vào; output cũ, comparison cũ và ground truth không được dùng làm parser input.",
        "",
        "## Kết quả lưu",
        "",
        f"- Input: `{scan['source_reports']}` báo cáo.",
        f"- Đã xử lý: `{scan['processed_reports']}` báo cáo.",
        f"- Trạng thái KQKD: `{scan['status_counts']}`.",
        f"- Trạng thái Bảng cân đối: `{scan['financial_position_status_counts']}`.",
        f"- Trạng thái LCTT: `{scan['cashflow_status_counts']}`.",
        f"- Trạng thái Thuyết minh: `{scan['notes_status_counts']}`.",
        "",
        "## Cấu trúc output",
        "",
        "- `<report>.comparison.json`: kết quả hợp nhất cho một báo cáo.",
        "- `<report>.financial_position.canonical.json`: Bảng cân đối kế toán.",
        "- `<report>.income.canonical.json`: Kết quả kinh doanh.",
        "- `<report>.cashflow.canonical.json`: Lưu chuyển tiền tệ.",
        "- `<report>.notes.ir.json` và `notes_rows/`: phần Thuyết minh, nếu được tìm thấy.",
        "- `scan_manifest.json`: chỉ mục artifact của toàn bộ báo cáo.",
    ]
    if scan["missing_source_reports"]:
        lines.extend(["", "## Cần rà soát", "", f"- Chưa có summary cho: `{scan['missing_source_reports']}`."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Folder of Markdown reports")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Folder for saved scan artifacts")
    parser.add_argument("--notes", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--current-year", type=int, default=None)
    parser.add_argument("--previous-year", type=int, default=None)
    args = parser.parse_args()

    input_dir = _resolve(args.input)
    output_dir = _resolve(args.output)

    if not input_dir.is_dir():
        raise SystemExit(f"Input folder not found: {input_dir}")
    _ensure_output_is_outside_input(input_dir, output_dir)

    source_files = _source_files(input_dir)
    if not source_files:
        raise SystemExit(f"No Markdown reports found: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    results_dir = output_dir / "results"
    command = [
        sys.executable,
        str(ROOT / "pipeline.py"),
        str(input_dir),
        "--output",
        str(results_dir),
        "--notes" if args.notes else "--no-notes",
    ]
    if args.current_year is not None:
        command.extend(["--current-year", str(args.current_year)])
    if args.previous_year is not None:
        command.extend(["--previous-year", str(args.previous_year)])
    run = _run_pipeline(command, output_dir)
    if run["status"] != "passed":
        raise SystemExit(f"Scan failed; see {output_dir / 'scan.log'}")

    scan = _snapshot(results_dir, source_files)
    manifest = {
        "schema_version": "financial_parser_scan_demo_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "input": _relative(input_dir),
        "notes_enabled": bool(args.notes),
        "run": run,
        "scan": scan,
    }
    manifest_path = output_dir / "scan_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_summary(output_dir / "scan_summary.md", manifest)

    print(json.dumps({
        "status": "passed",
        "output": _relative(output_dir),
        "input_reports": scan["source_reports"],
        "processed_reports": scan["processed_reports"],
        "manifest": _relative(manifest_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
