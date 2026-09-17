import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from src.notes.structural_parser import parse_bullet_structures
from src.common.source_canonical_hydrator import augment_canonical_with_recovered_rows


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "md_reports" / "ABB_BCTC_2025_hop_nhat_kiem_toan.md"


def _run_pipeline(
    source: Path,
    output: Path,
    *,
    audit: bool = False,
    notes: bool = False,
) -> tuple[subprocess.CompletedProcess, dict, dict]:
    command = [
        sys.executable,
        str(ROOT / "app" / "pipeline.py"),
        str(source),
        "--output",
        str(output),
    ]
    command.append("--notes" if notes else "--no-notes")
    if audit:
        command.append("--audit")
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["report_count"] == 1
    report_entry = manifest["reports"][0]
    report = json.loads(
        (output / report_entry["path"]).read_text(encoding="utf-8-sig")
    )
    statements = report["statements"]
    row = {
        "source_sha256": report["report"]["source_sha256"],
        "financial_position_status": statements["financial_position"]["status"],
        "financial_position_value_nodes": statements["financial_position"]["summary"]["node_count"],
        "income_value_nodes": statements["income_statement"]["summary"]["node_count"],
        "cashflow_value_nodes": statements["cash_flow"]["summary"]["node_count"],
    }
    return result, row, report


def test_source_only_ignores_previous_output_and_writes_provenance(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / SOURCE.name
    shutil.copy2(SOURCE, source)
    output = tmp_path / "output"
    output.mkdir()

    stale = output / f"{source.stem}.financial_position.canonical.json"
    stale.write_text(json.dumps({"poison": True}), encoding="utf-8")
    stale_comparison = output / f"{source.stem}.comparison.json"
    stale_comparison.write_text(
        json.dumps({"poison": True, "financial_position": {"v05": {"value_nodes": 999}}}),
        encoding="utf-8",
    )
    stale_rows = output / "notes_rows"
    stale_rows.mkdir()
    (stale_rows / "removed_report.notes_rows.csv").write_text("stale\n", encoding="utf-8")
    (stale_rows / "removed_report.notes_rows.json").write_text("{}", encoding="utf-8")
    (output / "removed_report.income.canonical.json").write_text("{}", encoding="utf-8")

    result, row, report = _run_pipeline(source, output)

    assert "[FINANCIAL_POSITION] source=markdown" in result.stdout
    assert "canonical_sources=" not in result.stdout
    assert "run_mode" not in row
    assert "financial_position_source_mode" not in row
    assert "financial_position_preserved" not in row
    assert row["financial_position_value_nodes"] > 0

    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["report"]["source_name"] == source.name
    assert report["report"]["source_sha256"] == expected_hash
    assert report["quality"]["status"] in {"ok", "review_required"}
    assert not stale.exists()
    assert not stale_comparison.exists()
    assert not (output / "comparison_summary.json").exists()
    assert not (output / "comparison_summary.csv").exists()
    assert (output / "manifest.json").exists()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    report_path = output / manifest["reports"][0]["path"]
    assert report_path.exists()
    assert source.stem in report_path.name
    assert not (output / "removed_report.income.canonical.json").exists()
    assert not (stale_rows / "removed_report.notes_rows.csv").exists()
    assert not (stale_rows / "removed_report.notes_rows.json").exists()


def test_source_only_is_stable_when_reusing_the_same_output_directory(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / SOURCE.name
    shutil.copy2(SOURCE, source)
    output = tmp_path / "output"

    first_log, first, _ = _run_pipeline(source, output)
    second_log, second, _ = _run_pipeline(source, output)

    assert "canonical_sources=" not in first_log.stdout
    assert "canonical_sources=" not in second_log.stdout
    for key in (
        "source_sha256",
        "financial_position_status",
        "financial_position_value_nodes",
        "income_value_nodes",
        "cashflow_value_nodes",
    ):
        assert second[key] == first[key]


def test_audit_artifacts_are_opt_in(tmp_path):
    output = tmp_path / "output"

    _, _, report = _run_pipeline(SOURCE, output, audit=True)

    audit = output / "audit"
    assert (audit / "run_metadata.json").exists()
    assert (audit / f"{SOURCE.stem}.comparison.json").exists()
    assert (audit / f"{SOURCE.stem}.financial_position.canonical.json").exists()
    assert report["report"]["source_name"] == SOURCE.name


def test_production_report_has_stable_native_contract(tmp_path):
    output = tmp_path / "output"

    _, _, report = _run_pipeline(SOURCE, output, notes=True)

    assert set(report) == {
        "output_schema",
        "report",
        "periods",
        "sector",
        "statements",
        "notes",
        "quality",
    }
    assert report["output_schema"] == {
        "name": "vn_financial_report_output",
        "version": "1.0.0",
    }
    assert report["notes"]["status"] == "parsed"
    assert report["notes"]["rows"]
    first_row = report["notes"]["rows"][0]
    assert isinstance(first_row["values"], list)
    assert isinstance(first_row["raw_cells"], list)
    assert isinstance(first_row["linked_targets"], list)
    for statement in report["statements"].values():
        assert "diagnostics" not in statement
        assert "reconciled_source_view" not in statement
        for node in statement["nodes"] + statement["observations"]:
            assert isinstance(node["value"]["current"], (int, float, type(None)))
            assert isinstance(node["value"]["previous"], (int, float, type(None)))


def test_output_inside_markdown_input_is_rejected(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / SOURCE.name
    shutil.copy2(SOURCE, source)
    output = input_dir / "generated"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "app" / "pipeline.py"),
            str(input_dir),
            "--output",
            str(output),
            "--no-notes",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode != 0
    assert "outside the Markdown input directory" in result.stderr
    assert not output.exists()


def test_notes_period_roles_use_requested_years():
    text = """
* 31/12/2026:
    * Tiền mặt: 100 đồng
* 31/12/2025:
    * Tiền mặt: 90 đồng
"""
    blocks = parse_bullet_structures(
        text,
        1,
        "TEST",
        current_year=2026,
        previous_year=2025,
    )
    rows = [row for block in blocks for row in block.rows]
    assert rows
    roles = {
        value.period_role
        for row in rows
        for value in row.values
    }
    assert roles == {"current", "previous"}


def test_recovered_generic_period_labels_keep_distinct_financial_position_contexts():
    canonical = {"unit": "vnd", "nodes": []}
    rows = [
        SimpleNamespace(
            label="Năm hiện tại", current=10, previous=9, code=None, note=None,
            section=None, source_line=10, pattern="test", parent_label="Tiền", hierarchy_path="Tài sản > Tiền",
            unit="vnd", unit_source="test",
        ),
        SimpleNamespace(
            label="Năm hiện tại", current=20, previous=19, code=None, note=None,
            section=None, source_line=20, pattern="test", parent_label="Đầu tư", hierarchy_path="Tài sản > Đầu tư",
            unit="vnd", unit_source="test",
        ),
    ]
    augment_canonical_with_recovered_rows(canonical, rows, "FINANCIAL_POSITION")
    source = [node for node in canonical["nodes"] if node.get("kind") == "source_observation"]
    assert len(source) == 2
    assert {node["value"]["current"] for node in source} == {10, 20}
