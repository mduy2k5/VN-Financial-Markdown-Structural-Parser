from pathlib import Path

from flat_parser.alias_matcher import choose_candidate, match_candidates
from flat_parser.models import StructuralNode
from flat_parser.pipeline import FlatParserPipeline
from flat_parser.semantic_catalog import SemanticCatalog
from src.b01_financial_position.extractor import FinancialPositionSourceParser


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


def test_period_wrapper_context_splits_same_label_parent_and_child():
    """Kỳ trên wrapper phải được truyền xuống child trùng nhãn với parent."""

    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
Năm 2025
Năm 2024

* Tài sản khác
    * 31/12/2025: 100
        * Tài sản khác: 40
    * 31/12/2024: 90
        * Tài sản khác: 30
"""
    result = _pipeline().parse_text(raw, source_name="period_wrapper_same_label.md")
    nodes = _nodes(result)
    dedup = result["canonical"]["diagnostics"]["semantic_dedup"]

    assert nodes["ASSET.OTHER"]["value"]["current"] == "100"
    assert nodes["ASSET.OTHER"]["value"]["previous"] == "90"
    assert nodes["ASSET.OTHER.OTHER"]["value"]["current"] == "40"
    assert nodes["ASSET.OTHER.OTHER"]["value"]["previous"] == "30"
    assert dedup["conflict_count"] == 0
    child_contexts = [
        occurrence["source_context"]["path"]
        for occurrence in nodes["ASSET.OTHER.OTHER"]["extraction_meta"]["occurrences"]
    ]
    assert any(path[-1] == path[0] for path in child_contexts)


def test_same_label_parent_overlap_is_derived_from_schema_not_only_alias_flags():
    catalog = SemanticCatalog(SCHEMA, ALIASES)

    overlap = catalog.same_label_parent_overlap("ASSET.OTHER.OTHER")

    assert "tai san khac" in overlap
    assert "tai san co khac" in overlap


def test_same_label_recovery_flag_can_roll_back_to_baseline_mapping():
    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
Năm 2025
Năm 2024

* Tài sản khác
    * 31/12/2025: 100
        * Tài sản khác: 40
    * 31/12/2024: 90
        * Tài sản khác: 30
"""

    enabled = _pipeline().parse_text(raw, source_name="same_label_enabled.md")
    disabled = FlatParserPipeline(
        schema_path=SCHEMA,
        aliases_path=ALIASES,
        universal_guide_path=GUIDE,
        scope_mode="financial_position",
        mapping_strategy="legacy",
        same_label_recovery=False,
    ).parse_text(raw, source_name="same_label_disabled.md")

    enabled_nodes = _nodes(enabled)
    disabled_nodes = _nodes(disabled)

    assert enabled["debug"]["stats"]["same_label_recovery"] is True
    assert enabled_nodes["ASSET.OTHER"]["value"]["current"] == "100"
    assert enabled_nodes["ASSET.OTHER.OTHER"]["value"]["current"] == "40"
    assert disabled["debug"]["stats"]["same_label_recovery"] is False
    assert disabled_nodes["ASSET.OTHER"]["value"]["current"] is None
    assert disabled_nodes["ASSET.OTHER.OTHER"]["value"]["current"] == "40"
    assert any(
        item.get("reason") == "ambiguous_mapping"
        for item in disabled["debug"]["unresolved"]
    )


def test_vcb_source_keeps_same_label_asset_parent_and_child_separate():
    source = ROOT / "md_reports" / "VCB_BCTC_2025_hop_nhat_kiem_toan.md"
    result = _pipeline().parse_file(source)
    nodes = _nodes(result)

    assert nodes["ASSET.OTHER"]["value"]["current"] == "33.993.212"
    assert nodes["ASSET.OTHER.OTHER"]["value"]["current"] == "5.951.104"
    assert nodes["ASSET.OTHER.OTHER"]["value"]["previous"] == "6.516.040"
    child_paths = [
        occurrence["source_context"]["path"]
        for occurrence in nodes["ASSET.OTHER.OTHER"]["extraction_meta"]["occurrences"]
    ]
    assert any(path[-1] == path[0] for path in child_paths)


def test_vcb_production_source_parser_preserves_same_label_recovery_diagnostic():
    source = ROOT / "md_reports" / "VCB_BCTC_2025_hop_nhat_kiem_toan.md"
    parser = FinancialPositionSourceParser(same_label_recovery=True)
    result = parser.parse_text(
        source.read_text(encoding="utf-8"),
        source_name=source.name,
        current_year=2025,
        previous_year=2024,
    )
    nodes = _nodes({"canonical": result["canonical"]})

    assert nodes["ASSET.OTHER"]["value"]["current"] == "33.993.212"
    assert nodes["ASSET.OTHER.OTHER"]["value"]["current"] == "5.951.104"
    assert result["metrics"]["parser"]["same_label_recovery"] is True
    assert result["canonical"]["diagnostics"]["source_statement_recovery"][
        "same_label_recovery"
    ] is True


def test_period_major_repeated_sibling_label_stays_on_same_schema_node():
    """Hai block kỳ không tự tạo parent/child cho cùng một nhãn nguồn."""

    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN

* Chứng khoán đầu tư
    * 31/12/2025 (triệu đồng): 51.149.531
        * Chứng khoán đầu tư sẵn sàng để bán: 51.149.531
    * 31/12/2024 (triệu đồng): 50.344.312
        * Chứng khoán đầu tư sẵn sàng để bán: 50.345.812
