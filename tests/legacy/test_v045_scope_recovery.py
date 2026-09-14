from pathlib import Path

from flat_parser.context import financial_position_scope
from flat_parser.pipeline import FlatParserPipeline
from flat_parser.textnorm import normalize_lines


ROOT = Path(__file__).resolve().parents[1]


def make_pipeline():
    return FlatParserPipeline(
        schema_path=ROOT / "resources/universal_financial_position_schema_v1_1.json",
        aliases_path=ROOT / "resources/universal_financial_position_aliases_v1_1.json",
        universal_guide_path=ROOT / "resources/universal_structural_guide_a1_a5.json",
    )


def test_earliest_heading_is_rejected_when_it_has_tiny_scope():
    raw = """
# MỤC LỤC
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
B02/TCTD-HN
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT

# Page 8
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
tại ngày 31 tháng 12 năm 2025
B02/TCTD-HN

TÀI SẢN
* Tiền mặt
    * Số cuối năm: 100
    * Số đầu năm: 90
* Tiền gửi tại Ngân hàng Nhà nước
    * Số cuối năm: 200
    * Số đầu năm: 180

NỢ PHẢI TRẢ
* Tổng nợ phải trả
    * Số cuối năm: 250
    * Số đầu năm: 220

BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
Năm 2025
"""
    lines = normalize_lines(raw)
    start, end, debug = financial_position_scope(lines)

    real = [
        x.line_no for x in lines
        if x.clean == "BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT"
    ][1]

    assert start == real
    assert end > start + 5
    assert debug["health"] == "healthy"

    first = min(debug["candidates"], key=lambda x: x["line_no"])
    assert first["final_score"] < debug["candidates"][1]["final_score"]


def test_missing_statement_title_recovers_from_anchor_density():
    raw = """
# Page 4
TẬP ĐOÀN ABC
Tại ngày 31 tháng 12 năm 2025
Đơn vị tính: đồng

A - TÀI SẢN NGẮN HẠN | 100 | 1.000 | 900
Tiền và các khoản tương đương tiền | 110 | 300 | 250
Các khoản phải thu ngắn hạn | 130 | 400 | 350
Hàng tồn kho | 140 | 300 | 300
B - TÀI SẢN DÀI HẠN | 200 | 2.000 | 1.800
TỔNG CỘNG TÀI SẢN | 270 | 3.000 | 2.700
C - NỢ PHẢI TRẢ | 300 | 1.500 | 1.300
D - VỐN CHỦ SỞ HỮU | 400 | 1.500 | 1.400
TỔNG CỘNG NGUỒN VỐN | 440 | 3.000 | 2.700

BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
"""
    lines = normalize_lines(raw)
    start, end, debug = financial_position_scope(lines)

    assert debug["mode"] == "anchor_density_recovery"
    assert debug["health"] == "healthy"
    assert end > start + 5


def test_pipeline_flags_tiny_scope_instead_of_silent_zero_unresolved():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
"""
    result = make_pipeline().parse_text(raw, source_name="tiny.md")
    assert result["debug"]["stats"]["scope_health"] in {
        "critical_tiny_scope",
        "suspicious_small_scope",
    }


def test_dense_asset_region_before_repeated_mid_statement_title_wins():
    raw = """
Tại ngày 31 tháng 12 năm 2025
A - TÀI SẢN NGẮN HẠN | 100 | 1.000 | 900
Tiền và các khoản tương đương tiền | 110 | 300 | 250
Các khoản phải thu ngắn hạn | 130 | 400 | 350
Hàng tồn kho | 140 | 300 | 300
B - TÀI SẢN DÀI HẠN | 200 | 2.000 | 1.800
TỔNG CỘNG TÀI SẢN | 270 | 3.000 | 2.700

BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT (tiếp theo)
C - NỢ PHẢI TRẢ | 300 | 1.500 | 1.300
D - VỐN CHỦ SỞ HỮU | 400 | 1.500 | 1.400
TỔNG CỘNG NGUỒN VỐN | 440 | 3.000 | 2.700

BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
"""
    lines = normalize_lines(raw)
    start, end, debug = financial_position_scope(lines)
    repeated_title = next(
        x.line_no for x in lines
        if x.clean.startswith("BÁO CÁO TÌNH HÌNH TÀI CHÍNH")
    )
    assert start < repeated_title
    assert debug["mode"] == "anchor_density_prestart_recovery"


def test_statement_health_detects_partial_single_period_output():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Thuế và các khoản phải nộp Nhà nước: 100
* Phải trả người lao động: 90
* Chi phí phải trả ngắn hạn: 80
* Phải trả ngắn hạn khác: 70
* Vốn khác của chủ sở hữu: 60
"""
    result = make_pipeline().parse_text(raw, source_name="partial.md")
    assert result["debug"]["stats"]["statement_health"] in {
        "critical_missing_statement_totals",
        "suspicious_single_period_only",
    }
