from flat_parser.qa import classify_unknown_financial_label, detect_sector
from flat_parser.semantic_catalog import SemanticCatalog
from flat_parser.alias_matcher import match_candidates
from flat_parser.models import StructuralNode
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _catalog():
    return SemanticCatalog(
        ROOT / 'resources/schemas/financial_position_schema.json',
        ROOT / 'resources/schemas/financial_position_aliases.json',
    )


def _node(label):
    return StructuralNode(
        node_index=0, line_no=1, raw_text=label, text=label, indent=0,
        is_bullet=False, bullet_marker=None, representation='plain',
        label_text=label, pattern_id='SP_LABEL_VALUE_INLINE',
    )


def test_enterprise_short_borrowing_alias_is_sector_guarded():
    c = _catalog(); n = _node('Vay ngắn hạn')
    ent = match_candidates(n, [n], c, [], detected_sector='enterprise')
    sec = match_candidates(n, [n], c, [], detected_sector='securities')
    assert any(x.node_id == 'LIABILITY.BORROWINGS.SHORT_TERM' for x in ent)
    assert not any(x.node_id == 'LIABILITY.BORROWINGS.SHORT_TERM' for x in sec)


def test_bank_other_asset_provision_alias_is_sector_guarded():
    c = _catalog(); n = _node('Các khoản dự phòng rủi ro cho các tài sản Có nội bảng khác')
    bank = match_candidates(n, [n], c, [], detected_sector='bank')
    ent = match_candidates(n, [n], c, [], detected_sector='enterprise')
    assert any(x.node_id == 'ASSET.OTHER.ALLOWANCE' for x in bank)
    assert not any(x.node_id == 'ASSET.OTHER.ALLOWANCE' for x in ent)


def test_residual_headers_and_addresses_are_noise():
    for label in [
        'STT Chỉ tiêu',
        'Báo cáo tình hình tài chính hợp nhất tại ngày 31 tháng 12 năm 2025',
        'Mạc Đĩnh Chi, phường Sài Gòn',
        'Lý Thường Kiệt, phường Cửa Nam, Hà Nội',
        'Hậu Giang, P. Bình Tây, TP. Hồ Chí Minh',
        'Trần Quang Khải, Hoàn Kiếm, Hà Nội',
        'Ngày 31 tháng 12 năm 2014 của Ngân hàng Nhà nước',
    ]:
        assert classify_unknown_financial_label(label, 'enterprise') == 'noise'


def test_insurance_sector_is_detected_and_classified_as_schema_gap():
    c = _catalog()
    text = 'Công ty bảo hiểm\nDự phòng bồi thường\nDự phòng toán học\nTài sản tái bảo hiểm'
    sector = detect_sector(text, c)
    assert sector['detected_sector'] == 'insurance'
    assert sector['schema_sector_gap'] == 'insurance'
    assert classify_unknown_financial_label('Dự phòng bồi thường', 'insurance') == 'likely_schema_gap:insurance'
