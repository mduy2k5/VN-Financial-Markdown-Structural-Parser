from src.notes.scanner import detect_notes_scope, explain_notes_scope_candidates


def test_bold_notes_title_is_detected():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ
| Chỉ tiêu | 2025 | 2024 |
|---|---:|---:|
| Tiền | 1 | 2 |

**THUYẾT MINH BÁO CÁO TÀI CHÍNH HỢP NHẤT**

## 1. Đặc điểm hoạt động
Nội dung.
""".strip()
    scope = detect_notes_scope(text)
    assert scope.found
    assert scope.start_line == 6


def test_plain_notes_title_is_detected():
    text = """
BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
Dòng dữ liệu
THUYẾT MINH BÁO CÁO TÀI CHÍNH HỢP NHẤT
1. Đặc điểm hoạt động
""".strip()
    scope = detect_notes_scope(text)
    assert scope.found
    assert scope.start_line == 3


def test_toc_title_followed_by_page_range_is_rejected():
    text = """
# MỤC LỤC
Báo cáo tình hình tài chính hợp nhất
6 - 8
Thuyết minh báo cáo tài chính hợp nhất
12 - 86

# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
Dòng dữ liệu

**THUYẾT MINH BÁO CÁO TÀI CHÍNH HỢP NHẤT**
## 1. Đặc điểm hoạt động
""".strip()
    scope = detect_notes_scope(text)
    assert scope.found
    assert scope.start_line == 10
    candidates = explain_notes_scope_candidates(text)
    assert any(x["line_no"] == 4 and x["rejected"] for x in candidates)


def test_bad_scanner_toc_start_is_not_authoritative():
    text = """
# MỤC LỤC
Thuyết minh báo cáo tài chính hợp nhất
12 - 86

# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
Dòng dữ liệu

# THUYẾT MINH BÁO CÁO TÀI CHÍNH HỢP NHẤT
## V.1. Tiền và các khoản tương đương tiền
""".strip()
    fake_scanner = {
        "ranges": [{"statement_type": "NOTES", "start_line": 2, "end_line": 99, "confidence": 0.99}]
    }
    scope = detect_notes_scope(text, scanner_result=fake_scanner)
    assert scope.found
    assert scope.start_line == 8
    assert any("rejected_toc_start" in x for x in scope.evidence)


def test_sticky_scope_remains_to_document_end():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## V.1. Tiền
# BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Phân tích chi tiết theo thuyết minh.
""".strip()
    scope = detect_notes_scope(text)
    assert scope.end_line == len(text.splitlines())


def test_audit_statement_list_reference_is_rejected():
    text = """
# BÁO CÁO KIỂM TOÁN ĐỘC LẬP
* Bảng cân đối kế toán hợp nhất
* Báo cáo kết quả hoạt động kinh doanh hợp nhất
* Báo cáo lưu chuyển tiền tệ hợp nhất
* Bản thuyết minh báo cáo tài chính hợp nhất

Trách nhiệm của Ban Tổng Giám đốc

THUYẾT MINH BÁO CÁO TÀI CHÍNH HỢP NHẤT
1. Thông tin chung
""".strip()
    scope = detect_notes_scope(text)
    assert scope.found
    assert scope.start_line == 9
    candidates = explain_notes_scope_candidates(text)
    assert any(x["line_no"] == 5 and x["reject_reason"] == "statement_list_reference" for x in candidates)


def test_numbered_toc_with_trang_child_is_rejected():
    text = """
1. Báo cáo kiểm toán độc lập
   - Trang: 3-4
7. Bản thuyết minh báo cáo tài chính hợp nhất cho năm tài chính kết thúc ngày 31 tháng 12 năm 2025
   - Trang: 15-78

BẢN THUYẾT MINH BÁO CÁO TÀI CHÍNH HỢP NHẤT
I. ĐẶC ĐIỂM HOẠT ĐỘNG
""".strip()
    scope = detect_notes_scope(text)
    assert scope.found
    assert scope.start_line == 6
    candidates = explain_notes_scope_candidates(text)
    assert any(x["line_no"] == 3 and x["reject_reason"] == "numbered_toc_reference" for x in candidates)
