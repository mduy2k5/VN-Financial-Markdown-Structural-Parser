# README_UPDATE — v12

## Mục tiêu

v12 tiếp tục flow 3 statements của v11 nhưng thay đổi trọng tâm sang **ground-truth coverage**.
Đây là bản DEBUG. Không có quality gate. Mục tiêu là quan sát đúng lỗi, giữ đầy đủ diagnostic và cải thiện dần coverage/giá trị dựa trên ground truth.

## Thay đổi chính

### 1. Source-observation layer

Canonical vẫn giữ semantic nodes chuẩn. v12 bổ sung các node `kind = source_observation` để bảo toàn structural rows/nhãn thực tế mà schema universal chưa biểu diễn hết.

- Financial Position: materialize các `source_label` đã có trong `extraction_meta.occurrences`.
- Income: giữ source rows khác wording canonical.
- Cash Flow: giữ cả mapped/unmapped structural rows có giá trị.

Đây là lớp additive; không overwrite semantic node và không thay đổi node_id chuẩn cũ.

### 2. Cash Flow previous-period recovery

Bổ sung các layout/recovery:

- `CF_POSITIONAL_VALUE_CHILDREN`: label + hai numeric child => current/previous.
- `CF_YEAR_VALUE_CHILDREN`: heading + `Năm 2025: value` / `Năm 2024: value`.
- `CF_REPEATED_PERIOD_BLOCK`: hai block cùng label bị LLM làm mất/mislabel period header; occurrence thứ hai ở vị trí đủ xa được dùng làm previous.
- `Năm nay (Triệu đồng): ...` / `Năm trước (Triệu đồng): ...` được nhận trực tiếp.
- section detector chấp nhận cả `Lưu chuyển tiền tệ từ hoạt động ...`.

Các sửa này đặc biệt nhắm vào bank-direct nơi v11 có nhiều file `previous_nodes = 0`.

## Chạy pipeline

```powershell
Set-Location 'F:\Indexium\Flatten'

python .\run_income_comparison.py .\output\md_reports `
  --financial-position-dir .\<folder_chua_financial_position_canonical_cu> `
  --comparison-dir .\comparison_v11 `
  --output .\comparison_v12 `
  --current-year 2025 `
  --previous-year 2024
```

## Regression cục bộ đã kiểm tra

MBB bank-direct trước đây v11 chỉ giữ current cho nhiều dòng. Với collector v12, các dòng kiểu:

```text
Thu nhập lãi ...:
  85.076.748
  68.529.262
```

được hydrate thành cả current và previous. Investing/financing dạng year-major và reconciliation dạng `Năm 2025:` / `Năm 2024:` cũng được ghép lại.

Một số source hiện có trong workspace sau patch cho thấy previous hydration tăng mạnh ở BVB, MBB, HDB, SHB, VIB, STB, NVB. Kết quả cuối cùng vẫn phải được xác nhận bằng bộ 57-file ground-truth của dự án; không dùng internal mapping_rate thay cho evaluator.

## Nguyên tắc release


## Debug policy

- Luôn sinh output/canonical/comparison dù coverage thấp, trừ lỗi runtime hoặc input không tồn tại.
- Không fail build chỉ vì accuracy/matched rows dưới một ngưỡng.
- Ground truth evaluator dùng để phân loại lỗi: missing row, wrong label mapping, wrong current, wrong previous, wrong scope/period hydration.
- Giữ `partial_mapping`, `partial_source_coverage`, `value_semantic_conflict`, `no_structural_rows` như tín hiệu debug thay vì biến chúng thành release gate.
- Mục tiêu chất lượng dài hạn vẫn là >90%, tốt nhất >95%, nhưng đó là KPI theo dõi, không phải điều kiện chặn trong giai đoạn debug.
