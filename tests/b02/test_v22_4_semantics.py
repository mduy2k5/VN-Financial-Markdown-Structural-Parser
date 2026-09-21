from src.common import (
    arithmetic_value,
    detect_statement_unit,
    extract_financial_position_source_rows,
    is_note_reference,
    parse_number,
)
from src.b02_income import extract_income_fallback, parse_period_line


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
    # Khai báo trộn trong đó đơn vị tiền tệ phải được ưu tiên hơn %.
    assert detect_statement_unit("**Đơn vị tính:** triệu đồng, %").unit == "million_vnd"
    assert detect_statement_unit("Không có đơn vị", fallback_unit="million_vnd").unit == "million_vnd"
    from src.common import detect_document_unit
    doc_sample = "# BÁO CÁO TÀI CHÍNH KIỂM TOÁN\nĐơn vị tính: VND\nNội dung báo cáo..."
    assert detect_document_unit(doc_sample).unit == "vnd"


def test_cumulative_quarter_previous_is_not_current_period():
    assert parse_period_line("Luỹ kế từ đầu năm đến cuối quý: 22.356.378", 2025, 2024) == (
        "current", 30, "22.356.378"
    )
    assert parse_period_line("Luỹ kế từ đầu năm đến cuối quý trước: 17.411.707", 2025, 2024) == (
        "previous", 30, "17.411.707"
    )


def test_extreme_structural_rows_and_income_fallback():
    text = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
**Đơn vị tính: Triệu VND**
| TÀI SẢN DÀI HẠN | Mã số | TM | 31/12/2025 | 01/01/2025 |
|---|---:|---:|---:|---:|
| Tài sản dở dang dài hạn | 240 | V.09 | 1.100.000 | 850.000 |

# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT
Các khoản giảm trừ doanh thu  
02  
VI.02  
(320.000)  
(280.000)
"""
    fp=extract_financial_position_source_rows(text,2025,2024)
    r240=[r for r in fp["rows"] if r.code=="240"]
    assert any(r.current==1100000 and r.previous==850000 for r in r240)
    inc=extract_income_fallback(text,2025,2024)
    r02=[r for r in inc["rows"] if r.get("code")=="02" and "giảm trừ" in r.get("indicator","").lower()]
    assert any(r.get("note")=="VI.02" and r.get("current")=="(320.000)" and r.get("previous")=="(280.000)" for r in r02)


def test_financial_position_positional_columns_follow_source_header_order():
    """Không mặc định số đầu tiên là kỳ hiện tại khi header bị đảo."""

    text = """
# BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
NGUỒN VỐN
Số đầu năm
(Trình bày lại)
Số cuối năm
Mã Thuyết
số mình
C. NỢ PHẢI TRẢ
300
27.563.291.053.672
25.567.783.329.754
"""
    result = extract_financial_position_source_rows(text, 2025, 2024)
    row = next(item for item in result["rows"] if item.code == "300")

    assert row.previous == 27_563_291_053_672
    assert row.current == 25_567_783_329_754


def test_financial_position_positional_rows_skip_standalone_code_and_formula():
    """Mã số đứng riêng/ghi chú công thức không được đọc thành giá trị kỳ."""

    filler = "\n".join(f"Ghi chú trang {index}" for index in range(120))
    text = f"""
# BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
NGUỒN VỐN
Số đầu năm
(Trình bày lại)
Số cuối năm
Mã Thuyết minh
số mình
C. NỢ PHẢI TRẢ
{filler}
10. Quỹ khen thưởng, phúc lợi
322
37.315.781.858
45.639.872.404
TÔNG CỘNG NGUỒN VỐN
440
36.722.431.033.992
(440 = 300 + 400)
37.524.891.642.819
"""

    rows = extract_financial_position_source_rows(text, 2025, 2024)["rows"]
    fund = next(row for row in rows if row.code == "322")
    total = next(row for row in rows if row.code == "440")

    assert fund.previous == 37_315_781_858
    assert fund.current == 45_639_872_404
    assert total.previous == 36_722_431_033_992
    assert total.current == 37_524_891_642_819


def test_income_rows_keep_parent_child_context_for_repeated_labels():
    text = """
# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
Mẫu B02-DN
* Doanh thu bán hàng và cung cấp dịch vụ
    * Năm nay: 100
    * Năm trước: 90
    * Doanh thu bán hàng và cung cấp dịch vụ
        * Năm nay: 40
        * Năm trước: 30
"""

    rows = extract_income_fallback(text, 2025, 2024)["rows"]
    child = next(row for row in rows if row.get("current") == "40")

    assert child["parent_context"] == "Doanh thu bán hàng và cung cấp dịch vụ"
    assert child["hierarchy_path"] == "Doanh thu bán hàng và cung cấp dịch vụ"
