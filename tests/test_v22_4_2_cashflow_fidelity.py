from pathlib import Path
import json
import tempfile

from src.b03_cashflow import CashFlowMapper, adapt_cashflow_row, extract_cashflow_fallback
from src.common import extract_generic_statement_rows
from src.b02_income.mapper import parse_number as parse_income_number


def test_dash_is_null_not_zero():
    assert parse_income_number('-') is None
    assert parse_income_number('—') is None
    assert parse_income_number('0') == 0


def test_generic_pipe_preserves_dash_period_position():
    text = '''
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ
| Chỉ tiêu | Mã số | TM | 2025 VND | 2024 VND |
|---|---:|---:|---:|---:|
| Tiền chi tiền gửi có kỳ hạn | 23 | | - | (3.620.022.795.913) |
| Tiền thu từ tiền gửi có kỳ hạn | 24 | | 2.232.419.883.915 | - |
'''
    rows = extract_generic_statement_rows(text, 1, len(text.splitlines()), 2025, 2024, 'CASHFLOW')
    r23 = next(r for r in rows if r.code == '23')
    r24 = next(r for r in rows if r.code == '24')
    assert r23.current is None and r23.previous == -3620022795913
    assert r24.current == 2232419883915 and r24.previous is None


def test_translation_difference_is_reconciliation_and_maps(tmp_path: Path):
    text = '''
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ
### Phương pháp gián tiếp
**Mẫu B 03 - DN/HN**
| Chỉ tiêu | Mã số | Thuyết minh | 2025 VND | 2024 VND |
|---|---:|---:|---:|---:|
| Lợi nhuận trước thuế | 01 | | 100 | 90 |
| Lưu chuyển tiền thuần từ hoạt động kinh doanh | 20 | | 50 | 40 |
| Lưu chuyển tiền thuần từ hoạt động đầu tư | 30 | | (10) | (9) |
| Lưu chuyển tiền thuần từ hoạt động tài chính | 40 | | (5) | (4) |
| Lưu chuyển tiền thuần trong năm | 50 | | 35 | 27 |
| Tiền và tương đương tiền đầu năm | 60 | | 100 | 70 |
| Ảnh hưởng của thay đổi tỷ giá | 61 | | 2 | 1 |
| Chênh lệch quy đổi tiền tệ | 62 | | 3 | 2 |
| Tiền và tương đương tiền cuối năm | 70 | | 140 | 100 |
'''
    ext = extract_cashflow_fallback(text, 2025, 2024, fallback_unit='vnd')
    row62 = next(x for x in ext['rows'] if str(x.get('code')) == '62')
    assert row62['section'] == 'reconciliation'

    root = Path(__file__).resolve().parents[1]
    mapper = CashFlowMapper(root/'resources/cash_flow_schema.json', root/'resources/cash_flow_aliases.json', sector='enterprise', method='indirect')
    mapped = mapper.map_rows([adapt_cashflow_row(x) for x in ext['rows']])
    r62 = next(r for r in mapped if r.code == '62')
    assert r62.mapping_status == 'mapped'
    assert r62.mapped_node_id == 'CASHFLOW.ENTERPRISE.TRANSLATION_DIFFERENCE'


def test_short_ma_field_keeps_bullet_cashflow_row():
    text = '''
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
(Theo phương pháp gián tiếp)
Mẫu B 03 - DN/HN
* **I. LƯU CHUYỂN TIỀN TỆ TỪ HOẠT ĐỘNG KINH DOANH**
* **1. Lợi nhuận trước thuế**
    * Mã: 01
    * Năm nay: 396.844.169.100
    * Năm trước: 595.916.748.469
'''
    ext = extract_cashflow_fallback(text, 2025, 2024, fallback_unit='vnd')
    row = next(r for r in ext['rows'] if r['code'] == '01')
    assert row['source_label'] == 'Lợi nhuận trước thuế'
    assert (row['current'], row['previous']) == (396844169100, 595916748469)
