# README_UPDATE — Integrated 3-Statement Flow / package v11

`README.md` của dự án không bị thay thế.

## Mục tiêu chất lượng

Ground-truth evaluator của dự án là nguồn đánh giá cuối cùng:

- ngưỡng tối thiểu chấp nhận: **>= 90% matched rows**;
- mục tiêu: **>= 95% matched rows**;
- không chấp nhận cải thiện một statement bằng cách gây regression statement khác.

v11 tích hợp đầy đủ flow 3 statements nhưng **không tự tuyên bố đạt quality gate** nếu chưa chạy evaluator 57-file của dự án.

## Flow v11

```text
Markdown
  ├─ Financial Position: reuse canonical hoàn chỉnh từ pipeline B02/Bảng tình hình tài chính đã có
  ├─ Income Statement: Income v8
  └─ Cash Flow: Cash Flow collector v2
        ↓
unified comparison + 3 canonical artifacts
```

Output chuẩn cho mỗi file:

```text
<base>.financial_position.canonical.json
<base>.income.canonical.json
<base>.cashflow.canonical.json
<base>.comparison.json
```

Comparison gồm:

```json
{
  "financial_position": {},
  "income_statement": {},
  "cash_flow_statement": {}
}
```

## Financial Position integration

Financial Position đã được hoàn thiện ở pipeline trước nên v11 **không viết lại mapper B02 từ đầu**. Runner ưu tiên tái sử dụng canonical:

```text
<base>.canonical.json
schema_id = UNIVERSAL_FINANCIAL_POSITION_V1
statement_type = FINANCIAL_POSITION
```

Sau đó copy vào output thành:

```text
<base>.financial_position.canonical.json
```

Điều này giữ baseline đã hoàn thiện và tránh regression do re-implementation.

Có thể chỉ rõ thư mục canonical cũ bằng:

```powershell
--financial-position-dir .\canonical_v3_9
```

Nếu không truyền, runner tự tìm trong các vùng workspace gần input/comparison/output. Nếu không tìm thấy source FP, summary ghi:

```text
financial_position_source_missing
```

thay vì giả vờ pipeline 3 statements đã đầy đủ.

## Cash Flow

Giữ các sửa của v10:

- `CF_PIPE_TABLE`
- `CF_INLINE_PERIODS`
- `CF_PERIOD_CHILDREN`
- `CF_YEAR_SECTIONS`
- `CF_PLAIN_TEXT_CODE`
- `CF_HEADING_VALUE`
- enterprise direct/indirect
- bank direct/indirect
- securities indirect
- code/note optional
- source-coverage gate

## Chạy khuyến nghị

```powershell
Set-Location 'F:\Indexium\Flatten'

python .\run_income_comparison.py .\output\md_reports `
  --financial-position-dir .\<THU_MUC_CANONICAL_B02_CU> `
  --comparison-dir .\comparison_v10 `
  --output .\comparison_v11 `
  --current-year 2025 `
  --previous-year 2024
```

Nếu canonical Financial Position cũ nằm trong workspace gần input/comparison thì có thể bỏ `--financial-position-dir`, nhưng chỉ rõ folder vẫn an toàn và nhanh hơn.

Log đầu batch có:

```text
[FINANCIAL_POSITION] canonical_sources=... scanned=...
```

Mỗi file có dạng:

```text
[OK] ACB...: fp=ok nodes=55 | income=ok 22/22 | cashflow=ok 36/36 ...
```

## Summary fields mới

```text
financial_position_status
financial_position_value_nodes
financial_position_current_nodes
financial_position_previous_nodes
financial_position_canonical_file
financial_position_preserved
```

## Regression kiểm tra cục bộ

ACB:

```text
Financial Position: 55 value nodes
Income:             22/22
Cash Flow:           36/36
```

ANV:

```text
Financial Position: 67 value nodes
Income:             22/22 mapped
Cash Flow:           37/37
```

Đây là integration regression, **không thay thế ground-truth evaluation 57 file**.

## Acceptance

Sau khi chạy v11, phải chạy lại evaluator 57-file. Chỉ promote bản tiếp theo khi:

```text
Financial Position matched rows >= 90%, target >= 95%
Income matched rows             >= 90%, target >= 95%
Cash Flow matched rows          >= 90%, target >= 95%
```

Nếu Cash Flow vẫn dưới 90%, tập trung sửa missing previous-period hydration, securities layout và bank layouts thay vì nới fuzzy mapping không kiểm soát.
