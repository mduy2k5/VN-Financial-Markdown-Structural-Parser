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
