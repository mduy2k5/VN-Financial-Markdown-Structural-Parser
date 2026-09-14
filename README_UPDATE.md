# README_UPDATE — v13

## Mục tiêu

v13 là bản debug tiếp theo từ v12. Không có quality gate và không chặn output theo accuracy.
Mục tiêu là tăng dữ liệu đúng có thể quan sát/đối chiếu với ground truth, ưu tiên:

1. Financial Position: phục hồi trực tiếp các dòng nguồn trong vùng bảng thay vì chỉ dựa vào canonical cũ.
2. Cash Flow: phục hồi kỳ Previous ở các layout ngân hàng direct còn yếu.
3. Income: chỉ bổ sung source rows trong đúng income scope; semantic mapper hiện tại không bị thay đổi rộng.

## Thay đổi chính

### 1. Source statement recovery mới

Thêm `source_statement_recovery.py`.

Module này đọc trực tiếp Markdown trong scope của statement và thu structural rows từ:

- pipe table;
- `Số cuối năm` / `Số đầu năm`;
- `Tại ngày 31.12.YYYY`;
- `Năm YYYY`;
- inline value + year/date marker;
- parent/child value blocks.

Các row phục hồi được dùng theo chính sách:

- chỉ fill kỳ còn thiếu khi identity label/code là không mơ hồ;
- không overwrite giá trị semantic đã có;
- nếu có xung đột, ghi diagnostic thay vì ép kết quả;
- row chưa có semantic node được thêm dưới `kind = source_observation`.

### 2. Financial Position

`financial_position_bridge.py` vẫn reuse `UNIVERSAL_FINANCIAL_POSITION_V1`, sau đó chạy source recovery từ Markdown.

Scope hỗ trợ:

- `BẢNG CÂN ĐỐI KẾ TOÁN`;
- `BÁO CÁO TÌNH HÌNH TÀI CHÍNH`;
- continuation pages;
- stop trước Income / Cash Flow / Notes.

Điều này đặc biệt bổ sung các dòng chi tiết mà canonical lịch sử không materialize đầy đủ.

### 3. Cash Flow previous-period recovery

`_extract_inline_periods()` được mở rộng cho các dạng:

```text
Label: CURRENT triệu đồng (Năm 2024: PREVIOUS triệu đồng)
```

```text
Label: CURRENT (Năm 2025) | PREVIOUS (Năm 2024)
```

```text
Label: CURRENT (31.12.2025); PREVIOUS (31.12.2024)
```

Ngoài semantic collector, v13 chạy thêm raw source recovery trong cash-flow scope để giữ các row còn sót.

### 4. Debug metrics mới

`comparison_summary.json/csv` có thêm:

- `financial_position_recovered_rows`
- `income_source_recovered_rows`
- `cashflow_source_recovered_rows`
- `cashflow_source_recovery_filled_nodes`

Canonical diagnostics có `source_statement_recovery` và `source_recovery_conflicts` nếu có.

## Regression cục bộ

Regression 8 case đại diện trong runtime cho thấy previous hydration được phục hồi mạnh ở nhóm bank direct:

- TCB: previous nodes `0 -> 44`
- VPB: `0 -> 33`
- CTG: `1 -> 15`
- MSB: `20 -> 86`
- SSB: `19 -> 51`

Financial Position source recovery cũng tăng đáng kể số source-valued nodes ở các case có canonical nguồn.

Đây chỉ là regression kỹ thuật cục bộ. Kết luận accuracy phải dựa trên evaluator 57-file ground truth của workspace.

## Cách chạy

```powershell
python .\run_income_comparison.py .\output\md_reports `
  --financial-position-dir .\<folder_financial_position_canonical> `
  --comparison-dir .\comparison_v12 `
  --output .\comparison_v13 `
  --current-year 2025 `
  --previous-year 2024
```

Pipeline luôn sinh output debug tối đa có thể; accuracy thấp không làm chương trình fail.
