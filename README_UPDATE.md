# Integrated Financial Statement Mapper v9

Bản v9 lấy trực tiếp v8 làm nền và tích hợp **Cash Flow v1** vào cùng runner hiện tại.

## Luồng chạy

```text
Markdown
  ├─ Income v8
  └─ Cash Flow v1
       ├─ scope detection
       ├─ sector detection
       ├─ direct / indirect detection
       ├─ section-aware extraction
       ├─ UNIVERSAL_CASH_FLOW_V1 mapping
       └─ formula validation
             ↓
merge comparison JSON hiện có
```

Output comparison giữ nguyên các key đang có và bổ sung:

```json
{
  "financial_position": {},
  "income_statement": {},
  "cash_flow_statement": {
    "v01": {},
    "canonical_file": "...cashflow.canonical.json"
  }
}
```

## Nguyên tắc Cash Flow v1

`Mã số` và `Thuyết minh` **không bắt buộc**.

Identity chính:

```text
method + section + normalized label
```

`code` chỉ là supporting evidence. Đặc biệt với bank, cùng code `01`, `02`, ... được tái sử dụng ở operating / investing / financing nên không map bằng code đơn độc.

Profiles v1:

- `enterprise_direct`
- `enterprise_indirect`
- `bank_direct`
- `bank_indirect`

Securities / insurance cash flow được nhận diện và giữ diagnostic, chưa ép vào enterprise/bank profile nếu form đặc thù.

## Chạy

Giữ nguyên workflow hiện tại:

```powershell
Set-Location 'F:\Indexium\Flatten'

python .\run_income_comparison.py .\output\md_reports `
  --comparison-dir .\comparison_v8 `
  --output .\comparison_v9 `
  --current-year 2025 `
  --previous-year 2024
```

Nếu Markdown ở `md_reports` trực tiếp:

```powershell
python .\run_income_comparison.py .\md_reports `
  --comparison-dir .\comparison_v8 `
  --output .\comparison_v9
```

## File sinh ra

Cho mỗi source:

```text
*.comparison.json
*.income.canonical.json
*.cashflow.canonical.json   # khi Cash Flow đủ profile để map
```

Batch:

```text
comparison_summary.json
comparison_summary.csv
```

Summary giữ các cột income cũ và bổ sung:

```text
cashflow_sector
cashflow_method
cashflow_status
cashflow_scope_start
cashflow_scope_end
cashflow_input_rows
cashflow_mapped_rows
cashflow_mapping_rate
cashflow_value_nodes
cashflow_current_nodes
cashflow_previous_nodes
cashflow_formula_pass_rate
cashflow_canonical_file
```

## Regression đại diện đã chạy

```text
ACB: cashflow bank/direct       36/36 mapped
ABB: cashflow bank/direct       26/26 mapped
ANV: cashflow enterprise/indirect 37/37 mapped
BSR: cashflow enterprise/indirect 31/31 mapped
HPG: cashflow enterprise/indirect 31/31 mapped
```

Các layout hiện hỗ trợ:

- label + child `Mã số / Thuyết minh / Năm nay / Năm trước`
- inline `value (Năm 2025) | value (Năm 2024)`
- inline `value (Năm nay), value (Năm trước)`
- Markdown pipe table
- thiếu code / thiếu note
- repeated heading trên trang `tiếp theo`

## Resources

```text
resources/
  income_statement_schema.json
  income_statement_aliases.json
  cash_flow_schema.json
  cash_flow_aliases.json
```

Cash Flow schema id:

```text
UNIVERSAL_CASH_FLOW_V1
schema_version = 1.0.0
```
