# Income Mapping v1.1 — Common Row Adapter

Bộ này chỉ xử lý **mapping**. Không parse Markdown.

## Điểm sửa chính

`v1.0` chỉ đọc JSON nếu root có trực tiếp `rows/observations/items/data`. Điều đó làm nhiều output của converter chung bị `rows_total=0` dù observation nằm sâu hơn trong JSON.

`v1.1` thêm `discover_rows()`:

- quét recursive các container JSON;
- nhận `label/source_label/canonical_name/...`;
- nhận `current/previous` trực tiếp;
- hydrate từ `value.current/value.previous`;
- hydrate từ `period_values`;
- hydrate từ `periods + values`;
- hydrate từ `values=[{period,value}, ...]`;
- đọc lại `extraction_meta.occurrences` khi input là canonical/debug node;
- không ép map nếu source thực sự không có income observation.

## Chạy

```powershell
python .\run_income_map.py .\rows `
  --sector auto `
  --current-year 2025 `
  --previous-year 2024 `
  --output .\output_income
```

Ngân hàng:

```powershell
python .\run_income_map.py .\rows `
  --sector bank `
  --current-year 2025 `
  --previous-year 2024 `
  --output .\output_income
```

Doanh nghiệp:

```powershell
python .\run_income_map.py .\rows `
  --sector enterprise `
  --current-year 2025 `
  --previous-year 2024 `
  --output .\output_income
```

## Output

Mỗi input:

- `*.income.canonical.json`
- `*.income.mapping.csv`

Toàn batch:

- `income_mapping_report.csv`
- `income_mapping_report.json`

## Status

- `ok`: mapping có dữ liệu hai kỳ hoặc không phát hiện lỗi rõ ràng.
- `source_rows_missing`: adapter không tìm thấy observation income trong JSON nguồn. Đây là lỗi upstream của converter/extractor, không phải alias.
- `period_hydration_incomplete`: có current nhưng toàn bộ previous vẫn mất.
- `mapping_failed`: có rows nhưng không map được.
