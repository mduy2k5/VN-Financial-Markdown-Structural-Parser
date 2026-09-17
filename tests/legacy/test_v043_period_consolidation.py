from pathlib import Path
from flat_parser.pipeline import FlatParserPipeline

ROOT = Path(__file__).resolve().parents[2]

def make_pipeline():
    return FlatParserPipeline(
        schema_path=ROOT/"resources/schemas/financial_position_schema.json",
        aliases_path=ROOT/"resources/schemas/financial_position_aliases.json",
        universal_guide_path=ROOT/"resources/guides/compiled/structural_guide.json",
    )

def node_map(doc):
    return {x["node_id"]: x for x in doc["nodes"]}

def test_period_context_ignores_2026_signature_date():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
tại ngày 31 tháng 12 năm 2025
Năm 2025
Năm 2024
Ngày ký báo cáo: 24 tháng 2 năm 2026

* Tổng nợ phải trả
    * Năm 2025: 100
    * Năm 2024: 90
"""
    result = make_pipeline().parse_text(raw)
    n = node_map(result["canonical"])["TOTAL_LIABILITIES"]
    assert n["value"]["current"] == "100"
    assert n["value"]["previous"] == "90"

def test_prefix_normalizer_dual_role():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* C - NỢ PHẢI TRẢ
    * Số cuối năm: 300
    * Số đầu năm: 250

* D - VỐN CHỦ SỞ HỮU
    * Số cuối năm: 200
    * Số đầu năm: 180
"""
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result["canonical"])
    assert nodes["TOTAL_LIABILITIES"]["value"]["current"] == "300"
    assert nodes["TOTAL_EQUITY"]["value"]["current"] == "200"

def test_repeated_label_rows_merge_to_two_periods():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Tiền gửi và cho vay các TCTD khác
    * Tiền gửi tại các TCTD khác: 25.819.775
    * Tiền gửi tại các TCTD khác: 12.454.527
"""
    result = make_pipeline().parse_text(raw)
    n = node_map(result["canonical"])["ASSET.INTERBANK.DEPOSITS"]
    assert n["value"]["current"] == "25.819.775"
    assert n["value"]["previous"] == "12.454.527"

def test_dash_is_preserved_as_raw_value():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Dự phòng rủi ro tiền gửi và cho vay các tổ chức tín dụng khác
    * Năm 2025: -
    * Năm 2024: (50.000)
"""
    result = make_pipeline().parse_text(raw)
    n = node_map(result["canonical"])["ASSET.INTERBANK.ALLOWANCE"]
    assert n["value"]["current"] == "-"
    assert n["value"]["previous"] == "(50.000)"


def test_dual_role_wrapper_chi_tieu_children():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

**C - NỢ PHẢI TRẢ**
* Chỉ tiêu: 300
    * Số cuối năm: 2.297.846
    * Số đầu năm: 2.068.623
"""
    result = make_pipeline().parse_text(raw)
    n = node_map(result["canonical"])["TOTAL_LIABILITIES"]
    assert n["value"]["current"] == "2.297.846"
    assert n["value"]["previous"] == "2.068.623"


def test_repeated_note_key_children_are_positional_values():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Tiền gửi tại NHNN
    * 5.2: 1.219.788
    * 5.2: 798.225
"""
    result = make_pipeline().parse_text(raw)
    n = node_map(result["canonical"])["ASSET.CENTRAL_BANK_BALANCES"]
    assert n["value"]["current"] == "1.219.788"
    assert n["value"]["previous"] == "798.225"
    assert n["value"]["note"] == "5.2"


def test_value_only_children_with_unit_are_positional():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Tổng tài sản Có:
    * 195.820.302 (Triệu VND)
    * 165.486.693 (Triệu VND)
"""
    result = make_pipeline().parse_text(raw)
    n = node_map(result["canonical"])["TOTAL_ASSETS"]
    assert n["value"]["current"] == "195.820.302"
    assert n["value"]["previous"] == "165.486.693"
