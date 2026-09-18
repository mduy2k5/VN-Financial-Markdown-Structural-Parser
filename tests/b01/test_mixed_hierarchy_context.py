from pathlib import Path

from flat_parser.alias_matcher import choose_candidate, match_candidates
from flat_parser.models import StructuralNode
from flat_parser.pipeline import FlatParserPipeline
from flat_parser.semantic_catalog import SemanticCatalog


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "resources" / "schemas" / "financial_position_schema.json"
ALIASES = ROOT / "resources" / "schemas" / "financial_position_aliases.json"
GUIDE = ROOT / "resources" / "guides" / "compiled" / "structural_guide.json"


def _pipeline():
    return FlatParserPipeline(
        schema_path=SCHEMA,
        aliases_path=ALIASES,
        universal_guide_path=GUIDE,
        scope_mode="financial_position",
        mapping_strategy="legacy",
    )


def _nodes(result):
    return {node["node_id"]: node for node in result["canonical"]["nodes"]}


def test_source_context_breaks_generic_nguyen_gia_tie_before_resolution():
    catalog = SemanticCatalog(SCHEMA, ALIASES)
    node = StructuralNode(
        node_index=0,
        line_no=10,
        raw_text="Nguyên giá",
        text="Nguyên giá",
        indent=0,
        is_bullet=True,
        bullet_marker="*",
        representation="bullet",
        label_text="Nguyên giá",
    )
    context = {
        "path": ["Tài sản cố định", "Tài sản cố định thuê tài chính", "Nguyên giá"],
        "parent_label": "Tài sản cố định thuê tài chính",
        "semantic_anchor": "Tài sản cố định thuê tài chính",
    }

    candidates = match_candidates(
        node,
        [node],
        catalog,
        [],
        source_context=context,
    )
    selected, reason = choose_candidate(candidates)

    assert reason is None
    assert selected is not None
    assert selected.node_id == "ASSET.FIXED_ASSETS.FINANCE_LEASE.COST"
    assert "source_context_semantic_anchor" in selected.evidence


def test_plain_numbered_rows_keep_short_long_context_and_bound_section_values():
    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
Năm 2025
Năm 2024

* NỢ PHẢI TRẢ
    * Nợ ngắn hạn
        * Số cuối năm: 100
        * Số đầu năm: 90
    Phải trả người bán ngắn hạn
        * Số cuối năm: 40
        * Số đầu năm: 30
    * Nợ dài hạn
        * Số cuối năm: 200
        * Số đầu năm: 180
    Phải trả người bán dài hạn
        * Số cuối năm: 50
        * Số đầu năm: 45
"""
    result = _pipeline().parse_text(raw, source_name="mixed_hierarchy.md")
    nodes = _nodes(result)

    short = nodes["LIABILITY.TRADE_PAYABLES.SHORT_TERM"]
    long = nodes["LIABILITY.TRADE_PAYABLES.LONG_TERM"]
    assert short["value"]["current"] == "40"
    assert long["value"]["current"] == "50"
    assert short["source_context"]["maturity"] == "short_term"
    assert long["source_context"]["maturity"] == "long_term"
    assert nodes["LIABILITY.CURRENT"]["value"]["current"] == "100"
    assert nodes["LIABILITY.NON_CURRENT"]["value"]["current"] == "200"


def test_generic_fixed_asset_depreciation_uses_structural_context():
    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
Năm 2025
Năm 2024

* Tài sản cố định
    * Tài sản cố định hữu hình: 100, 90
    * Nguyên giá: 80, 70
    * Giá trị khấu hao lũy kế: (20), (18)
    * Tài sản cố định thuê tài chính: 30, 25
    * Nguyên giá: 35, 30
    * Giá trị khấu hao lũy kế: (5), (5)
* Bất động sản đầu tư
    * Nguyên giá: 60, 50
    * Giá trị khấu hao lũy kế: (10), (9)
"""
    result = _pipeline().parse_text(raw, source_name="fixed_asset_context.md")
    nodes = _nodes(result)

    assert nodes["ASSET.FIXED_ASSETS.TANGIBLE.ACCUM_DEPR"]["value"]["current"] == "(20)"
    assert nodes["ASSET.FIXED_ASSETS.FINANCE_LEASE.ACCUM_DEPR"]["value"]["current"] == "(5)"
    assert nodes["ASSET.INVESTMENT_PROPERTY.ACCUM_DEPR"]["value"]["current"] == "(10)"
    assert nodes["ASSET.FIXED_ASSETS.FINANCE_LEASE.ACCUM_DEPR"]["source_context"]["semantic_anchor"] == "Tài sản cố định thuê tài chính"


def test_conflicting_duplicate_periods_are_audited():
    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
Năm 2025
Năm 2024

* Tài sản cố định hữu hình
    * Giá trị khấu hao lũy kế: (20), (18)
    * Giá trị khấu hao lũy kế: (22), (19)
"""
    result = _pipeline().parse_text(raw, source_name="conflict.md")
    node = _nodes(result)["ASSET.FIXED_ASSETS.TANGIBLE.ACCUM_DEPR"]
    dedup = result["canonical"]["diagnostics"]["semantic_dedup"]

    assert result["canonical"]["status"] == "review_required"
    assert dedup["conflict_count"] == 2
    assert node["mapping"]["status"] == "review_required"
    assert node["mapping"]["method"] == "semantic_dedup_conflict"
    actions = [
        action
        for occurrence in node["extraction_meta"]["occurrences"]
        for action in occurrence["actions"]
    ]
    assert any(action["action"] == "conflict_existing_period" for action in actions)
