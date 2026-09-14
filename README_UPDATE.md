# README_UPDATE — v14 reconciliation debug build

V14 tiếp tục giai đoạn debug, không có quality gate và không chặn output theo accuracy.

## Mục tiêu

- Financial Position: giảm miss còn lại bằng cách mở rộng nhận diện scope và hợp nhất source observations.
- Cash Flow: ghép các occurrence cùng label để phục hồi cặp current/previous tốt hơn, đặc biệt khi LLM làm mất mã số hoặc tách kỳ qua nhiều block.
- Income: giữ nguyên semantic extractor/mapping; chỉ chạy reconciliation trên source-observation layer, không mở rộng alias hàng loạt.

## Thay đổi chính

1. Financial Position scope v14
   - nhận `BẢNG CÂN ĐỐI KẾ TOÁN`;
   - nhận `BÁO CÁO CÂN ĐỐI KẾ TOÁN`;
   - nhận `BÁO CÁO TÌNH HÌNH TÀI CHÍNH`;
   - nối các trang `(tiếp theo)`;
   - fallback từ B02/TCTD, `TỔNG CỘNG TÀI SẢN`, `TỔNG NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU` khi heading đầu bị LLM/OCR làm mất.

2. Source reconciliation
   - identity chính: normalized label;
   - Cash Flow thêm section vào identity;
   - code chỉ là supporting identity;
   - merge complementary current/previous;
   - ưu tiên giá trị có nhiều evidence nhất;
   - không overwrite semantic node đã có giá trị;
   - giữ conflict trong diagnostics thay vì ép sửa.

3. Diagnostics mới

```text
diagnostics.source_observation_reconciliation
```

bao gồm:

```text
input_source_nodes
output_source_nodes
merged_groups
removed_duplicate_nodes
conflicting_groups
```

## Chạy

Dùng cùng command v13, chỉ đổi output sang `comparison_v14`.

Mục tiêu >90% / >95% vẫn chỉ là KPI theo dõi trong giai đoạn debug, không phải gate.
