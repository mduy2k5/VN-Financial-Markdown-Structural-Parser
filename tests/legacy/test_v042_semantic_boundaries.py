from pathlib import Path

from flat_parser.pipeline import FlatParserPipeline

ROOT = Path(__file__).resolve().parents[1]


def make_pipeline():
    return FlatParserPipeline(
        schema_path=ROOT / "resources/universal_financial_position_schema_v1_1.json",
        aliases_path=ROOT / "resources/universal_financial_position_aliases_v1_1.json",
        universal_guide_path=ROOT / "resources/universal_structural_guide_a1_a5.json",
    )


def node_map(doc):
    return {x["node_id"]: x for x in doc["nodes"]}


def test_semantic_child_values_do_not_leak_to_parent():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Cho vay khách hàng
    * Số cuối năm: 112.691.295
    * Số đầu năm: 97.032.286

    * Cho vay khách hàng
        * Số cuối năm: 113.891.373
        * Số đầu năm: 98.738.176

    * Dự phòng rủi ro cho vay khách hàng
        * Số cuối năm: (1.200.078)
        * Số đầu năm: (1.705.890)
"""
    result = make_pipeline().parse_text(raw, source_name="loans.md")
    nodes = node_map(result["canonical"])

    parent = nodes["ASSET.CUSTOMER_LOANS"]
    gross = nodes["ASSET.CUSTOMER_LOANS.GROSS"]
    allowance = nodes["ASSET.CUSTOMER_LOANS.ALLOWANCE"]

    assert parent["value"]["current"] == "112.691.295"
    assert parent["value"]["previous"] == "97.032.286"

    assert gross["value"]["current"] == "113.891.373"
    assert gross["value"]["previous"] == "98.738.176"

    assert allowance["value"]["current"] == "(1.200.078)"
    assert allowance["value"]["previous"] == "(1.705.890)"

    # Parent occurrence should contain only its own two values.
    occ = parent["extraction_meta"]["occurrences"][0]
    assert len(occ["values"]) == 2


def test_container_without_direct_value_does_not_take_child_value():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Các khoản nợ khác
    * Các khoản lãi, phí phải trả
        * Số cuối năm: 2.621.145
        * Số đầu năm: 1.736.021
    * Các khoản phải trả và công nợ khác
        * Số cuối năm: 1.987.508
        * Số đầu năm: 949.077
"""
    result = make_pipeline().parse_text(raw, source_name="other_liab.md")
    nodes = node_map(result["canonical"])

    parent = nodes["LIABILITY.OTHER"]
    child1 = nodes["LIABILITY.ACCRUED_INTEREST_FEES"]
    child2 = nodes["LIABILITY.OTHER_PAYABLES"]

    assert parent["value"]["current"] is None
    assert parent["value"]["previous"] is None

    assert child1["value"]["current"] == "2.621.145"
    assert child2["value"]["current"] == "1.987.508"


def test_bank_cash_alias_and_total_assets():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
tại ngày 31 tháng 12 năm 2025
B02/TCTD-HN
Năm 2025
Năm 2024

TÀI SẢN

* Tiền mặt
    * Số cuối năm: 493.695 triệu đồng
    * Số đầu năm: 315.917 triệu đồng

* TỔNG TÀI SẢN
    * Số cuối năm: 220.494.731 triệu đồng
    * Số đầu năm: 176.713.113 triệu đồng
"""
    result = make_pipeline().parse_text(raw, source_name="cash_total.md")
    nodes = node_map(result["canonical"])

    cash = nodes["ASSET.CASH_EQUIV.CASH_ON_HAND"]
    total = nodes["TOTAL_ASSETS"]

    assert cash["value"]["current"] == "493.695"
    assert cash["value"]["previous"] == "315.917"

    assert total["value"]["current"] == "220.494.731"
    assert total["value"]["previous"] == "176.713.113"


def test_plain_label_followed_by_period_bullets():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

**TỔNG TÀI SẢN**
* Số cuối năm: 220.494.731 triệu đồng
* Số đầu năm: 176.713.113 triệu đồng
"""
    result = make_pipeline().parse_text(raw, source_name="plain_total.md")
    nodes = node_map(result["canonical"])
    total = nodes["TOTAL_ASSETS"]

    assert total["value"]["current"] == "220.494.731"
    assert total["value"]["previous"] == "176.713.113"


def test_fixed_asset_generic_child_alias_uses_nearest_parent():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Tài sản cố định
    * Tài sản cố định hữu hình
        * Nguyên giá tài sản cố định
            * Số cuối năm: 1.353.557
            * Số đầu năm: 1.335.517
        * Khấu hao tài sản cố định
            * Số cuối năm: (791.924)
            * Số đầu năm: (750.031)

    * Tài sản cố định vô hình
        * Nguyên giá tài sản cố định
            * Số cuối năm: 983.088
            * Số đầu năm: 869.013
        * Hao mòn tài sản cố định
            * Số cuối năm: (441.276)
            * Số đầu năm: (387.366)
"""
    result = make_pipeline().parse_text(raw, source_name="fixed_assets.md")
    nodes = node_map(result["canonical"])

    assert nodes["ASSET.FIXED_ASSETS.TANGIBLE.COST"]["value"]["current"] == "1.353.557"
    assert nodes["ASSET.FIXED_ASSETS.TANGIBLE.ACCUM_DEPR"]["value"]["current"] == "(791.924)"
    assert nodes["ASSET.FIXED_ASSETS.INTANGIBLE.COST"]["value"]["current"] == "983.088"
    assert nodes["ASSET.FIXED_ASSETS.INTANGIBLE.ACCUM_DEPR"]["value"]["current"] == "(441.276)"
