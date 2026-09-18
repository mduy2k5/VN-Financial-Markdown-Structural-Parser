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
        "source_sha256": report["report"]["source"]["sha256"],
        "financial_position_status": statements["financial_position"]["status"],
        "financial_position_value_nodes": statements["financial_position"]["summary"]["counts"]["valued_items"],
        "income_value_nodes": statements["income_statement"]["summary"]["counts"]["valued_items"],
        "cashflow_value_nodes": statements["cash_flow"]["summary"]["counts"]["valued_items"],
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
    assert report["report"]["source"]["name"] == source.name
    assert report["report"]["source"]["sha256"] == expected_hash
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
    assert report["report"]["source"]["name"] == SOURCE.name


def test_production_report_has_stable_native_contract(tmp_path):
    output = tmp_path / "output"

    _, _, report = _run_pipeline(SOURCE, output, notes=True)

    assert set(report) == {
        "contract",
        "report",
        "periods",
        "statements",
        "notes",
        "quality",
    }
    assert report["contract"] == {
        "name": "vn_financial_report_output",
        "version": "2.0.0",
    }
    assert set(report["report"]) == {"id", "source"}
    assert set(report["report"]["source"]) == {"name", "sha256"}
    assert report["notes"]["status"] == "parsed"
    assert report["notes"]["rows"]
    first_row = report["notes"]["rows"][0]
    assert isinstance(first_row["values"], list)
    assert isinstance(first_row["source"]["raw_cells"], list)
    assert isinstance(first_row["links"], list)
    required_statement_keys = {
        "status", "statement_type", "schema", "context", "items",
        "observations", "summary", "validation",
    }
    required_record_keys = {
        "record_type", "id", "source_id", "label", "attributes", "value", "provenance",
    }
    required_value_keys = {
        "current", "previous", "additional", "note", "unit", "raw_text", "raw_values",
    }
    required_provenance_keys = {"evidence", "mapping"}
    for statement in report["statements"].values():
        assert set(statement) == required_statement_keys
        assert "diagnostics" not in statement
        assert "reconciled_source_view" not in statement
        for node in statement["items"] + statement["observations"]:
            assert set(node) == required_record_keys
            assert set(node["value"]) == required_value_keys
            assert set(node["provenance"]) == required_provenance_keys
            assert isinstance(node["value"]["current"], (int, float, type(None)))
            assert isinstance(node["value"]["previous"], (int, float, type(None)))
            assert isinstance(node["value"]["raw_values"], dict)
        assert all(node["record_type"] == "semantic_item" for node in statement["items"])
        assert all(node["record_type"] == "source_observation" for node in statement["observations"])


def test_inline_cashflow_source_observations_expose_semantic_links(tmp_path):
    output = tmp_path / "output"

    _, _, report = _run_pipeline(SOURCE, output, audit=True, notes=False)
    observations = {
        observation["label"]: observation
        for observation in report["statements"]["cash_flow"]["observations"]
    }
    expected = {
        "Chênh lệch số tiền thực thu từ hoạt động kinh doanh chứng khoán, vàng bạc, ngoại tệ",
        "Thu nhập (chi phí) khác",
        "Tiền thu các khoản nợ đã được xử lý xoá, bù đắp bằng nguồn dự phòng rủi ro",
        "Tiền thuế thu nhập thực nộp trong năm",
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh trước những thay đổi về tài sản và nợ phải trả hoạt động",
    }
    assert expected <= observations.keys()
    for label in expected:
        mapping = observations[label]["provenance"]["mapping"]
        assert mapping["status"] == "mapped"
        assert mapping["target_id"].startswith("CASHFLOW.BANK.DIRECT.")
        assert mapping["method"] == "source_evidence_link"

    semantic = {
        node["label"]: node
        for node in report["statements"]["cash_flow"]["items"]
    }
    for label in (
        "Thu nhập lãi và các khoản thu nhập tương tự nhận được",
        "Chi phí lãi và các chi phí tương tự đã trả",
        "Thu nhập từ hoạt động dịch vụ nhận được",
        "Thu nhập khác",
        "Tiền chi trả cho nhân viên và hoạt động quản lý, công vụ",
        "Tiền thuế thu nhập thực nộp trong kỳ",
    ):
        mapping = semantic[label]["provenance"]["mapping"]
        assert mapping["status"] == "mapped"
        assert mapping["target_id"].startswith("CASHFLOW.BANK.DIRECT.")

    interest = semantic["Thu nhập lãi và các khoản thu nhập tương tự nhận được"]
    assert "12.919.243" in interest["value"]["raw_text"]
    assert "Năm trước" in interest["value"]["raw_text"]
    assert interest["provenance"]["evidence"][0]["raw_text"] == interest["value"]["raw_text"]

    audit = json.loads(
        (output / "audit" / f"{SOURCE.stem}.cashflow.canonical.json").read_text(encoding="utf-8-sig")
    )
    audit_node = next(
        node for node in audit["nodes"]
        if node.get("node_id") == "CASHFLOW.BANK.DIRECT.INTEREST_RECEIVED"
    )
    assert audit_node["mapping"]["status"] == "mapped"
    assert audit_node["mapping"]["mapped_node_id"] == audit_node["node_id"]
    assert "12.919.243" in audit_node["value"]["raw_text"]


