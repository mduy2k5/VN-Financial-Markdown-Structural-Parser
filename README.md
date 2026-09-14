# Income Comparison Full v7

## Mục tiêu

v7 sửa regression của v6 và bổ sung profile bảo hiểm vào cùng universal income pipeline.

### Thay đổi chính

1. **Scope ranking chống chọn nhầm Notes**
   - phát hiện mốc bắt đầu `THUYẾT MINH BÁO CÁO TÀI CHÍNH` / `B09-DN/HN`;
   - candidate income nằm sau mốc notes bị penalty mạnh;
   - block quá dài (>320 dòng) bị giảm điểm;
   - tăng trọng số cho tập anchor của báo cáo chính thay vì số lượng numeric rows thuần túy.

   Mục tiêu: giữ ACB/NAB quý đã hồi phục ở v6 nhưng không để BSR/VIC nhảy sang notes.

2. **Insurance profile**
   - `sector=insurance` không còn hard-stop `schema_sector_gap`;
   - thêm `INCOME.INSURANCE.*` vào `UNIVERSAL_INCOME_STATEMENT_V1`;
   - hỗ trợ các mã 31, 32, 33, 41, 42, 43, 43.1, 43.2, 44, 44.1, 44.2,
     45, 46, 47, 48, 48.1, 48.2, 50, 51, 52, 60, 61, 62, 70;
   - thêm formula validation cho insurance.

3. Giữ nguyên các collector v6 đã ổn cho bank / enterprise / securities.

## Chạy batch

```powershell
Set-Location 'F:\Indexium\Flatten'

python .\run_income_comparison.py .\output\md_reports `
  --comparison-dir .\output\comparisons\comparison_legacy `
  --output .\output\comparisons\comparison_v7 `
  --current-year 2025 `
  --previous-year 2024
```

Nếu không cần merge comparison B02 cũ:

```powershell
python .\run_income_comparison.py .\output\md_reports --output .\output\comparisons\comparison_v7
```

## Kiểm tra regression

Ưu tiên kiểm tra:

- ACB: không được tụt khỏi 22/22.
- NAB quý: không được quay về 0 rows.
- BSR: scope phải quay về báo cáo chính, không chọn vùng thuyết minh doanh thu/giá vốn.
- VIC: sector phải quay về enterprise và có canonical.
- BVH: sector insurance phải tạo canonical thay vì `schema_sector_gap:insurance`.
- BSI/CTS: securities không được regress.

Trong summary, `collector_policy` phải là `income_multi_layout_v7`.

## v8 - batch discovery safety

v8 keeps the v7 scope/insurance changes and fixes the silent-empty-batch failure mode.

Input discovery now:

1. validates that the input path exists;
2. accepts a single `.md` file;
3. scans `*.md` in the requested directory;
4. falls back to recursive `**/*.md` discovery if the top level has none;
5. prints `[DISCOVERY] ... md_found=N selected=M` before processing;
6. exits non-zero instead of writing a misleading empty summary when no Markdown input is found.

Recommended command from `F:\Indexium\Flatten`:

```powershell
python .\run_income_comparison.py .\output\md_reports `
  --comparison-dir .\output\comparisons\comparison_v6 `
  --output .\output\comparisons\comparison_v8
```

If your Markdown is actually in `F:\Indexium\Flatten\md_reports`, using `.\md_reports` also works. v8 prints the resolved input path so this is immediately visible.
