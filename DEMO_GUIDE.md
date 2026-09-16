# Demo scan 57 báo cáo

## Chạy

Từ thư mục gốc dự án:

```powershell
python .\scripts\run_demo.py
```

Demo chỉ quét `md_reports/` và lưu artifact parser cho 57 báo cáo. Không chạy benchmark, audit hay so sánh reconciliation.

## Output

```text
demo_output/scan_57/
├── scan.log
├── scan_summary.md
├── scan_manifest.json
└── results/
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
  --output .\demo_output\scan_57
```

Canonical Bảng cân đối được nạp từ folder `output/comparisons/comparison_v22_4_unit`, sau đó pipeline quét lại nguồn để tích hợp KQKD, LCTT và Notes.
