from pathlib import Path
from flat_parser.pipeline import FlatParserPipeline
from flat_parser.context import financial_position_scope
from flat_parser.textnorm import normalize_lines

ROOT = Path(__file__).resolve().parents[1]

def pipe():
    return FlatParserPipeline(
        schema_path=ROOT/"resources/universal_financial_position_schema_v1_1.json",
        aliases_path=ROOT/"resources/universal_financial_position_aliases_v1_1.json",
        universal_guide_path=ROOT/"resources/universal_structural_guide_a1_a5.json",
    )

def nmap(doc):
    return {n["node_id"]: n for n in doc["nodes"]}

def test_tiny_audit_candidate_is_rejected_for_later_real_statement():
    raw = """
* Bảng cân đối kế toán hợp nhất tại ngày 31 tháng 12 năm 2025
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT

BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
TỔNG CỘNG TÀI SẢN
* Số cuối năm: 100
* Số đầu năm: 90
NỢ PHẢI TRẢ
TỔNG NỢ PHẢI TRẢ
* Số cuối năm: 60
* Số đầu năm: 50
VỐN CHỦ SỞ HỮU
TỔNG VỐN CHỦ SỞ HỮU
* Số cuối năm: 40
* Số đầu năm: 40
TỔNG CỘNG NGUỒN VỐN
* Số cuối năm: 100
* Số đầu năm: 90
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
"""
    lines=normalize_lines(raw)
    start,end,dbg=financial_position_scope(lines)
    selected=next(x.clean for x in lines if x.line_no==start)
    assert selected=="BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT"
    assert end-start>5

def test_plain_sequential_respects_previous_then_current_header_order():
    raw = """
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
NGUỒN VỐN
Số đầu năm
Số cuối năm
Mã số
C. NỢ PHẢI TRẢ
300
90
100
D. VỐN CHỦ SỞ HỮU
400
10
20
TỔNG CỘNG NGUỒN VỐN
440
100
120
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
"""
    result=pipe().parse_text(raw)
    nm=nmap(result["canonical"])
    assert nm["TOTAL_LIABILITIES"]["value"]["previous"]=="90"
    assert nm["TOTAL_LIABILITIES"]["value"]["current"]=="100"

def test_parenthetical_years_not_parsed_as_values():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TỔNG TÀI SẢN CÓ: 2.767.699.300 (2025), 2.385.387.732 (2024)
TỔNG NỢ PHẢI TRẢ: 2.588.044.295 (2025), 2.236.883.024 (2024)
TỔNG VỐN: 179.655.005 (2025), 148.504.708 (2024)
TỔNG NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU: 2.767.699.300 (2025), 2.385.387.732 (2024)
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
"""
    result=pipe().parse_text(raw)
    nm=nmap(result["canonical"])
    assert nm["TOTAL_ASSETS"]["value"]["current"]=="2.767.699.300"
    assert nm["TOTAL_ASSETS"]["value"]["previous"]=="2.385.387.732"
    assert nm["TOTAL_EQUITY"]["value"]["current"]=="179.655.005"

def test_column_major_block_rehydrates_labels_and_totals():
    raw = """
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
TÀI SẢN DÀI HẠN
Các khoản phải thu dài hạn
Tài sản cố định
TỔNG CỘNG TÀI SẢN (270=100+200)
Thuyết minh
Mã số
Số cuối năm
Số đầu năm
200
210
220
270
10
20
30
100
9
18
27
90
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
"""
    result=pipe().parse_text(raw)
    nm=nmap(result["canonical"])
    assert nm["ASSET.NON_CURRENT"]["value"]["current"]=="10"
    assert nm["TOTAL_ASSETS"]["value"]["current"]=="100"
    assert nm["TOTAL_ASSETS"]["value"]["previous"]=="90"
