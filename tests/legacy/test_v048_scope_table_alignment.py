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


def node_map(doc):
    return {n['node_id']: n for n in doc['nodes']}


def test_inline_reporting_date_title_is_valid_scope_start():
    raw = '''
BÁO CÁO KIỂM TOÁN ĐỘC LẬP
Chúng tôi đã kiểm toán báo cáo tài chính hợp nhất.

Bảng cân đối kế toán hợp nhất tại ngày 31 tháng 12 năm 2025
| Mã số | Thuyết minh | 31/12/2025 VND | 1/1/2025 VND |
|---|---|---|---|
| 270 | TỔNG CỘNG TÀI SẢN | 100 | 90 |
| 440 | TỔNG CỘNG NGUỒN VỐN | 100 | 90 |

Báo cáo kết quả hoạt động kinh doanh hợp nhất cho năm 2025
'''
    lines = normalize_lines(raw)
    start, end, debug = financial_position_scope(lines)
    selected = next(x.clean for x in lines if x.line_no == start)
    assert selected.startswith('Bảng cân đối kế toán hợp nhất tại ngày')
    assert debug['mode'] == 'validated_financial_position'
    assert end > start


def test_table_missing_label_header_does_not_shift_code_note_into_values():
    raw = '''
Bảng cân đối kế toán hợp nhất tại ngày 31 tháng 12 năm 2025
| Mã số | Thuyết minh | 31/12/2025 VND | 1/1/2025 VND |
|---|---|---|---|
| | TÀI SẢN | | |
| | Tài sản ngắn hạn | 100 | 59.561 | 59.543 |
| | Tiền và các khoản tương đương tiền | 110 | 5 | 10.675 | 14.933 |
| | Tiền | 111 | | 7.700 | 5.329 |
| | TỔNG CỘNG TÀI SẢN | 270 | 85.855 | 81.274 |
| | NỢ PHẢI TRẢ | 300 | 56.294 | 51.967 |
| | VỐN CHỦ SỞ HỮU | 400 | 29.561 | 29.307 |
| | TỔNG CỘNG NGUỒN VỐN | 440 | 85.855 | 81.274 |
'''
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result['canonical'])
    assert nodes['ASSET.CURRENT']['value']['current'] == '59.561'
    assert nodes['ASSET.CURRENT']['value']['previous'] == '59.543'
    assert nodes['ASSET.CASH_EQUIV']['value']['current'] == '10.675'
    assert nodes['ASSET.CASH_EQUIV']['value']['previous'] == '14.933'
    assert nodes['ASSET.CASH_EQUIV']['value']['note'] == '5'


def test_bank_table_note_column_is_not_current_value():
    raw = '''
Báo cáo tình hình tài chính hợp nhất tại ngày 31 tháng 12 năm 2025
| Thuyết minh | 31/12/2025 Triệu VND | 31/12/2024 Triệu VND |
|---|---|---|
| Vốn chủ sở hữu | 22 | 59.866.744 | 54.972.070 |
| TỔNG VỐN CHỦ SỞ HỮU | | 59.866.744 | 54.972.070 |
| TỔNG NỢ PHẢI TRẢ | | 857.253.059 | 693.122.476 |
| TỔNG NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU | | 917.119.803 | 748.094.546 |
'''
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result['canonical'])
    assert nodes['TOTAL_EQUITY']['value']['current'] == '59.866.744'
    assert nodes['TOTAL_EQUITY']['value']['previous'] == '54.972.070'
    assert nodes['TOTAL_EQUITY']['value']['current'] != '22'


def test_explicit_period_occurrences_are_not_consolidated_as_positional_rows():
    raw = '''
Bảng cân đối kế toán hợp nhất tại ngày 31 tháng 12 năm 2025
* 31/12/2025
    * VỐN CHỦ SỞ HỮU
        * Tổng cộng: 22.999
* 1/1/2025
    * VỐN CHỦ SỞ HỮU
        * Tổng cộng: 24.437
* TỔNG CỘNG TÀI SẢN
    * Số cuối năm: 32.597
    * Số đầu năm: 33.439
* TỔNG CỘNG NGUỒN VỐN
    * Số cuối năm: 32.597
    * Số đầu năm: 33.439
'''
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result['canonical'])
    assert nodes['TOTAL_EQUITY']['value']['current'] == '22.999'
    assert nodes['TOTAL_EQUITY']['value']['previous'] == '24.437'


def test_plain_total_heading_with_two_summary_siblings_is_positional_pair():
    raw = '''
Bảng cân đối kế toán hợp nhất tại ngày 31 tháng 12 năm 2025
Năm 2025
Năm 2024

### TỔNG TÀI SẢN
* Tổng: 32.597
* Tổng: 33.439
'''
    result = make_pipeline().parse_text(raw)
    total = node_map(result['canonical'])['TOTAL_ASSETS']
    assert total['value']['current'] == '32.597'
    assert total['value']['previous'] == '33.439'
