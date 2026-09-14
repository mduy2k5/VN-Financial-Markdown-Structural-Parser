from flat_parser.qa import classify_unknown_financial_label


def test_period_headers_are_noise():
    cases = [
        "Số đầu năm (Trình bày lại)",
        "31/12/2024 Triệu VND (đã kiểm toán)",
        "Tại 31/12/2025",
        "Tại 31/12/2024",
        "Ngày 31.12.2025",
        "(31/12/2025)",
        "Cho năm tài chính kết thúc ngày 31 tháng 12 năm 2025",
    ]
    for x in cases:
        assert classify_unknown_financial_label(x, "bank") == "noise", x


def test_unit_table_and_form_headers_are_noise():
    cases = [
        "đồng", "STT", "Tên chỉ tiêu", "Số liệu", "Số liệu (Trình bày lại)",
        "Mẫu số B 01-DN/HN", "Ngày 22 tháng 12 năm 2014 của Bộ Tài chính",
        "Địa chỉ",
    ]
    for x in cases:
        assert classify_unknown_financial_label(x, "enterprise") == "noise", x


def test_real_business_gaps_remain_actionable_or_schema_gap():
    assert classify_unknown_financial_label("Chứng khoán đầu tư", "bank") == "likely_alias_or_schema_gap"
    assert classify_unknown_financial_label("Cam kết bán ngoại tệ", "bank") == "likely_schema_gap:off_balance"
    assert classify_unknown_financial_label("Các tài sản tài chính ghi nhận thông qua lãi/lỗ (FVTPL)", "securities") == "likely_schema_gap:securities"


def test_inline_serialized_business_row_is_structural_gap():
    x = "Các khoản phải thu ngắn hạn 130 4.260.806.610.198 2.252.910.212.253"
    assert classify_unknown_financial_label(x, "enterprise") == "likely_structural_gap"
