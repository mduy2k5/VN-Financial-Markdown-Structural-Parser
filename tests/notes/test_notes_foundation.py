from src.notes.pipeline import parse_notes
from src.notes.scanner import detect_notes_scope
from src.notes.sectionizer import normalize_note_id


def test_note_id_normalization_preserves_semantics():
    assert normalize_note_id("V.01") == "V.1"
    assert normalize_note_id("V.04(a)") == "V.4(a)"
    assert normalize_note_id("VI.02") == "VI.2"


def test_sticky_scope_does_not_exit_on_primary_decoy():
    text = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH
| Chỉ tiêu | 2025 | 2024 |
|---|---:|---:|
| Tiền | 1 | 2 |

# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## V.01. TIỀN VÀ CÁC KHOẢN TƯƠNG ĐƯƠNG TIỀN
# BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
### Phân tích chi tiết theo thuyết minh
| Nội dung | 2025 | 2024 |
|---|---:|---:|
| Tiền mặt | 1 | 2 |
"""
    scope = detect_notes_scope(text)
    assert scope.found
    assert scope.end_line == len(text.splitlines())

    out = parse_notes(text, source_name="x.md", sector="enterprise")
    assert out["diagnostics"]["section_count"] >= 1
    assert len(out["diagnostics"]["primary_heading_decoys_inside_notes"]) >= 1


def test_simple_breakdown_table():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## V.01. TIỀN VÀ CÁC KHOẢN TƯƠNG ĐƯƠNG TIỀN
| Nội dung | 31/12/2025 | 01/01/2025 |
|---|---:|---:|
| Tiền mặt | 80.000 | 65.000 |
| Tiền gửi | 1.450.000 | 1.250.000 |
| **Tổng cộng** | **1.530.000** | **1.315.000** |
"""
    out = parse_notes(text, source_name="x.md", sector="enterprise")
    blocks = out["sections"][0]["blocks"]
    tables = [x for x in blocks if x["form"] == "table"]
    assert tables
    assert tables[0]["semantic_shape"] == "breakdown"
    assert tables[0]["rows"][-1]["row_role"] == "total"


def test_movement_table_detected():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## V.07. TÀI SẢN CỐ ĐỊNH HỮU HÌNH
| Nội dung | Nhà cửa | Máy móc | Tổng cộng |
|---|---:|---:|---:|
| Nguyên giá đầu năm | 100 | 200 | 300 |
| Mua trong năm | 10 | 20 | 30 |
| Thanh lý, nhượng bán | (5) | (10) | (15) |
| Nguyên giá cuối năm | 105 | 210 | 315 |
"""
    out = parse_notes(text, source_name="x.md", sector="enterprise")
    table = next(x for x in out["sections"][0]["blocks"] if x["form"] == "table")
    assert table["semantic_shape"] == "movement"
    movement_row = next(x for x in table["rows"] if "Mua" in x["label_raw"])
    assert movement_row["values"][0]["movement_role"] == "addition"


def test_note_values_expose_canonical_unit_without_scaling():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## 1. TIỀN
**Đơn vị: triệu đồng**
| Nội dung | 2025 | 2024 |
|---|---:|---:|
    | Tiền mặt | 80 | 65 |
"""
    out = parse_notes(text, source_name="units.md", sector="enterprise")
    table = next(x for x in out["sections"][0]["blocks"] if x["form"] == "table")
    value = table["rows"][0]["values"][0]
    assert value["raw"] == "80"
    assert value["normalized"] == 80
    assert value["unit_canonical"] == "million_vnd"


def test_parenthesized_unit_does_not_pollute_raw_bullet_value():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## 1. TÀI SẢN
* Giá gốc: 58.066 (triệu đồng)
"""
    out = parse_notes(text, source_name="unit_suffix.md", sector="enterprise")
    block = next(block for block in out["sections"][0]["blocks"] if block["rows"])
    value = block["rows"][0]["values"][0]
    assert value["raw"] == "58.066"
    assert value["normalized"] == 58066
    assert value["unit"] == "triệu đồng"


def test_baseline_statement_rows_link_and_reconcile_without_mutating_primary():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## 1. TIỀN
| Nội dung | 2025 | 2024 |
|---|---:|---:|
| Tiền mặt | 100 | 90 |
| Tổng cộng | 100 | 90 |
"""
    primary = {
        "statements": {
            "financial_position": {
                "rows": [{
                    "row_id": "r0001",
                    "note": "1",
                    "observations": [
                        {"period_key": "current", "value": 100},
                        {"period_key": "prior", "value": 90},
                    ],
                }]
            }
        }
    }
    out = parse_notes(text, source_name="linked.md", sector="enterprise", primary=primary)
    assert any(link["relation"] == "explains" for link in out["links"])
    assert any(item["status"] == "confirmed" for item in out["reconciliation"])
    assert primary["statements"]["financial_position"]["rows"][0]["observations"][0]["value"] == 100


def test_company_label_is_not_misclassified_as_note_total():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## 20.1 THUẾ THU NHẬP DOANH NGHIỆP
* **Điều chỉnh giảm**
    * **Chuyển lỗ từ công ty con:**
        * Năm nay: (54) triệu đồng
        * Năm trước: (14) triệu đồng
* **Chi phí thuế TNDN hiện hành:**
    * Năm nay: 321.919 triệu đồng
    * Năm trước: 230.373 triệu đồng
"""
    out = parse_notes(text, source_name="tax-role.md", sector="bank")
    rows = [
        row
        for section in out["sections"]
        for block in section["blocks"]
        for row in block["rows"]
    ]
    detail = next(row for row in rows if "Chuyển lỗ từ công ty con" in row["label_raw"])
    assert detail["row_role"] == "detail"


def test_tax_note_total_can_match_signed_primary_by_magnitude():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## 20.1 THUẾ THU NHẬP DOANH NGHIỆP
* **Điều chỉnh giảm**
    * **Chuyển lỗ từ công ty con:**
        * Năm nay: (54) triệu đồng
        * Năm trước: (14) triệu đồng
* **Chi phí thuế TNDN hiện hành:**
    * Năm nay: 321.919 triệu đồng
    * Năm trước: 230.373 triệu đồng
"""
    primary = {
        "statements": {
            "income_statement": {
                "rows": [{
                    "row_id": "r0017",
                    "label": "Chi phí thuế thu nhập doanh nghiệp hiện hành",
                    "note": "20.1",
                    "observations": [
                        {"period_key": "current", "value": -321919},
                        {"period_key": "prior", "value": -230373},
                    ],
                }]
            }
        }
    }
    out = parse_notes(text, source_name="tax-sign.md", sector="bank", primary=primary)
    reconciliations = out["reconciliation"]
    assert [item["status"] for item in reconciliations] == ["confirmed", "confirmed"]
    assert all("sign_convention_difference" in item["evidence"] for item in reconciliations)
