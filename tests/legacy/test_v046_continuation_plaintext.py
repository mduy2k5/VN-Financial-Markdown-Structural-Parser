from pathlib import Path

from flat_parser.context import financial_position_scope
from flat_parser.pipeline import FlatParserPipeline
from flat_parser.textnorm import normalize_lines

ROOT = Path(__file__).resolve().parents[1]


def make_pipeline():
    return FlatParserPipeline(
        schema_path=ROOT / 'resources/universal_financial_position_schema_v1_1.json',
        aliases_path=ROOT / 'resources/universal_financial_position_aliases_v1_1.json',
        universal_guide_path=ROOT / 'resources/universal_structural_guide_a1_a5.json',
    )


def nmap(canonical):
    return {n['node_id']: n for n in canonical['nodes']}


def test_repeated_continuation_headings_keep_first_statement_page():
    raw = '''
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
A. TÀI SẢN
* Tổng tài sản Có:
    * 100
    * 90

BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT (tiếp theo)
B. NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU
* Tổng nợ phải trả: 70 (31/12/2025); 60 (31/12/2024)

BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT (tiếp theo)
* Tổng nợ phải trả và vốn chủ sở hữu: 100 (31/12/2025); 90 (31/12/2024)

BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
Năm 2025
'''
    lines = normalize_lines(raw)
    start, end, debug = financial_position_scope(lines)
    first = next(x.line_no for x in lines if x.clean == 'BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT')
    assert start == first
    assert end > start + 10


def test_plain_text_row_packet_uses_tail_as_current_previous():
    raw = '''
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
Đơn vị: Đồng

A. TÀI SẢN NGẮN HẠN
100
58.015.996.839.126
48.680.623.561.824

TỔNG CỘNG TÀI SẢN (270=100+200)
Số cuối năm: 81.510.550.856.141
Số đầu năm: 63.438.713.441.528

C. NỢ PHẢI TRẢ (Mã số: 300)
Số cuối năm: 38.672.356.541.926
Số đầu năm: 27.606.678.855.315

D. VỐN CHỦ SỞ HỮU (Mã số: 400)
Số cuối năm: 42.838.194.314.215
Số đầu năm: 35.832.034.586.213

TỔNG CỘNG NGUỒN VỐN (440 = 300 + 400)
Số cuối năm: 81.510.550.856.141
Số đầu năm: 63.438.713.441.528

BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
'''
    result = make_pipeline().parse_text(raw)
    nm = nmap(result['canonical'])
    assert nm['ASSET.CURRENT']['value']['current'] == '58.015.996.839.126'
    assert nm['ASSET.CURRENT']['value']['previous'] == '48.680.623.561.824'
    assert nm['TOTAL_ASSETS']['value']['current'] == '81.510.550.856.141'
    assert nm['TOTAL_LIABILITIES']['value']['current'] == '38.672.356.541.926'
    assert nm['TOTAL_EQUITY']['value']['current'] == '42.838.194.314.215'
    assert nm['TOTAL_LIABILITIES_AND_EQUITY']['value']['current'] == '81.510.550.856.141'
