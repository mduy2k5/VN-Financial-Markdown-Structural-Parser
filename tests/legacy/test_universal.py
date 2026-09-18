from pathlib import Path
import json

from flat_parser.pipeline import FlatParserPipeline

ROOT = Path(__file__).resolve().parents[2]

SAMPLE_REPORT = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Đơn vị tính: triệu đồng
Năm 2025
Năm 2024

* **Tài sản**

* **Hàng tồn kho** | 141 | | 22.179.036 | 21.055.950

* **Tiền và các khoản tương đương tiền**
    * **Tiền mặt, vàng bạc, đá quý**
        * Thuyết minh: 5
        * Số cuối năm: 493.695 triệu đồng
        * Số đầu năm: 315.917 triệu đồng

* **Tài sản cố định**
    * **Tài sản cố định hữu hình**
        * **Nguyên giá**
            * Năm 2025: 1.200.000
            * Năm 2024: 1.000.000

* **Các khoản phải thu**
    * **Số cuối năm**
        * **Phải thu của khách hàng**: 123.000
    * **Số đầu năm**
        * **Phải thu của khách hàng**: 100.000

| Mã số | Tài sản | Thuyết minh | Năm 2025 | Năm 2024 |
| --- | --- | --- | ---: | ---: |
| 270 | Tổng cộng tài sản |  | 50.000.000 | 45.000.000 |

* Hàng tồn kho
    * Năm 2025: 999.999.999
    * Năm 2024: 888.888.888

# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH

# THUYẾT MINH BÁO CÁO TÀI CHÍNH

* Hàng tồn kho
    * Năm 2025: 999.999.999
    * Năm 2024: 888.888.888
"""


def pipeline():
    return FlatParserPipeline(
        schema_path=ROOT / "resources/schemas/financial_position_schema.json",
        aliases_path=ROOT / "resources/schemas/financial_position_aliases.json",
        universal_guide_path=ROOT / "resources/guides/compiled/structural_guide.json",
    )


def node_map(doc):
    return {x["node_id"]: x for x in doc["nodes"]}


def parse_sample():
    return pipeline().parse_text(SAMPLE_REPORT, source_name="inline_statement.md")


def test_compiled_guide_has_a1_a5_sources():
    guide = json.loads(
        (ROOT / "resources/guides/compiled/structural_guide.json").read_text(encoding="utf-8")
    )
    ids = {p["id"] for p in guide["patterns"]}
    assert "SP_PERIOD_CONTAINER" in ids
    assert "SP_MARKDOWN_TABLE_ROW" in ids
    assert "SP_PIPE_DELIMITED_INLINE_ROW" in ids
    assert "SP_PERIOD_CHILDREN" in ids
    assert len(guide["source_guides"]) == 5


def test_alias_structure_and_first_value_policy():
    result = parse_sample()
    nodes = node_map(result["canonical"])

    inv = nodes["ASSET.INVENTORY"]
    assert inv["value"]["current"] == "22.179.036"
    assert inv["value"]["previous"] == "21.055.950"

    cash = nodes["ASSET.CASH_EQUIV.CASH_ON_HAND"]
    assert cash["value"]["current"] == "493.695"
    assert cash["value"]["previous"] == "315.917"
    assert cash["value"]["note"] == "5"

    tangible_cost = nodes["ASSET.FIXED_ASSETS.TANGIBLE.COST"]
    assert tangible_cost["value"]["current"] == "1.200.000"
    assert tangible_cost["value"]["previous"] == "1.000.000"

    total_assets = nodes["TOTAL_ASSETS"]
    assert total_assets["value"]["current"] == "50.000.000"
    assert total_assets["value"]["previous"] == "45.000.000"

    # Section Notes nằm sau ranh giới scope và không được ghi đè inventory.
    assert inv["value"]["current"] != "999.999.999"


def test_period_container_propagation():
    result = parse_sample()
    nodes = node_map(result["canonical"])

    customer = nodes["ASSET.RECEIVABLES.CUSTOMER"]
    assert customer["value"]["current"] == "123.000"
    assert customer["value"]["previous"] == "100.000"


def test_first_value_per_period_never_overwrites():
    result = parse_sample()
    nodes = node_map(result["canonical"])
    inv = nodes["ASSET.INVENTORY"]

    assert inv["value"]["current"] == "22.179.036"
    assert inv["value"]["previous"] == "21.055.950"

    occurrence_actions = inv["extraction_meta"]["occurrences"]
    assert any(
        any(a["action"] == "skip_existing_period" for a in occ["actions"])
        for occ in occurrence_actions
    )


def test_a4_pipe_role_row_is_self_contained():
    raw = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024
* Tiền mặt, vàng bạc, đá quý: 39.926 (USD) | 13 (EUR) | 398 (Các ngoại tệ khác) | 40.337 (Tổng cộng)
"""
    result = pipeline().parse_text(raw, source_name="pipe_roles.md")
    nodes = node_map(result["canonical"])
    cash = nodes["ASSET.CASH_EQUIV.CASH_ON_HAND"]
    additional = cash["value"]["additional"]

    assert additional["additional:USD"] == "39.926"
    assert additional["additional:EUR"] == "13"
    assert additional["additional:Các ngoại tệ khác"] == "398"
    assert additional["additional:Tổng cộng"] == "40.337"


def test_period_formats_and_range_are_preserved():
    from flat_parser.guide import UniversalGuide
    from flat_parser.primitives import extract_periods, extract_values

    guide = UniversalGuide(ROOT / "resources/guides/compiled/structural_guide.json")

    p1 = extract_periods("Tại ngày 31.12.2025", 1, guide)
    p2 = extract_periods("Ngày 31 tháng 12 năm 2024", 1, guide)
    assert p1
    assert p2

    vals = extract_values("Lãi suất: 5,20 - 9,60 %/năm", 1, guide)
    assert vals[0].raw_value == "5,20 - 9,60"
    assert vals[0].normalized_candidate is None
