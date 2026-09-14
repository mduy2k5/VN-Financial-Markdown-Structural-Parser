from pathlib import Path
import json

from flat_parser.coverage_reporter import build_coverage_report
from flat_parser.pipeline import FlatParserPipeline

ROOT = Path(__file__).resolve().parents[1]


def pipe():
    return FlatParserPipeline(
        schema_path=ROOT/"resources/universal_financial_position_schema_v1_1.json",
        aliases_path=ROOT/"resources/universal_financial_position_aliases_v1_1.json",
        universal_guide_path=ROOT/"resources/universal_structural_guide_a1_a5.json",
    )


def test_unknown_label_has_normalized_classification_and_top_labels():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
Khoản mục thử nghiệm chưa có alias: 100
TỔNG TÀI SẢN
* 31/12/2025: 100
* 31/12/2024: 90
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
"""
    r=pipe().parse_text(raw, source_name="ZZZ.md")
    cov=r["debug"]["semantic_coverage"]
    assert cov["unknown_financial_labels"] >= 1
    assert any(x.get("normalized_label") for x in cov["unknown_examples"])
    assert any(x.get("classification") == "likely_alias_or_schema_gap" for x in cov["unknown_examples"])
    assert cov["unknown_top_labels"]


def test_batch_coverage_report_writes_json_and_csv(tmp_path):
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
Khoản mục thử nghiệm chưa có alias: 100
TỔNG TÀI SẢN
* 31/12/2025: 100
* 31/12/2024: 90
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
"""
    r=pipe().parse_text(raw, source_name="ZZZ.md")
    report=build_coverage_report([(Path("ZZZ.md"), r)], tmp_path, top_n=10)
    assert report["summary"]["files"] == 1
    assert (tmp_path/"coverage/coverage_summary.json").exists()
    assert (tmp_path/"coverage/coverage_summary.csv").exists()
    data=json.loads((tmp_path/"coverage/coverage_summary.json").read_text(encoding="utf-8"))
    assert data["files"][0]["ticker"] == "ZZZ"
