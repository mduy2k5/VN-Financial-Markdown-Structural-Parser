from pathlib import Path

from flat_parser.document import build_nodes
from flat_parser.preprocess import filter_noise
from flat_parser.textnorm import normalize_lines
from flat_parser.tables import detect_tables
from flat_parser.guide import UniversalGuide
from flat_parser.structural_classifier import StructuralClassifier

ROOT = Path(__file__).resolve().parents[1]
GUIDE = UniversalGuide(ROOT / 'resources' / 'universal_structural_guide_a1_a5.json')


def _node(text):
    lines = filter_noise(normalize_lines(text))
    _, table_map = detect_tables(lines)
    nodes = build_nodes(lines, table_map, GUIDE)
    StructuralClassifier(GUIDE).classify_all(nodes)
    return nodes[0]


def test_compact_row_code_current_previous():
    n = _node('III. Các khoản phải thu ngắn hạn 130 4.260.806.610.198 2.252.910.212.253')
    assert n.label_text == 'Các khoản phải thu ngắn hạn'
    assert n.code == '130'
    assert n.note is None
    assert [v.raw_value for v in n.values] == ['4.260.806.610.198', '2.252.910.212.253']
    assert n.pattern_id == 'SP_CODE_NOTE_PERIOD_INLINE_ROW'


def test_compact_row_code_note_current_previous():
    n = _node('1. Chi phí trả trước ngắn hạn 151 13 32.309.453.139 24.815.192.830')
    assert n.label_text == 'Chi phí trả trước ngắn hạn'
    assert n.code == '151'
    assert n.note == '13'
    assert [v.raw_value for v in n.values] == ['32.309.453.139', '24.815.192.830']
    assert n.pattern_id == 'SP_CODE_NOTE_PERIOD_INLINE_ROW'


def test_compact_row_rejects_report_header():
    n = _node('Báo cáo tình hình tài chính hợp nhất tại ngày 31 tháng 12 năm 2025 100 1.234.567 2.345.678')
    assert n.pattern_id != 'SP_CODE_NOTE_PERIOD_INLINE_ROW'


def test_compact_row_rejects_formula():
    n = _node('Công thức tính 270 100 200')
    assert n.pattern_id != 'SP_CODE_NOTE_PERIOD_INLINE_ROW'
