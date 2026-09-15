from src.value_semantics import detect_statement_unit, is_note_reference, arithmetic_value
from src.source_statement_recovery import parse_number, extract_financial_position_source_rows
from src.income_observation_patch import extract_income_fallback


def test_dash_is_null_and_zero_is_zero():
    assert parse_number("-") is None
    assert parse_number("—") is None
    assert parse_number("0") == 0
    assert arithmetic_value(None) == 0


def test_note_reference_grammar():
    for x in ["28", "VI.02", "V.03.3", "V.4(a)", "V.12(b)"]:
        assert is_note_reference(x)


def test_unit_detection_no_conversion():
    assert detect_statement_unit("Đơn vị tính: Triệu VND").unit == "million_vnd"
    assert detect_statement_unit("| Chỉ tiêu | 2025 VND | 2024 VND |").unit == "vnd"
    assert parse_number("21.100.000") == 21100000
    # Mixed declaration where currency must take precedence over %
    assert detect_statement_unit("**Đơn vị tính:** triệu đồng, %").unit == "million_vnd"
    assert detect_statement_unit("Không có đơn vị", fallback_unit="million_vnd").unit == "million_vnd"
    from src.value_semantics import detect_document_unit
    doc_sample = "# BÁO CÁO TÀI CHÍNH KIỂM TOÁN\nĐơn vị tính: VND\nNội dung báo cáo..."
    assert detect_document_unit(doc_sample).unit == "vnd"


def test_fpt_extreme_if_fixture_present():
    from pathlib import Path
    p=Path("tests/md_test/FPT_BCTC_2025_extreme_stress_test.md")
    if not p.exists(): return
    text=p.read_text(encoding="utf-8")
    fp=extract_financial_position_source_rows(text,2025,2024)
    r240=[r for r in fp["rows"] if r.code=="240"]
    assert any(r.current==1100000 and r.previous==850000 for r in r240)
    inc=extract_income_fallback(text,2025,2024)
    r02=[r for r in inc["rows"] if r.get("code")=="02" and "giảm trừ" in r.get("indicator","").lower()]
    assert any(r.get("note")=="VI.02" and r.get("current")=="(320.000)" and r.get("previous")=="(280.000)" for r in r02)