def test_abb_income_pipe_table_is_fully_mapped_with_source_provenance(tmp_path):
    output = tmp_path / "output"

    _, _, report = _run_pipeline(SOURCE, output, audit=True, notes=False)
    statement = report["statements"]["income_statement"]
    expected = {
        "Thu nhập lãi và các khoản thu nhập tương tự": (790, 13604093, 9027696),
        "Chi phí lãi và các chi phí tương tự": (791, -8515301, -5992439),
        "Thu nhập lãi thuần": (792, 5088792, 3035257),
        "Thu nhập từ hoạt động dịch vụ": (793, 698131, 879352),
        "Chi phí hoạt động dịch vụ": (794, -437584, -379603),
        "Lãi thuần từ hoạt động dịch vụ": (795, 260547, 499749),
        "Lãi thuần từ hoạt động kinh doanh ngoại hối": (796, -1546, 245756),
        "Lãi thuần từ mua bán chứng khoán kinh doanh": (797, 2007, 3385),
        "(Lỗ)/lãi thuần từ mua bán chứng khoán đầu tư": (798, -104237, 109475),
        "Thu nhập từ hoạt động khác": (799, 3460511, 646787),
        "Chi phí hoạt động khác": (800, -156111, -31152),
        "Lãi thuần từ hoạt động khác": (801, 3304400, 615635),
        "Thu nhập từ góp vốn, mua cổ phần": (802, 15314, 11296),
        "TỔNG THU NHẬP HOẠT ĐỘNG": (803, 8565277, 4520553),
        "TỔNG CHI PHÍ HOẠT ĐỘNG": (804, -2999921, -2364544),
        "Lợi nhuận thuần từ hoạt động kinh doanh trước chi phí dự phòng rủi ro tín dụng": (
            805,
            5565356,
            2156009,
        ),
        "Chi phí dự phòng rủi ro tín dụng": (806, -2024645, -1411791),
        "TỔNG LỢI NHUẬN TRƯỚC THUẾ": (807, 3540711, 744218),
        "Chi phí thuế thu nhập doanh nghiệp hiện hành": (808, -765983, -169720),
        "Thu nhập thuế thu nhập doanh nghiệp hoãn lại": (809, 33898, 11058),
        "Tổng chi phí thuế thu nhập doanh nghiệp": (810, -732085, -158662),
        "LỢI NHUẬN SAU THUẾ": (811, 2808626, 585556),
        "Lãi cơ bản trên cổ phiếu (đồng/cổ phiếu)": (812, 2714, 535),
    }

    mapping_summary = statement["summary"]["mapping"]
    assert mapping_summary["input_rows"] == len(expected)
    assert mapping_summary["mapped_rows"] == len(expected)
    assert mapping_summary["unmapped_rows"] == 0

    valued = [
        item
        for item in statement["items"]
        if item["value"]["current"] is not None
        or item["value"]["previous"] is not None
    ]
    assert len(valued) == len(expected)
    by_source_label = {
        item["provenance"]["evidence"][0]["source_label"]: item
        for item in valued
    }
    assert set(by_source_label) == set(expected)

    for source_label, (line, current, previous) in expected.items():
        item = by_source_label[source_label]
        evidence = item["provenance"]["evidence"][0]
        assert evidence["source_line"] == line
        assert item["value"]["current"] == current
        assert item["value"]["previous"] == previous
        assert item["value"]["raw_text"] == evidence["raw_text"]
        assert source_label in item["value"]["raw_text"]
        assert "|" in item["value"]["raw_text"]


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
