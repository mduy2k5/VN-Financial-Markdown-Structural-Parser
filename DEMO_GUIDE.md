# Demo scan theo thư mục input

## Chạy

Từ thư mục gốc dự án:

```powershell
python .\scripts\run_demo.py
```

Demo chỉ đọc `md_reports/`, parse mới cả ba bảng chính và Notes, rồi lưu artifact cho toàn bộ báo cáo tìm thấy. Output cũ, ground truth và comparison không được dùng làm input parser. Demo không chạy benchmark, audit hay so sánh reconciliation.

## Output

```text
output/demo/latest/
├── scan.log
├── scan_summary.md
├── scan_manifest.json
└── results/
    ├── run_metadata.json
    ├── comparison_summary.json
    ├── comparison_summary.csv
    ├── <report>.comparison.json
    ├── <report>.financial_position.canonical.json
    ├── <report>.income.canonical.json
    ├── <report>.cashflow.canonical.json
    ├── <report>.notes.ir.json
    └── notes_rows/
```

`scan_manifest.json` là chỉ mục theo từng báo cáo, gồm trạng thái và đường dẫn tới artifact đã tạo.

## Tùy chọn

```powershell
# Không quét Notes
python .\scripts\run_demo.py --no-notes

# Chỉ định input/output khác
python .\scripts\run_demo.py `
  --input .\md_reports `
  --output .\output\demo\latest

```

Pipeline không tự quét project root, `output/` hoặc các comparison cũ. Các script audit/compare là công cụ đánh giá riêng và chỉ đọc artifact sau khi scan hoàn tất.
