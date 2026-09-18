from pathlib import Path

from flat_parser.statement_locator import StatementLocator


ROOT = Path(__file__).resolve().parents[2]


def _locator(profile: str) -> StatementLocator:
    schema = ROOT / "resources" / "schemas" / {
        "financial_position": "financial_position_schema.json",
        "income_statement": "income_statement_schema.json",
        "cash_flow": "cash_flow_schema.json",
    }[profile]
    aliases = ROOT / "resources" / "schemas" / {
        "financial_position": "financial_position_aliases.json",
        "income_statement": "income_statement_aliases.json",
        "cash_flow": "cash_flow_aliases.json",
    }[profile]
    return StatementLocator(schema_path=schema, aliases_path=aliases)


def test_locator_ignores_repeated_statement_title_in_table_of_contents():
    text = """
**MỤC LỤC**
4. Bảng cân đối kế toán hợp nhất tại ngày 31 tháng 12 năm 2025
    6-9
5. Báo cáo kết quả hoạt động kinh doanh hợp nhất
    10
---
# Page 6
## Metadata
## Content
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
Đơn vị tính: Đồng
**TÀI SẢN** | 100 |  | 1.000 | 900
**Tiền và các khoản tương đương tiền** | 110 |  | 100 | 90
**NỢ PHẢI TRẢ** | 300 |  | 500 | 450
**VỐN CHỦ SỞ HỮU** | 400 |  | 500 | 450
"""
    result = _locator("financial_position").locate(text, profile="financial_position")

    selected = result["selected_scope"]
    assert selected is not None
    assert selected["start_line"] > 6
    assert result["fallback_used"] is False
    assert any("Tiền và các khoản tương đương tiền" in row["raw_text"] for row in result["candidate_rows"])


def test_locator_returns_candidate_rows_without_mapping_them():
    text = """
# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
Đơn vị tính: triệu đồng
Thu nhập lãi và các khoản thu nhập tương tự | 13.604.093 | 9.027.696
Chi phí lãi và các chi phí tương tự | (8.515.301) | (5.992.439)
Thu nhập lãi thuần | 5.088.792 | 3.035.257
Lợi nhuận sau thuế | 2.808.626 | 585.556
"""
    result = _locator("income_statement").locate(text, profile="income_statement")

    assert result["selected_scope"] is not None
    assert result["selected_scope"]["start_line"] == 2
    assert result["candidate_rows"]
    assert all(row["matched_node_ids"] for row in result["candidate_rows"])
    assert all("mapping" not in row for row in result["candidate_rows"])


def test_locator_can_fallback_when_evidence_is_insufficient():
    text = """
Một đoạn văn có nhắc đến tài sản nhưng không có tiêu đề bảng.
Tài sản có thể thay đổi theo chính sách kế toán.
"""
    result = _locator("financial_position").locate(text, profile="financial_position")

    assert result["selected_scope"] is None
    assert result["fallback_used"] is True