"""
    result = _pipeline().parse_text(raw, source_name="period_major_repeated_label.md")
    nodes = _nodes(result)

    afs = nodes["ASSET.FIN_INV.AFS"]
    gross = nodes["ASSET.FIN_INV.AFS.GROSS"]

    assert afs["value"]["current"] == "51.149.531"
    assert afs["value"]["previous"] == "50.345.812"
    assert gross["value"]["current"] is None
    assert gross["value"]["previous"] is None


def test_period_wrapper_keeps_generic_fixed_asset_children_on_direct_parent():
    """Wrapper kỳ không làm mất dòng ``Nguyên giá`` của kỳ trước."""

    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN

* Tài sản cố định
    * 31/12/2025 Triệu VND: 8.232.904
        * Tài sản cố định hữu hình:
            * 31/12/2025 Triệu VND: 5.618.792
                * Nguyên giá: 16.271.879
                * Hao mòn tài sản cố định: (10.653.087)
            * 31/12/2024 Triệu VND: 5.530.579
                * Nguyên giá: 15.808.302
                * Hao mòn tài sản cố định: (10.277.723)
        * Tài sản cố định vô hình:
            * 31/12/2025 Triệu VND: 2.614.112
                * Nguyên giá: 5.284.812
                * Hao mòn tài sản cố định: (2.670.700)
            * 31/12/2024 Triệu VND: 2.562.298
                * Nguyên giá: 5.072.735
                * Hao mòn tài sản cố định: (2.510.437)
"""
    result = _pipeline().parse_text(raw, source_name="period_wrapper_generic_children.md")
    nodes = _nodes(result)

    assert nodes["ASSET.FIXED_ASSETS.TANGIBLE.COST"]["value"]["current"] == "16.271.879"
    assert nodes["ASSET.FIXED_ASSETS.TANGIBLE.COST"]["value"]["previous"] == "15.808.302"
    assert nodes["ASSET.FIXED_ASSETS.INTANGIBLE.COST"]["value"]["current"] == "5.284.812"
    assert nodes["ASSET.FIXED_ASSETS.INTANGIBLE.COST"]["value"]["previous"] == "5.072.735"
    assert nodes["ASSET.FIXED_ASSETS.TANGIBLE.ACCUM_DEPR"]["value"]["previous"] == "(10.277.723)"
    assert nodes["ASSET.FIXED_ASSETS.INTANGIBLE.ACCUM_DEPR"]["value"]["previous"] == "(2.510.437)"


def test_standalone_period_headings_split_period_major_blocks():
    """Tiêu đề kỳ không có bullet vẫn phải truyền kỳ xuống cả block."""

    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
**31/12/2025**
* TÀI SẢN
    * A. TÀI SẢN NGẮN HẠN: 100
**01/01/2025**
* TÀI SẢN
    * A. TÀI SẢN NGẮN HẠN: 90
"""
    result = _pipeline().parse_text(raw, source_name="standalone_period_heading.md")
    nodes = _nodes(result)
    dedup = result["canonical"]["diagnostics"]["semantic_dedup"]

    assert nodes["ASSET.CURRENT"]["value"]["current"] == "100"
    assert nodes["ASSET.CURRENT"]["value"]["previous"] == "90"
    assert dedup["conflict_count"] == 0


def test_pipe_values_ignore_unit_parentheses_as_period_roles():
    """Đơn vị trong ngoặc không được biến hai cột kỳ thành một role phụ."""

    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
Năm 2025
Năm 2024

* TÀI SẢN
    * A. TÀI SẢN NGẮN HẠN: 100 (đồng) | 90 (đồng)
"""
    result = _pipeline().parse_text(raw, source_name="pipe_unit_suffix.md")
    node = _nodes(result)["ASSET.CURRENT"]
    dedup = result["canonical"]["diagnostics"]["semantic_dedup"]

    assert node["value"]["current"] == "100"
    assert node["value"]["previous"] == "90"
    assert node["value"]["additional"] is None
    assert dedup["conflict_count"] == 0


def test_current_period_alias_nam_hien_tai_is_not_dropped():
    """Một số báo cáo dùng ``Năm hiện tại`` thay cho ``Năm nay``."""

    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
* Tiền và các khoản tương đương tiền
    * Năm hiện tại: 100
    * Năm trước: 90
"""
    result = _pipeline().parse_text(raw, source_name="current_period_alias.md")
    node = _nodes(result)["ASSET.CASH_EQUIV"]

    assert node["value"]["current"] == "100"
    assert node["value"]["previous"] == "90"


def test_parent_child_alias_collision_is_audited_not_a_semantic_conflict():
    """Schema thiếu node riêng không được biến cây nguồn thành conflict giả."""

    raw = """
# BẢNG CÂN ĐỐI KẾ TOÁN
Năm 2025
Năm 2024

* VỐN CHỦ SỞ HỮU
    * Vốn đầu tư của chủ sở hữu: 100, 90
        * Vốn góp của chủ sở hữu: 60, 50
"""
    result = _pipeline().parse_text(raw, source_name="owner_capital_parent_child.md")
    node = _nodes(result)["EQUITY.OWNER_CAPITAL"]
    dedup = result["canonical"]["diagnostics"]["semantic_dedup"]

    assert dedup["conflict_count"] == 0
    assert dedup["structural_context_collision_count"] == 2
    actions = [
        action
        for occurrence in node["extraction_meta"]["occurrences"]
        for action in occurrence["actions"]
    ]
    assert any(action["action"] == "structural_context_collision" for action in actions)
