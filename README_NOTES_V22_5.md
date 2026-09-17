# v22.5.0 Notes Foundation

## Mục tiêu
Thêm subsystem Thuyết minh BCTC độc lập, không phá B01/B02/B03 hiện có.

## Policy bắt buộc
- PRIMARY > NOTES.
- Notes không overwrite canonical primary.
- Sticky Notes scope.
- Không scale số theo đơn vị.
- Generic Note IR trước, sector profile sau.
- Không hard-code note number.
- Raw + normalized note ID cùng tồn tại.
- Link bằng explicit note reference là evidence mạnh nhất.
- Recovery từ Notes không tự mutate canonical trong v22.5.0.

## Cài đặt
Copy `src/notes/` vào project.
Có thể chạy độc lập:
`python run_notes.py tests/md_test/FPT_BCTC_2025_extreme_stress_test.md --output output/notes/raw`

Nếu dùng flat_parser integrated flow, thay file:
`flat_parser/integrated_pipeline.py`

## Output
`*.notes.ir.json` có:
- scope
- sections
- blocks
- rows / values
- dimensions
- links
- reconciliation
- diagnostics

## Test
`pytest -q tests/test_notes_foundation.py`

## Versioning
Baseline: v22.4.2
Target: v22.5.0-notes-foundation
