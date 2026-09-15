# v23.0.0 — Notes Scope & Coverage Patch

## Mục tiêu
v23 sửa lớp phát hiện phạm vi Thuyết minh dựa trên corpus 57 báo cáo thực tế, không mở rộng ontology/linking.

## Thay đổi chính
1. Nhận diện tiêu đề Notes ở các dạng `# heading`, `**bold**`, `__bold__`, blockquote và plain text.
2. Loại Mục lục bằng dấu hiệu số trang/range ở cùng dòng hoặc dòng kế tiếp.
3. `statement_scanner` chỉ là evidence; Notes scanner tự xác minh và có thể từ chối start line sai từ Mục lục.
4. Sticky Notes scope giữ đến cuối tài liệu; heading B01/B02/B03 bên trong Notes là decoy.
5. Thêm `scripts/evaluate_notes_coverage.py` để chạy inventory toàn corpus.
6. Không thay đổi linker/reconciliation và không overwrite primary canonical.

## Chạy coverage 57 file
```bash
python scripts/evaluate_notes_coverage.py md_reports \
  --output output_notes_v23_eval \
  --write-per-file
```

Output:
- `inventory.csv/json`
- `coverage_summary.json`
- `scope_misses.csv`
- `suspicious_scope.csv`
- `structural_backlog.csv`
- tùy chọn `per_file/*.notes.ir.json`

## Release gates
- Notes scope current reference corpus: 57/57
- false primary capture: 0
- B01/B02/B03 regression: unchanged
- existing v22.4/v22.5 tests: PASS

## Phạm vi không làm trong v23.0
- Không thêm hard-coded note number.
- Không ép toàn bộ Notes vào canonical.
- Không scale số theo đơn vị.
- Không mở rộng linker bằng fuzzy rule.
- Không sửa movement/multi-axis parser ngoài các capability đã có ở Foundation.
