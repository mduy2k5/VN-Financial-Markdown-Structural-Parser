# v23.1.0 Structural Notes Extraction

## Mục tiêu
Mở rộng Notes Foundation từ pipe-table-only sang structural extraction cho dữ liệu Markdown/OCR thực tế.

## Thay đổi chính
- Plain/bold/Markdown numbered note headings trong sectionizer.
- Note ID dạng `2b`, `6a`, `21b` được giữ nguyên semantic ID.
- Multi-row Markdown table header: header tầng 2 và dòng đơn vị không còn bị xuất thành data row.
- Bullet period containers:
  - `Số cuối năm -> label:value`
  - `Số đầu năm -> label:value`
  - `Năm nay / Năm trước`
  được pivot thành một row có current/previous.
- Semantic parent với child current/previous được đọc thành row.
- Single-value key:value fallback chỉ nhận khi có financial unit rõ ràng để giảm nhiễu STT/phone/id.
- Không scale số liệu.
- Row exporter giữ `values`, `headers`, `dimensions`, provenance.

## Output
`python run_notes.py md_reports --output output_notes`

```text
output_notes/
├── notes_rows/
│   ├── <report>.notes_rows.csv
│   ├── <report>.notes_rows.json
│   ├── all_notes_rows.csv
│   └── all_notes_rows.json
├── ir/
│   └── <report>.notes.ir.json
└── notes_summary.json
```

## Verification
- Notes tests: 15/15 PASS.
- Corpus 57: Notes detected 57/57.
- Exported structural rows: 27,542.
- Target cases:
  - ABB: 567 rows
  - ACB: 307 rows
  - ANV: 419 rows
