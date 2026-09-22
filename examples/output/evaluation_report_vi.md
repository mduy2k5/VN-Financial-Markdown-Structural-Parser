# Báo cáo đánh giá kết quả example

## 1. Phạm vi đánh giá

- **Đầu vào:** [synthetic_high_coverage_statement.md](../synthetic_high_coverage_statement.md)
- **Loại dữ liệu:** báo cáo tài chính mô phỏng, có B01, B02, B03 và thuyết minh.
- **Cấu hình:** tự nhận diện sector, schema `schema_v1_7`, notes bật, chỉ đọc dữ liệu Markdown nguồn.
- **Manifest:** [manifest.json](./manifest.json)
- **Report JSON:** [synthetic_high_coverage_statement__b2b4b67ea02e0ba9.json](./reports/synthetic_high_coverage_statement__b2b4b67ea02e0ba9.json)
- **Thời điểm chạy:** `2026-09-21T16:59:29.541706+07:00`
- **Report ID:** `r_b2b4b67ea02e0ba9`
- **SHA-256 đầu vào:** `b2b4b67ea02e0ba9dbc29a03df7e6f51a111d0e2cd8772cc8ec2596a29ce61eb`

## 2. Kết luận điều hành

Example chạy thành công qua pipeline đầy đủ. Cả ba báo cáo chính đều đạt trạng
thái `ok`, không có dòng chưa map, không có xung đột kỳ và quality gate cho phép
sử dụng.

`eligible_for_use=true` ở đây có nghĩa là file phù hợp làm fixture kiểm thử
parser/schema. Đây không phải xác nhận rằng số liệu mô phỏng là số liệu tài chính
thật hoặc có giá trị pháp lý.

## 3. Kết quả theo báo cáo

| Thành phần | Trạng thái | Dòng đầu vào | Đã map | Chưa map | Tỷ lệ map | Độ phủ kỳ hiện tại / kỳ trước |
|---|---:|---:|---:|---:|---:|---:|
| B01 – Bảng cân đối kế toán | `ok` | 60 observations | — | — | — | 100% / 100% |
| B02 – Kết quả hoạt động kinh doanh | `ok` | 18 | 18 | 0 | 100% | 100% / 100% |
| B03 – Lưu chuyển tiền tệ | `ok` | 20 | 20 | 0 | 100% | 100% / 100% |

### B01 – Bảng cân đối kế toán

- 205 semantic items được dựng từ schema.
- 60 observations nguồn được giữ làm bằng chứng.
- 78 item có giá trị ở ít nhất một kỳ.
- Độ phủ kỳ hiện tại và kỳ trước đều đạt 100%.
- Quan hệ tài sản – nguồn vốn được giữ trong cây semantic.

### B02 – Báo cáo kết quả hoạt động kinh doanh

- 18/18 dòng được map vào schema doanh nghiệp.
- Không có dòng `unmapped` hoặc `ambiguous`.
- 7 công thức được kiểm tra; 7 đạt, 0 lỗi.
- Tỷ lệ pass công thức: 100%.

### B03 – Báo cáo lưu chuyển tiền tệ

- Sector nhận diện: `enterprise`.
- Phương pháp nhận diện: `indirect`.
- 20/20 dòng được map vào schema.
- Không có dòng `unmapped` hoặc `ambiguous`.
- 2 công thức được kiểm tra; 2 đạt, 0 lỗi.
- Tỷ lệ pass công thức: 100%.

## 4. Kết quả phần thuyết minh

- Trạng thái: `parsed`.
- Vùng thuyết minh: dòng 379–743.
- Độ tin cậy vùng: `0.97`.
- Số section nhận diện: **31**.
- Số liên kết nội dung: **17**.
- `row_count`: **2**.

`row_count=2` không có nghĩa là chỉ còn hai mục thuyết minh. Phần lớn nội dung
thuyết minh của example là văn bản giải thích và các câu tuyên bố loại trừ dữ
liệu thật; bộ trích xuất notes chỉ materialize các bullet có dạng dòng số liệu
thành `row`. Toàn bộ phần văn bản vẫn nằm trong vùng notes và được giữ trong
source report.

Các nhóm thuyết minh có trong file gồm tiền, đầu tư, phải thu, hàng tồn kho, tài
sản cố định, công nợ, vay, vốn chủ sở hữu, doanh thu, chi phí, thuế, dòng tiền,
rủi ro, bên liên quan, cam kết, sự kiện sau kỳ, hoạt động liên tục và license.

## 5. Quality gate

```text
quality.status                 = ok
quality.gate.status            = ok
quality.gate.eligible_for_use  = true
periods.conflict               = false
issues                         = []
```

Chính sách áp dụng là `strict_source_backed_quality_gate_v1`. Không có cảnh báo
về thiếu mapping, lỗi công thức, xung đột kỳ hoặc thiếu độ phủ.

## 6. Kiểm tra dữ liệu mô phỏng

- Front matter có `synthetic_sample: true`.
- Có license `Synthetic Data License 1.0`.
- Không tìm thấy literal `_id` hoặc `s3_key` trong file input.
- Không có chữ ký, con dấu, địa chỉ thật, mã số thuế thật hoặc thông tin liên hệ thật.
- Đã so sánh token số có từ 6 chữ số trở lên với file CTR được dùng làm cảm hứng:
  - Example: 152 token duy nhất.
  - File CTR: 834 token duy nhất.
  - Số token trùng chính xác: **0**.

Đối chiếu số liệu trên chỉ chứng minh rằng example không lặp lại các token số lớn
của file CTR đã kiểm tra; nó không phải là chứng nhận pháp lý cho mọi nguồn dữ
liệu bên ngoài.

## 7. Đánh giá cấu trúc và khả năng tái sử dụng

### Điểm đạt

- Markdown có cấu trúc trang, heading và cây bullet rõ ràng.
- B01, B02 và B03 được tách khỏi phần thuyết minh đúng ranh giới.
- Quan hệ cha–con ở B01 được bảo toàn trong semantic tree.
- Hai kỳ 2026 và 2025 được nhận diện nhất quán.
- Các dòng âm được biểu diễn bằng ngoặc đơn và được chuẩn hóa đúng dấu.
- File phù hợp làm regression fixture cho parser, mapper, schema và notes.

### Giới hạn cần ghi nhận

- Đây là dữ liệu mô phỏng, không dùng để đánh giá chất lượng số liệu của doanh
  nghiệp thật.
- `row_count` của notes thấp hơn số section vì notes chủ yếu là prose, không phải
  bảng số liệu có thể materialize thành row.
- Kết quả `ok` phản ánh tính nhất quán của fixture và pipeline, không thay thế
  kiểm định trên nhiều bố cục báo cáo thực tế.

## 8. Kết luận cuối

Example đạt yêu cầu để đưa vào thư mục mẫu/regression test của dự án. Kết quả
chạy đầy đủ cho thấy parser nhận diện được ba báo cáo chính, map đủ các dòng có
giá trị, kiểm tra công thức thành công và đọc được phần thuyết minh theo section.

File này nên được sử dụng cho kiểm thử kỹ thuật và minh họa; không được dùng như
báo cáo tài chính, hồ sơ thuế, chứng từ kế toán hoặc tài liệu pháp lý.
