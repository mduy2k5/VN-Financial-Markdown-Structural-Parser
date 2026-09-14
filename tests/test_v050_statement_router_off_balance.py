from pathlib import Path

from flat_parser.integrated_pipeline import IntegratedFinancialPipeline
from flat_parser.preprocess import filter_noise
from flat_parser.statement_scanner import scan_statements
from flat_parser.textnorm import normalize_lines

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "resources"


def scan(text):
    return scan_statements(filter_noise(normalize_lines(text)))


def test_scanner_separates_fp_off_balance_income_for_bank():
    text = """
Ngân hàng TMCP Ví dụ
Mẫu số: B02/TCTD-HN
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31/12/2025
TÀI SẢN
Tiền mặt | 100 | 90
TỔNG CỘNG TÀI SẢN | 100 | 90
NỢ PHẢI TRẢ
VỐN CHỦ SỞ HỮU
CÁC CHỈ TIÊU NGOÀI BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Bảo lãnh vay vốn | 10 | 11
Cam kết giao dịch hối đoái | 20 | 21
Cam kết mua ngoại tệ | 3 | 4
Cam kết bán ngoại tệ | 5 | 6
Bảo lãnh khác | 7 | 8
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT
Thu nhập lãi và các khoản thu nhập tương tự | 30 | 29
"""
    out = scan(text)
    assert out["sector"]["sector"] == "bank"
    ranges = {x["statement_type"]: x for x in out["ranges"]}
    assert "FINANCIAL_POSITION" in ranges
    assert "OFF_BALANCE" in ranges
    assert "INCOME_STATEMENT" in ranges
    assert ranges["FINANCIAL_POSITION"]["end_line"] < ranges["OFF_BALANCE"]["start_line"]
    assert ranges["OFF_BALANCE"]["end_line"] < ranges["INCOME_STATEMENT"]["start_line"]


def test_toc_title_does_not_win_over_real_statement():
    text = """
MỤC LỤC
Báo cáo tình hình tài chính 1 - 2
Báo cáo kết quả hoạt động kinh doanh 3 - 4

Ngân hàng TMCP Ví dụ
Mẫu số: B02/TCTD-HN
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31/12/2025
TÀI SẢN
Tiền mặt | 100 | 90
NỢ PHẢI TRẢ
VỐN CHỦ SỞ HỮU
TỔNG CỘNG TÀI SẢN | 200 | 190
TỔNG CỘNG NGUỒN VỐN | 200 | 190
"""
    out = scan(text)
    fp = next(x for x in out["ranges"] if x["statement_type"] == "FINANCIAL_POSITION")
    assert fp["start_line"] > 4


def test_enterprise_off_balance_is_not_routed_to_bank_resource():
    text = """
CÔNG TY CỔ PHẦN VÍ DỤ
Mẫu số B01-DN
BÁO CÁO TÌNH HÌNH TÀI CHÍNH
TÀI SẢN
TỔNG CỘNG TÀI SẢN | 100 | 90
NỢ PHẢI TRẢ
VỐN CHỦ SỞ HỮU
CÁC CHỈ TIÊU NGOÀI BẢNG CÂN ĐỐI KẾ TOÁN
Cam kết khác | 5 | 4
"""
    out = scan(text)
    assert out["sector"]["sector"] == "enterprise"
    ob = next(x for x in out["ranges"] if x["statement_type"] == "OFF_BALANCE")
    assert ob["status"] == "resource_unavailable"


def test_integrated_pipeline_uses_existing_engine_for_off_balance():
    text = """
Ngân hàng TMCP Ví dụ
Mẫu số: B02/TCTD-HN
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31/12/2025
TÀI SẢN
Tổng cộng tài sản | 100 | 90
NỢ PHẢI TRẢ
Tổng cộng nợ phải trả | 60 | 55
VỐN CHỦ SỞ HỮU
Tổng cộng vốn chủ sở hữu | 40 | 35
TỔNG CỘNG NGUỒN VỐN | 100 | 90
CÁC CHỈ TIÊU NGOÀI BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Bảo lãnh vốn vay | 10 | 11
Cam kết mua giao dịch hoán đổi ngoại tệ | 2 | 3
Nợ khó đòi đã xử lý | 4 | 5
Tổng cộng | 16 | 19
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT
Thu nhập lãi và các khoản thu nhập tương tự | 30 | 29
"""
    pipe = IntegratedFinancialPipeline(
        financial_schema_path=RES / "universal_financial_position_schema_v1_6.json",
        financial_aliases_path=RES / "universal_financial_position_aliases_v1_6_1.json",
        universal_guide_path=RES / "universal_structural_guide_a1_a5.json",
        off_balance_schema_path=RES / "universal_off_balance_bank_schema_v1_3.json",
        off_balance_aliases_path=RES / "universal_off_balance_bank_aliases_v1_3.json",
    )
    out = pipe.parse_text(text, "synthetic.md")
    assert "financial_position" in out["statements"]
    assert "off_balance" in out["statements"]
    ob_nodes = {n["node_id"]: n for n in out["statements"]["off_balance"]["canonical"]["nodes"]}
    assert ob_nodes["OFF_BALANCE.GUARANTEES.LOAN"]["value"]["current"] == "10"
    assert ob_nodes["OFF_BALANCE.FX_COMMITMENTS.SWAP_BUY"]["value"]["current"] == "2"
    assert ob_nodes["OFF_BALANCE.WRITTEN_OFF_BAD_DEBT"]["value"]["current"] == "4"
