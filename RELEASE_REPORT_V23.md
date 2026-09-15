# BÁO CÁO TRIỂN KHAI v23.0.0 — NOTES SCOPE & COVERAGE PATCH

## 1. Mục tiêu

v23.0.0 đóng vai trò bản vá Scope & Coverage cho subsystem Thuyết minh BCTC. Bản này không mở rộng ontology/linking và không thay đổi canonical của B01/B02/B03.

## 2. Lỗi được xác nhận trên corpus 57 file

### 2.1. Tiêu đề Notes không phải Markdown heading
Một số báo cáo dùng bold hoặc plain text, ví dụ GVR. v22.5.0 chỉ nhận diện được tập presentation hẹp nên có thể bỏ sót toàn bộ Notes.

### 2.2. Notes giả trong Mục lục
Một số báo cáo có mục lục dạng:
- `Thuyết minh báo cáo tài chính hợp nhất` + dòng kế tiếp `12 - 86`;
- `7. Bản thuyết minh ...` + dòng kế tiếp `Trang: 15-78`;
- bảng mục lục `THUYẾT MINH ... | 10-102`.

### 2.3. Notes giả trong Báo cáo kiểm toán
Một số báo cáo liệt kê bộ BCTC được kiểm toán bằng bullet, gồm cả `Bản thuyết minh báo cáo tài chính hợp nhất`. Đây chỉ là statement reference, không phải điểm bắt đầu Notes.

## 3. Cơ chế v23

1. Normalize presentation trước title detection: heading, bold, italic, blockquote, bullet, plain text.
2. Reject TOC theo local page-number/page-range signatures.
3. Reject statement-list reference trong audit/front matter.
4. Validate output của `statement_scanner`; scanner không còn là authority tuyệt đối cho Notes start.
5. Sticky Notes scope giữ nguyên tới cuối document.
6. Primary-looking headings sau Notes start chỉ được ghi diagnostic `note_internal_decoy`.
7. `PRIMARY > NOTES`; reconciliation vẫn non-destructive.

## 4. Kết quả kiểm thử

### Unit tests
- `tests/test_notes_foundation.py`
- `tests/test_notes_scope_v23.py`
- Tổng: 11/11 PASS.

### Corpus 57 file
- File: 57
- Notes detected: 57/57
- Detection rate: 100%
- Scope confidence < 0.90: 0
- Rejected false title candidates: 57
- Primary-like headings bên trong sticky Notes scope: 101 (được giữ là decoy, không đóng scope)

### Extraction inventory sau scope patch
- Sections: 949
- Markdown tables: 149
- Rows: 1,588
- Breakdown: 102
- Movement: 16
- Matrix: 30
- Aging: 1
- Reconciliation shape: 0
- Narrative blocks: 1,090

Các con số table/row không được coi là coverage hoàn chỉnh. Narrative còn rất lớn, xác nhận backlog tiếp theo là Generic Structural Block Extraction cho bullet/plain-text/OCR tables.

## 5. Zero-regression boundary

v23 không sửa mapper/canonical logic B01/B02/B03, linker hay reconciliation. Thay đổi production tập trung ở `src/notes/scanner.py` và evaluator mới. Do đó đường primary không bị thay đổi bởi patch này.

Ground Truth 406/406 không được chạy lại trong artifact build này vì bộ Ground Truth không nằm trong gói 57 input được cung cấp cho lần triển khai v23. Gate đó cần được chạy trong repository của dự án trước khi merge/release, cùng với 3 core test suites hiện hữu.

## 6. File mới/chỉnh sửa

- `src/notes/scanner.py` — thay thế
- `scripts/evaluate_notes_coverage.py` — mới
- `tests/test_notes_scope_v23.py` — mới
- `README_V23.md` — mới
- `RELEASE_REPORT_V23.md` — mới
- `VERSION.txt` — cập nhật v23.0.0

Các module Notes Foundation còn lại giữ nguyên từ v22.5.0.

## 7. Bước tiếp theo

v23.1 / v23.2 nên tập trung vào Structural Block Extraction thay vì ontology:
- bullet tables;
- plain-text row/column layouts;
- OCR fragmented tables;
- column-major/period-major note structures;
- movement schedules đa trục.

Release gate tiếp theo vẫn giữ `false_primary_capture_rate = 0` và primary regression = 100%.
