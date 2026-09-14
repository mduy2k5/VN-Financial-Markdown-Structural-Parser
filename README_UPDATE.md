# README_UPDATE — v22.2

## Mục tiêu

v22.2 là patch rất hẹp trên v22.1, chỉ hoàn thiện 8 dòng còn unmapped của
Income Statement ngành bảo hiểm. Không thay đổi broad extractor/mapping logic.

## 8 semantic node mới

1. `INCOME.INSURANCE.TOTAL_PREMIUM_REVENUE`
   - Doanh thu phí bảo hiểm

2. `INCOME.INSURANCE.REINSURANCE_COMMISSION_OTHER_REVENUE`
   - Hoa hồng nhượng tái bảo hiểm và doanh thu khác hoạt động kinh doanh bảo hiểm

3. `INCOME.INSURANCE.NET_INSURANCE_BUSINESS_REVENUE`
   - Doanh thu thuần từ hoạt động kinh doanh bảo hiểm

4. `INCOME.INSURANCE.ACCEPTED_REINSURANCE_CLAIMS_EXPENSE`
   - Chi bồi thường nhận tái bảo hiểm

5. `INCOME.INSURANCE.CLAIM_EXPENSE_REDUCTIONS`
   - Các khoản giảm trừ chi phí

6. `INCOME.INSURANCE.THIRD_PARTY_RECOVERY`
   - Thu đòi người thứ ba

7. `INCOME.INSURANCE.SALVAGE_RECOVERY`
   - Thu xử lý hàng bồi thường

8. `INCOME.INSURANCE.TOTAL_CLAIMS_AND_BENEFITS`
   - Tổng chi bồi thường và trả tiền bảo hiểm

## Nguyên tắc

- Không dùng ticker-specific mapping.
- Không map 8 dòng này vào các node aggregate cũ có semantics khác.
- Không đổi fuzzy threshold.
- Không đổi scope logic.
- Không đổi Income extractor.
- Không đổi Bank / Enterprise / Securities aliases.
- Không đổi bất kỳ Cash Flow file nào.
- Không thêm quality gate.

## Regression expectation

Với source BVH hiện tại, extractor v22.1 emit 49 Income rows.
Trước patch:
- mapped: 41
- unmapped: 8

Sau patch v22.2 local smoke:
- mapped: 49
- unmapped: 0

Đây chỉ là mapper/extractor smoke trên source BVH, không thay thế evaluator ground-truth 57 file.

## Ground-truth cần chạy lại

So sánh v22.2 với v22.1:

- Financial Position: phải giữ nguyên.
- Cash Flow: phải giữ nguyên.
- Income ngoài Insurance: phải giữ nguyên.
- BVH Income: kỳ vọng tăng từ 41/49 nếu evaluator dùng cùng semantic rows.
