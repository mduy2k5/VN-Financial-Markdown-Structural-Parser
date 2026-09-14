# README_UPDATE — Integrated Cash Flow v2 / package v10

Bản cập nhật này tích hợp Cash Flow vào runner hiện tại. `README.md` của dự án không bị thay thế.

## Thay đổi chính so với v9

- Cash Flow collector policy: `cashflow_multi_layout_v2`.
- Bổ sung các layout không yêu cầu `Mã số` hoặc `Thuyết minh`:
  - `CF_PERIOD_CHILDREN` với `Năm 2025/Năm 2024`;
  - `CF_YEAR_SECTIONS` cho layout period-major;
  - `CF_PLAIN_TEXT_CODE`;
  - `CF_HEADING_VALUE`;
  - giữ `CF_PIPE_TABLE`, `CF_INLINE_PERIODS`.
- `code` và `note` vẫn là optional; identity chính là method + section + label.
- Bổ sung `securities_indirect` vào `UNIVERSAL_CASH_FLOW_V1`.
- BSI/CTS không còn hard-stop `schema_sector_gap:securities`.
- Bổ sung source-coverage gate: một file chỉ có 1–vài dòng không còn được báo `ok` giả.
- Method có fallback từ các row đã extract nếu heading/OCR không đủ rõ.
- Lọc metadata/page noise khỏi Cash Flow observations.
- Runner tiếp tục merge `cash_flow_statement` vào comparison hiện có, không chủ động xóa `financial_position`/`income_statement`.

## Regression trên nhóm v9 no_structural_rows

17 file v9 `no_structural_rows` được test lại trên source Markdown hiện có:

- phục hồi structural rows: 14/17;
- còn `no_structural_rows`: 3;
- BAB: 12/14 mapped;
- BMP: 34/40 mapped;
- BVB: 26/28 mapped;
- CTG: 21/21 mapped, được quality gate thành `partial_source_coverage` do thiếu core anchors;
- MSB: 29/45 mapped sau fallback method;
- NVB: 21/21 mapped;
- TCB: 24/30 mapped;
- VIB: 23/32 mapped;
- VPB: 26/32 mapped.

Securities regression:

- BSI: 42/72 mapped, 40 value nodes;
- CTS: 33/67 mapped, 33 value nodes.

## Chạy

```powershell
Set-Location 'F:\Indexium\Flatten'
python .\run_income_comparison.py .\output\md_reports `
  --comparison-dir .\comparison_v9 `
  --output .\comparison_v10 `
  --current-year 2025 `
  --previous-year 2024
```

Có thể dùng `comparison_v8` làm base nếu đó là comparison đầy đủ nhất đang có.

## Lưu ý merge financial_position

Runner chỉ có thể preserve `financial_position` nếu comparison base truyền qua `--comparison-dir` thực sự có key này. Nếu comparison base đã mất B02 từ phiên bản trước thì v10 không tự tái tạo B02 từ Markdown; cần trỏ `--comparison-dir` tới folder comparison đầy đủ hơn.
