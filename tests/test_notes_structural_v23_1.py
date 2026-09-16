from src.notes.pipeline import parse_notes


def _rows(ir):
    out=[]
    for s in ir['sections']:
        for b in s['blocks']:
            out.extend(b.get('rows') or [])
    return out


def test_plain_numbered_heading_and_bullet_period_pair():
    text='''
BẢN THUYẾT MINH BÁO CÁO TÀI CHÍNH HỢP NHẤT
V. THÔNG TIN BỔ SUNG
1. **Tiền và các khoản tương đương tiền**
    * Số cuối năm:
        * Tiền mặt: 1.525.654.580 đồng
        * Tiền gửi ngân hàng: 32.535.422.421 đồng
        * Cộng: 34.061.077.001 đồng
    * Số đầu năm:
        * Tiền mặt: 397.752.286 đồng
        * Tiền gửi ngân hàng: 53.092.446.909 đồng
        * Cộng: 53.490.199.195 đồng
'''
    ir=parse_notes(text,source_name='ANV.md',sector='enterprise')
    rows=_rows(ir)
    labels={r['label_normalized'] for r in rows}
    assert 'tien mat' in labels
    cash=next(r for r in rows if r['label_normalized']=='tien mat')
    roles={v['period_role']:v['normalized'] for v in cash['values']}
    assert roles['current']==1525654580
    assert roles['previous']==397752286


def test_multirow_markdown_header_not_emitted_as_data():
    text='''
THUYẾT MINH BÁO CÁO TÀI CHÍNH
## 43. PHÂN TÍCH QUÁ HẠN
|                    | **Quá hạn** |              |            |             |
| :----------------- | :---------- | :----------- | :--------- | :---------- |
|                    | Dưới 90 ngày | Từ 91 đến 180 ngày | Từ 181 đến 360 ngày | Trên 360 ngày | Tổng cộng |
|                    | Triệu đồng | Triệu đồng | Triệu đồng | Triệu đồng | Triệu đồng |
| Cho vay khách hàng | 261 | 181 | 1.015 | - | 1.457 |
'''
    ir=parse_notes(text,source_name='ABB.md',sector='bank')
    rows=_rows(ir)
    assert len(rows)==1
    assert rows[0]['label_normalized']=='cho vay khach hang'
    assert len(rows[0]['values'])==5


def test_numbered_disclosure_items_do_not_open_note_sections_and_refs_are_unique():
    text='''
THUYẾT MINH BÁO CÁO TÀI CHÍNH
## 1. ĐẶC ĐIỂM HOẠT ĐỘNG
1. **Tên công ty:** Công ty thử nghiệm
    * **Được thành lập theo:** một quyết định
2. **Công ty liên doanh**
    * **STT:** 1
## 2. CHÍNH SÁCH KẾ TOÁN
    2.1. Cơ sở lập báo cáo
        * Theo nguyên tắc giá gốc.
'''
    ir = parse_notes(text, source_name='identity.md', sector='enterprise')
    sections = ir['sections']
    titles = {s['title_raw'] for s in sections}

    assert 'Tên công ty: Công ty thử nghiệm' not in titles
    assert 'Công ty liên doanh' not in titles
    assert any(s['note_id_normalized'] == '2.1' for s in sections)
    assert len({s['section_ref'] for s in sections}) == len(sections)
    block_ids = [b['block_id'] for s in sections for b in s['blocks']]
    assert len(set(block_ids)) == len(block_ids)
