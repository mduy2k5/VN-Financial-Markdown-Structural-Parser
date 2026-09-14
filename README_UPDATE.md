# README_UPDATE — v15

## Mục tiêu

V15 là bản debug tiếp theo của pipeline 3 statements. Không có quality gate và không chặn output theo accuracy.

Bản này sửa regression chính của v14: reconciliation đã làm sạch source observations nhưng xóa một số occurrence, khiến Financial Position matched rows giảm từ 88.17% xuống 86.23%.

## Thay đổi chính

### 1. Non-destructive source reconciliation

`source_reconciliation.py` không còn xóa duplicate source observations.

Mỗi nhóm source row cùng normalized label được gắn:

- `duplicate_group_id`
- `duplicate_group_size`
- `preferred_observation`
- `reconciliation_rank`

Toàn bộ occurrence gốc vẫn nằm trong `nodes` để evaluator/downstream không mất source evidence.

### 2. Reconciled source view

Canonical bổ sung top-level:

```json
"reconciled_source_view": []
```

Mỗi group chứa:

- preferred node;
- toàn bộ member node IDs;
- current/previous đã reconcile;
- vote table;
- trạng thái `unanimous`, `majority`, `conflict`, `missing`.

### 3. Conservative value reconciliation

Period value chỉ được chọn khi:

- toàn bộ evidence đồng nhất; hoặc
- có strict majority.

Nếu tie/conflict, v15 giữ nguyên tất cả evidence và không ép chọn một giá trị mới.

Preferred source observation có thể được fill period còn thiếu từ reconciled view, nhưng các alternatives không bị xóa.

### 4. Semantic hydration

Semantic node chỉ được fill khi:

- exact normalized label match;
- Cash Flow section tương thích;
- chỉ có đúng một semantic candidate;
- period hiện tại đang null.

Không overwrite giá trị semantic đã có.

### 5. Income

Không thay broad extractor/mapper. V15 chỉ thay source reconciliation policy để tránh regression recall.

## Diagnostics

`diagnostics.source_observation_reconciliation` gồm:

- `input_source_nodes`
- `output_source_nodes`
- `duplicate_groups`
- `removed_duplicate_nodes` (v15 luôn bằng 0)
- `conflicting_groups`
- `preferred_completed_nodes`
- `semantic_nodes_filled`
- `preserves_all_source_observations`

## Chạy

```powershell
python .\run_income_comparison.py .\output\md_reports `
  --financial-position-dir .\<folder_financial_position_canonical> `
  --comparison-dir .\comparison_v14 `
  --output .\comparison_v15 `
  --current-year 2025 `
  --previous-year 2024
```

## Kỳ vọng debug

- Financial Position: lấy lại recall của v13 nhưng giữ phần cải thiện period accuracy của v14.
- Income: không regress mức matched rows v14.
- Cash Flow: giữ toàn bộ evidence v13/v14 để tiếp tục debug 112 ground-truth rows còn thiếu.

Các KPI >90% / >95% chỉ dùng để theo dõi, không dùng để chặn output.
