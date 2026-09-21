from pathlib import Path
import json
import tempfile

from src.b03_cashflow import CashFlowMapper, adapt_cashflow_row, extract_cashflow_fallback
from src.common import extract_code_period_table, extract_generic_statement_rows
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


def test_code_period_evidence_preserves_dash_period_position():
    text = '''
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ
| Mã số | 2025 VND | 2024 VND |
|---:|---:|---:|
| 17 | - | (10.000.000.000) |
| 36 | (54.283.249.510) | - |
'''
    rows = extract_code_period_table(text, 1, len(text.splitlines()), 2025, 2024)
    r17 = next(r for r in rows if r['code'] == '17')
    r36 = next(r for r in rows if r['code'] == '36')
    assert r17['current'] is None and r17['previous'] == -10000000000
    assert r36['current'] == -54283249510 and r36['previous'] is None


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

    root = Path(__file__).resolve().parents[2]
    mapper = CashFlowMapper(root/'resources/schemas/cash_flow_schema.json', root/'resources/schemas/cash_flow_aliases.json', sector='enterprise', method='indirect')
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


def test_sibling_period_values_are_not_attached_to_previous_child():
    """B03 phải tôn trọng indent khi parent có tổng không gắn nhãn."""

    text = '''
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ
Phương pháp gián tiếp
Mẫu B03-CTCK
* 1. LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG KINH DOANH
    * 02. Điều chỉnh cho các khoản:
        * 08. Dự thu tiền lãi
            * Năm nay: (8.972.897.043)
            * Năm trước: (8.355.631.386)
        * Năm nay: (233.662.533.028)
        * Năm trước: (106.577.700.028)
'''

    ext = extract_cashflow_fallback(text, 2025, 2024, fallback_unit='vnd')
    row = next(x for x in ext['rows'] if x['code'] == '08')

    assert row['current'] == -8972897043
    assert row['previous'] == -8355631386
    assert row['parent_label'] == '02. Điều chỉnh cho các khoản'
    assert '02. Điều chỉnh cho các khoản' in row['hierarchy_path']


def test_payment_label_does_not_fuzzy_map_to_receipts():
    text = '''
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
(Theo phương pháp gián tiếp)
Mẫu B 03 - DN/HN
* Tiền chi khác từ hoạt động kinh doanh: (10.000.000.000) đồng
'''
    ext = extract_cashflow_fallback(text, 2025, 2024, fallback_unit='vnd')
    root = Path(__file__).resolve().parents[2]
    mapper = CashFlowMapper(
        root / 'resources/schemas/cash_flow_schema.json',
        root / 'resources/schemas/cash_flow_aliases.json',
        sector='enterprise',
        method='indirect',
    )
    row = mapper.map_rows([adapt_cashflow_row(ext['rows'][0])])[0]

    assert row.mapping_status == 'mapped'
    assert row.mapped_node_id == 'CASHFLOW.ENTERPRISE.INDIRECT.OTHER_OPERATING_PAYMENTS'


def test_unique_form_code_disambiguates_detached_reconciliation_row():
    text = '''
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
(Theo phương pháp gián tiếp)
Mẫu B 03 - DN/HN
| Chỉ tiêu | Mã số | 2025 VND | 2024 VND |
|---|---:|---:|---:|
| Tiền và tương đương tiền đầu năm | 60 | 100 | 90 |
'''
    ext = extract_cashflow_fallback(text, 2025, 2024, fallback_unit='vnd')
    root = Path(__file__).resolve().parents[2]
    mapper = CashFlowMapper(
        root / 'resources/schemas/cash_flow_schema.json',
        root / 'resources/schemas/cash_flow_aliases.json',
        sector='enterprise',
        method='indirect',
    )
    row = mapper.map_rows([adapt_cashflow_row(ext['rows'][0])])[0]

    assert row.mapping_status == 'mapped'
    assert row.mapped_node_id == 'CASHFLOW.ENTERPRISE.CASH_BEGINNING'
    assert row.mapping_method == 'form_code_disambiguation'


def test_semantic_fallback_does_not_cross_cashflow_form_code_boundary():
    """Mã 103 cuối năm không được kéo vào child 101.2 đầu năm."""

    root = Path(__file__).resolve().parents[2]
    mapper = CashFlowMapper(
        root / 'resources/schemas/cash_flow_schema.json',
        root / 'resources/schemas/cash_flow_aliases.json',
        sector='securities',
        method='indirect',
    )
    row = adapt_cashflow_row({
        'source_label': 'Tiền và các khoản tương đương tiền cuối năm',
        'code': '103',
        'current': 1064105925053,
        'previous': 284434076341,
        'section': 'reconciliation',
    })

    mapped = mapper.map_rows([row])[0]

    assert mapped.mapping_status == 'unmapped'
    assert mapped.mapped_node_id is None
