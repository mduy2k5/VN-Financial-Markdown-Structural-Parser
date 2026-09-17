import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.b01_financial_position import (
    FinancialPositionIndex,
    integrate_financial_position,
)
from src.notes.structural_parser import parse_bullet_structures
from src.common.source_canonical_hydrator import augment_canonical_with_recovered_rows


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "md_reports" / "ABB_BCTC_2025_hop_nhat_kiem_toan.md"


def _run_pipeline(source: Path, output: Path) -> tuple[subprocess.CompletedProcess, dict]:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "pipeline.py"),
            str(source),
            "--mode",
            "source-only",
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
    assert result.returncode == 0, result.stdout + result.stderr
    rows = json.loads((output / "comparison_summary.json").read_text(encoding="utf-8-sig"))
    assert len(rows) == 1
    return result, rows[0]


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

    result, row = _run_pipeline(source, output)

    assert "mode=source-only source=markdown" in result.stdout
    assert "canonical_sources=" not in result.stdout
    assert row["run_mode"] == "source-only"
    assert row["financial_position_source_mode"] == "source_parse"
    assert row["financial_position_preserved"] is False
    assert row["financial_position_value_nodes"] > 0

    canonical = json.loads(stale.read_text(encoding="utf-8-sig"))
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert canonical["source_name"] == source.name
    assert canonical["source_sha256"] == expected_hash
    assert canonical["provenance"]["source_sha256"] == expected_hash
    comparison = json.loads(stale_comparison.read_text(encoding="utf-8-sig"))
    assert comparison.get("poison") is None
    assert comparison["run_mode"] == "source-only"
    assert comparison["financial_position"]["v05"]["parser"]["integration_mode"] == "source_parse"
    assert not (output / "removed_report.income.canonical.json").exists()
    assert not (stale_rows / "removed_report.notes_rows.csv").exists()
    assert not (stale_rows / "removed_report.notes_rows.json").exists()


def test_source_only_is_stable_when_reusing_the_same_output_directory(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / SOURCE.name
    shutil.copy2(SOURCE, source)
    output = tmp_path / "output"

    first_log, first = _run_pipeline(source, output)
    second_log, second = _run_pipeline(source, output)

    assert "canonical_sources=" not in first_log.stdout
    assert "canonical_sources=" not in second_log.stdout
    for key in (
        "source_sha256",
        "run_mode",
        "financial_position_status",
        "financial_position_value_nodes",
        "income_value_nodes",
        "cashflow_value_nodes",
    ):
        assert second[key] == first[key]


def test_missing_b01_cannot_restore_metrics_from_old_comparison(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    index = FinancialPositionIndex.build([empty])
    old_comparison = {
        "financial_position": {
            "canonical_file": "old.financial_position.canonical.json",
            "v05": {"status": "ok", "value_nodes": 999},
        }
    }

    result = integrate_financial_position(
        "ABB_BCTC_2025_hop_nhat_kiem_toan",
        tmp_path / "out",
        index,
        existing_comparison=old_comparison,
    )

    assert result["status"] == "financial_position_source_missing"
    assert result["metrics"]["value_nodes"] == 0
    assert result["canonical"] is None
    assert result["canonical_file"] is None
    assert result["preserved_legacy"] is False


def test_unverified_and_ambiguous_b01_artifacts_are_not_selected(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    base = "ABB_BCTC_2025_hop_nhat_kiem_toan"
    path = artifact_dir / f"{base}.financial_position.canonical.json"
    minimal = {
        "schema_id": "UNIVERSAL_FINANCIAL_POSITION_V1",
        "schema_version": "1.6.0",
        "statement_type": "FINANCIAL_POSITION",
        "nodes": [],
    }
    path.write_text(json.dumps(minimal), encoding="utf-8")
    assert FinancialPositionIndex.build([artifact_dir]).find(base) is None

    source_hash = "a" * 64
    minimal.update({"source_name": f"{base}.md", "source_sha256": source_hash})
    path.write_text(json.dumps(minimal), encoding="utf-8")
    index = FinancialPositionIndex.build([artifact_dir])
    assert index.find(base) == path

    duplicate_dir = tmp_path / "duplicate"
    duplicate_dir.mkdir()
    duplicate = duplicate_dir / path.name
    duplicate.write_text(json.dumps(minimal), encoding="utf-8")
    index = FinancialPositionIndex.build([artifact_dir, duplicate_dir])
    assert base in index.duplicates
    with pytest.raises(ValueError, match="Multiple valid"):
        index.find(base)


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
