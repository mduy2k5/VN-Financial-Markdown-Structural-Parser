# Demo scan 57 báo cáo

## Chạy

Từ thư mục gốc dự án:

```powershell
python .\scripts\run_demo.py
```

Demo mặc định chạy ở chế độ `source-only`: chỉ đọc `md_reports/`, parse mới cả ba bảng chính và Notes, rồi lưu artifact cho 57 báo cáo. Không chạy benchmark, audit hay so sánh reconciliation.

## Output

```text
output/demo/scan_57/
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
  --output .\output\demo\scan_57

# Chỉ dùng khi cần demo tương thích với B01 đã xác thực provenance
python .\scripts\run_demo.py `
  --mode seeded-demo `
  --financial-position-dir .\path\to\validated_b01_artifacts
```

Pipeline không tự quét project root, `output/` hoặc các comparison cũ. Ground truth và artifact của lần chạy trước chỉ được dùng bởi các script audit/compare sau khi scan hoàn tất.
