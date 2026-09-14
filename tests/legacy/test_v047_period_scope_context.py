from pathlib import Path

from flat_parser.context import financial_position_scope
from flat_parser.pipeline import FlatParserPipeline
from flat_parser.textnorm import normalize_lines, strip_inline_financial_metadata

ROOT = Path(__file__).resolve().parents[1]

def make_pipeline():
    return FlatParserPipeline(
        schema_path=ROOT / "resources/universal_financial_position_schema_v1_1.json",
        aliases_path=ROOT / "resources/universal_financial_position_aliases_v1_1.json",
        universal_guide_path=ROOT / "resources/universal_structural_guide_a1_a5.json",
    )

def node_map(doc):
    return {n["node_id"]: n for n in doc["nodes"]}

def test_audit_bullet_is_not_statement_title():
    raw = """
BÁO CÁO KIỂM TOÁN ĐỘC LẬP
Chúng tôi đã kiểm toán, bao gồm:
* Bảng cân đối kế toán hợp nhất tại ngày 31 tháng 12 năm 2025
* Báo cáo kết quả hoạt động kinh doanh hợp nhất

BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
* TỔNG CỘNG TÀI SẢN
    * Số cuối năm: 100
    * Số đầu năm: 90
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT
"""
    lines = normalize_lines(raw)
    start, end, debug = financial_position_scope(lines)
    selected = next(x.clean for x in lines if x.line_no == start)
    assert selected == "BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT"
    assert end > start

def test_regulation_2014_does_not_override_reporting_year_2025():
    raw = """
Mẫu số: B02/TCTD-HN
(Ban hành theo Thông tư số 49/2014/TT-NHNN ngày 31/12/2014)
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
* TỔNG TÀI SẢN
    * 31/12/2025 Triệu VND: 505.901.570
    * 31/12/2024 Triệu VND: 418.028.391
"""
    result = make_pipeline().parse_text(raw)
    total = node_map(result["canonical"])["TOTAL_ASSETS"]
    assert total["value"]["current"] == "505.901.570"
    assert total["value"]["previous"] == "418.028.391"

def test_opening_date_same_year_is_previous():
    raw = """
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
| TÀI SẢN | 31/12/2025 (VND) | 01/01/2025 (VND) |
| --- | --- | --- |
| TỔNG CỘNG TÀI SẢN | 100 | 90 |
"""
    result = make_pipeline().parse_text(raw)
    total = node_map(result["canonical"])["TOTAL_ASSETS"]
    assert total["value"]["current"] == "100"
    assert total["value"]["previous"] == "90"

def test_parenthetical_code_and_note_are_semantic_metadata():
    assert strip_inline_financial_metadata("Tài sản cố định hữu hình (221)") == "Tài sản cố định hữu hình"
    assert strip_inline_financial_metadata("Tài sản cố định hữu hình (thuyết minh 13)") == "Tài sản cố định hữu hình"

def test_generic_cost_uses_actual_fixed_asset_parent():
    raw = """
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
* TÀI SẢN
    * Tài sản cố định
        * Tài sản cố định hữu hình (221)
            * Nguyên giá
                * Số cuối năm: 100
                * Số đầu năm: 90
            * Giá trị hao mòn lũy kế
                * Số cuối năm: (20)
                * Số đầu năm: (15)
        * Tài sản cố định vô hình (227)
            * Nguyên giá
                * Số cuối năm: 50
                * Số đầu năm: 40
"""
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result["canonical"])
    assert nodes["ASSET.FIXED_ASSETS.TANGIBLE.COST"]["value"]["current"] == "100"
    assert nodes["ASSET.FIXED_ASSETS.TANGIBLE.ACCUM_DEPR"]["value"]["current"] == "(20)"
    assert nodes["ASSET.FIXED_ASSETS.INTANGIBLE.COST"]["value"]["current"] == "50"

def test_structural_section_does_not_dual_role_from_descendant_values():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
* NỢ PHẢI TRẢ
    * Các khoản nợ Chính phủ và NHNNVN
        * 31/12/2025: 10
        * 31/12/2024: 9
    * TỔNG NỢ PHẢI TRẢ
        * 31/12/2025: 100
        * 31/12/2024: 90
"""
    result = make_pipeline().parse_text(raw)
    total = node_map(result["canonical"])["TOTAL_LIABILITIES"]
    assert total["value"]["current"] == "100"
    assert total["value"]["previous"] == "90"

def test_plain_section_label_is_not_total_alias_when_true_total_follows():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
* NỢ PHẢI TRẢ
    * Các khoản nợ Chính phủ và NHNNVN
        * 31/12/2025: 10
        * 31/12/2024: 9
    * TỔNG NỢ PHẢI TRẢ
        * 31/12/2025: 100
        * 31/12/2024: 90
"""
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result["canonical"])
    assert nodes["LIABILITY"]["value"]["current"] is None
    assert nodes["TOTAL_LIABILITIES"]["value"]["current"] == "100"


def test_keyed_record_wrapper_uses_ten_chi_tieu_as_semantic_label():
    raw = """
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
**NGUỒN VỐN**
* Mã số: 400
    * Tên chỉ tiêu: D. VỐN CHỦ SỞ HỮU
    * Thuyết minh: 27
    * 31/12/2025: 62.201
    * 01/01/2025: 58.397
"""
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result["canonical"])
    assert nodes["TOTAL_EQUITY"]["value"]["current"] == "62.201"
    assert nodes["TOTAL_EQUITY"]["value"]["previous"] == "58.397"


def test_total_followed_by_so_lieu_ngay_attributes():
    raw = """
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
**TỔNG CỘNG TÀI SẢN**
* Số liệu ngày 31/12/2025 (VND): 86.282
* Số liệu ngày 01/01/2025 (VND): 83.383
"""
    result = make_pipeline().parse_text(raw)
    n = node_map(result["canonical"])["TOTAL_ASSETS"]
    assert n["value"]["current"] == "86.282"
    assert n["value"]["previous"] == "83.383"
