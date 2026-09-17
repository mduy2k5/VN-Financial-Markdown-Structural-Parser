from flat_parser.context import financial_position_scope
from flat_parser.textnorm import normalize_lines


def test_toc_is_not_selected():
    raw = '''
# Page 2
MỤC LỤC
Trang
Báo cáo tình hình tài chính hợp nhất
6 - 8
Báo cáo kết quả hoạt động hợp nhất
9
Báo cáo lưu chuyển tiền tệ hợp nhất
10 - 11

# Page 8
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
tại ngày 31 tháng 12 năm 2025
B02/TCTD-HN
TÀI SẢN
* Tiền mặt
    * Số cuối năm: 493.695 triệu đồng
    * Số đầu năm: 315.917 triệu đồng

# Page 11
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
cho năm tài chính kết thúc ngày 31 tháng 12 năm 2025
B03/TCTD-HN
'''
    lines = normalize_lines(raw)
    start, end, debug = financial_position_scope(lines)
    toc = min(debug['candidates'], key=lambda x: x['line_no'])
    assert toc['score'] < 4
    assert start > toc['line_no']
    b03 = next(x.line_no for x in lines if 'BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT' in x.clean.upper() and x.line_no > start)
    assert end == b03 - 1


def test_real_statement_has_positive_evidence():
    raw = '''
MỤC LỤC
Báo cáo tình hình tài chính hợp nhất
6 - 8

BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
tại ngày 31 tháng 12 năm 2025
B02/TCTD-HN
TÀI SẢN
'''
    lines = normalize_lines(raw)
    start, _, debug = financial_position_scope(lines)
    chosen = next(x for x in debug['candidates'] if x['line_no'] == start)
    assert chosen['score'] >= 4
    assert 'near_form_code:+3' in chosen['evidence']
    assert 'near_reporting_date:+2' in chosen['evidence']


def test_audit_prose_mention_is_not_statement_heading():
    raw = '''
BÁO CÁO KIỂM TOÁN ĐỘC LẬP
Chúng tôi đã kiểm toán báo cáo tài chính hợp nhất, bao gồm báo cáo tình hình tài chính hợp nhất tại ngày 31 tháng 12 năm 2025, báo cáo kết quả hoạt động hợp nhất và báo cáo lưu chuyển tiền tệ hợp nhất.

BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
tại ngày 31 tháng 12 năm 2025
B02/TCTD-HN
TÀI SẢN
'''
    lines = normalize_lines(raw)
    start, _, debug = financial_position_scope(lines)
    selected = next(x for x in lines if x.line_no == start)
    assert selected.clean == 'BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT'
    assert all('Chúng tôi đã kiểm toán' not in x['text'] for x in debug['candidates'])
