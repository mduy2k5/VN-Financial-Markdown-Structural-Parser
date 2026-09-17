from pathlib import Path

from flat_parser.context import financial_position_scope
from flat_parser.pipeline import FlatParserPipeline
from flat_parser.qa import canonical_completeness, detect_explicit_totals, detect_sector
from flat_parser.textnorm import normalize_lines

ROOT = Path(__file__).resolve().parents[2]


def pipe():
    return FlatParserPipeline(
        schema_path=ROOT / "resources/schemas/financial_position_schema.json",
        aliases_path=ROOT / "resources/schemas/financial_position_aliases.json",
        universal_guide_path=ROOT / "resources/guides/compiled/structural_guide.json",
    )


def nmap(doc):
    return {n["node_id"]: n for n in doc["nodes"]}


def test_metadata_title_is_valid_statement_start_and_keeps_assets_page():
    raw = """
# Page 8
- Tên Ngân hàng: ABC
- Mã Báo cáo: B02/TCTD-HN
- Tiêu đề: BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
- Ngày báo cáo: 31 tháng 12 năm 2025
TÀI SẢN
TỔNG TÀI SẢN
* 31/12/2025: 100
* 31/12/2024: 90
# Page 9
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT (tiếp theo)
NỢ PHẢI TRẢ
TỔNG NỢ PHẢI TRẢ
* 31/12/2025: 60
* 31/12/2024: 50
TỔNG VỐN CHỦ SỞ HỮU
* 31/12/2025: 40
* 31/12/2024: 40
TỔNG NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU
* 31/12/2025: 100
* 31/12/2024: 90
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
"""
    lines = normalize_lines(raw)
    start, end, debug = financial_position_scope(lines)
    selected = next(x.clean for x in lines if x.line_no == start)
    assert "Tiêu đề:" in selected
    result = pipe().parse_text(raw)
    nm = nmap(result["canonical"])
    assert nm["TOTAL_ASSETS"]["value"]["current"] == "100"
    assert result["debug"]["stats"]["explicit_total_missed"] == 0


def test_explicit_total_miss_is_detectable_even_outside_selected_scope_margin():
    raw = """
TỔNG TÀI SẢN
* 31/12/2025: 100
* 31/12/2024: 90
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT (tiếp theo)
NỢ PHẢI TRẢ
* 31/12/2025: 60
* 31/12/2024: 50
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
"""
    lines = normalize_lines(raw)
    p = pipe()
    explicit = detect_explicit_totals(lines, 4, 8, p.guide)
    canonical = {"nodes": [
        {"node_id": x, "value": {"current": None, "previous": None}}
        for x in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY", "TOTAL_LIABILITIES_AND_EQUITY")
    ]}
    comp = canonical_completeness(canonical, explicit)
    assert comp["explicit_total_missed"] >= 1
    assert comp["explicit_total_missed_details"][0]["node_id"] == "TOTAL_ASSETS"


def test_ctck_is_reported_as_schema_sector_gap_not_silent_healthy():
    raw = """
CÔNG TY CỔ PHẦN CHỨNG KHOÁN ABC
BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Mẫu số B01 - CTCK
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN TÀI CHÍNH FVTPL
* Số cuối năm: 100
* Số đầu năm: 90
TỔNG TÀI SẢN
* Số cuối năm: 100
* Số đầu năm: 90
TỔNG NGUỒN VỐN
* Số cuối năm: 100
* Số đầu năm: 90
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG
"""
    result = pipe().parse_text(raw)
    stats = result["debug"]["stats"]
    assert stats["detected_sector"] == "securities"
    assert stats["schema_sector_gap"] == "securities"
    assert stats["statement_health"] == "schema_sector_gap:securities"


def test_unknown_financial_label_is_counted_even_when_unresolved_is_zero():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
* Khoản tài sản siêu đặc thù chưa có schema
  * Số cuối năm: 12
  * Số đầu năm: 10
TỔNG TÀI SẢN
* Số cuối năm: 12
* Số đầu năm: 10
TỔNG NGUỒN VỐN
* Số cuối năm: 12
* Số đầu năm: 10
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG
"""
    result = pipe().parse_text(raw)
    stats = result["debug"]["stats"]
    assert stats["unknown_financial_labels"] >= 1
    assert result["debug"]["semantic_coverage"]["unknown_examples"]


def test_root_section_does_not_inherit_child_note():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
* Tiền mặt, vàng
  * Thuyết minh: 5
  * Số cuối năm: 10
  * Số đầu năm: 9
TỔNG TÀI SẢN
* Số cuối năm: 10
* Số đầu năm: 9
TỔNG NGUỒN VỐN
* Số cuối năm: 10
* Số đầu năm: 9
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG
"""
    result = pipe().parse_text(raw)
    nm = nmap(result["canonical"])
    assert nm["ASSET"]["value"]["note"] is None

def test_same_label_parent_wrapper_without_value_is_not_unresolved():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
* Chứng khoán kinh doanh
  * Chứng khoán kinh doanh
    * Số cuối năm: -
    * Số đầu năm: 100
TỔNG TÀI SẢN
* Số cuối năm: 200
* Số đầu năm: 180
TỔNG NGUỒN VỐN
* Số cuối năm: 200
* Số đầu năm: 180
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG
"""
    result = pipe().parse_text(raw)
    assert not any(x.get("source_label") == "Chứng khoán kinh doanh" for x in result["debug"]["unresolved"])
    assert any(x.get("classification") == "structural_wrapper_no_value" for x in result["debug"]["ignored_non_errors"])
