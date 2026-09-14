from pathlib import Path
import json

from flat_parser.pipeline import FlatParserPipeline

ROOT = Path(__file__).resolve().parents[1]


def pipeline():
    return FlatParserPipeline(
        schema_path=ROOT / "resources/universal_financial_position_schema_v1_1.json",
        aliases_path=ROOT / "resources/universal_financial_position_aliases_v1_1.json",
        universal_guide_path=ROOT / "resources/universal_structural_guide_a1_a5.json",
    )


def node_map(doc):
    return {x["node_id"]: x for x in doc["nodes"]}


def test_compiled_guide_has_a1_a5_sources():
    guide = json.loads(
        (ROOT / "resources/universal_structural_guide_a1_a5.json").read_text(encoding="utf-8")
    )
    ids = {p["id"] for p in guide["patterns"]}
    assert "SP_PERIOD_CONTAINER" in ids
    assert "SP_MARKDOWN_TABLE_ROW" in ids
    assert "SP_PIPE_DELIMITED_INLINE_ROW" in ids
    assert "SP_PERIOD_CHILDREN" in ids
    assert len(guide["source_guides"]) == 5


def test_alias_structure_and_first_value_policy():
    result = pipeline().parse_file(ROOT / "samples/sample_a1_a5.md")
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

    # Notes section lies after scope boundary and cannot overwrite inventory.
    assert inv["value"]["current"] != "999.999.999"


def test_period_container_propagation():
    result = pipeline().parse_file(ROOT / "samples/sample_a1_a5.md")
    nodes = node_map(result["canonical"])

    customer = nodes["ASSET.RECEIVABLES.CUSTOMER"]
    assert customer["value"]["current"] == "123.000"
    assert customer["value"]["previous"] == "100.000"


def test_first_value_per_period_never_overwrites():
    result = pipeline().parse_file(ROOT / "samples/sample_a1_a5.md")
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

    guide = UniversalGuide(ROOT / "resources/universal_structural_guide_a1_a5.json")

    p1 = extract_periods("Tại ngày 31.12.2025", 1, guide)
    p2 = extract_periods("Ngày 31 tháng 12 năm 2024", 1, guide)
    assert p1
    assert p2

    vals = extract_values("Lãi suất: 5,20 - 9,60 %/năm", 1, guide)
    assert vals[0].raw_value == "5,20 - 9,60"
    assert vals[0].normalized_candidate is None
