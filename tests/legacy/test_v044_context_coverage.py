from pathlib import Path

from flat_parser.pipeline import FlatParserPipeline

ROOT = Path(__file__).resolve().parents[2]


def make_pipeline():
    return FlatParserPipeline(
        schema_path=ROOT / 'resources/schemas/financial_position_schema.json',
        aliases_path=ROOT / 'resources/schemas/financial_position_aliases.json',
        universal_guide_path=ROOT / 'resources/guides/compiled/structural_guide.json',
    )


def node_map(doc):
    return {x['node_id']: x for x in doc['nodes']}


def test_same_label_gross_requires_actual_tree_parent_not_previous_sibling():
    raw = '''
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Chứng khoán kinh doanh
    * Năm 2025: 100
    * Năm 2024: 90
    * Chứng khoán kinh doanh: 100
    * Chứng khoán kinh doanh: 90
'''
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result['canonical'])

    parent = nodes['ASSET.FIN_INV.TRADING_SECURITIES']
    gross = nodes['ASSET.FIN_INV.TRADING_SECURITIES.GROSS']

    assert parent['value']['current'] == '100'
    assert parent['value']['previous'] == '90'
    assert gross['value']['current'] == '100'
    assert gross['value']['previous'] == '90'


def test_repeated_siblings_do_not_flip_into_gross_without_same_tree_parent():
    raw = '''
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

* Chứng khoán đầu tư
    * Chứng khoán đầu tư sẵn sàng để bán: 12.643.232
    * Chứng khoán đầu tư sẵn sàng để bán: 9.400.555
'''
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result['canonical'])

    afs = nodes['ASSET.FIN_INV.AFS']
    gross = nodes['ASSET.FIN_INV.AFS.GROSS']

    assert afs['value']['current'] == '12.643.232'
    assert afs['value']['previous'] == '9.400.555'
    assert gross['value']['current'] is None
    assert gross['value']['previous'] is None


def test_dual_role_wrapper_has_no_duplicate_values_inside_occurrence():
    raw = '''
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

**C - NỢ PHẢI TRẢ**
* Chỉ tiêu: 300
    * Số cuối năm: 2.297.846
    * Số đầu năm: 2.068.623
'''
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result['canonical'])
    total = nodes['TOTAL_LIABILITIES']

    assert total['value']['current'] == '2.297.846'
    assert total['value']['previous'] == '2.068.623'
    occ = total['extraction_meta']['occurrences'][0]
    assert len(occ['values']) == 2


def test_flat_table_sibling_context_resolves_asset_repo():
    raw = '''
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
Năm 2025
Năm 2024

| Chỉ tiêu | Mã số | Năm 2025 | Năm 2024 |
| --- | --- | --- | --- |
| Tài sản ngắn hạn khác | 150 | 10 | 9 |
| Giao dịch mua bán lại trái phiếu Chính phủ | 154 | - | - |
'''
    result = make_pipeline().parse_text(raw)
    nodes = node_map(result['canonical'])
    asset_repo = nodes['ASSET.OTHER.GOV_BOND_REPO']
    liability_repo = nodes['LIABILITY.GOV_BOND_REPO']

    assert asset_repo['value']['current'] == '-'
    assert asset_repo['value']['previous'] == '-'
    assert liability_repo['value']['current'] is None
