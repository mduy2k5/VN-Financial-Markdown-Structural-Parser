# Structural Parsing Guide — ABB

## 1. Dataset overview

Bộ hướng dẫn này được xây dựng **riêng cho** `ABB_BCTC_2025_hop_nhat_kiem_toan.md`, gồm 88 page blocks. Không sử dụng pattern hay coverage của BAB để bổ sung giả tạo cho ABB.

Dataset ABB có ba hình thức cấu trúc nổi bật: nested Markdown bullets; Markdown pipe tables; và một số block OCR suy giảm thành các dòng text/value rời. Phần báo cáo tình hình tài chính và nhiều thuyết minh thường biểu diễn `label -> Số cuối năm / Số đầu năm`, trong khi báo cáo kết quả hoạt động có table rows, và báo cáo lưu chuyển tiền tệ có nhiều `label + hai value-period inline`.

Đánh giá line-oriented structural inventory: **3,287 samples**, trong đó **3,216 matched**, **71 UNKNOWN**, coverage **97.84%**. UNKNOWN được giữ lại thay vì tạo rule yếu.

## 2. Canonical semantic model

```json
{
  "label": null,
  "qualifier": null,
  "note": null,
  "values": [
    {
      "raw_value": null,
      "period": null,
      "unit": null,
      "role": null
    }
  ],
  "children": []
}
```

`raw_value` luôn bảo toàn đúng text nguồn. Không đổi `(1.200.078)` thành số âm, không đổi dấu chấm/dấu phẩy, và không đổi `-` thành `0` ở giai đoạn structural parsing.

## 3. Primitive field recognition

Các recognizer dùng chung nằm trong `field_patterns.json`.

### Value

Các dạng thực tế gồm số nhóm bằng dấu chấm (`13.021.715`), số âm bằng ngoặc (`(1.200.078)`), decimal dùng dấu phẩy (`5,30`), range (`5,30-10,00`) và dấu `-`.

### Period

Các token phổ biến gồm `Số cuối năm`, `Số đầu năm`, `Năm nay`, `Năm trước`, `Cuối năm`, `Đầu năm`, ngày đầy đủ và năm explicit.

Relative period chỉ được map sang semantic role như `current_period`/`previous_period`; calendar date cụ thể phải đến từ context của báo cáo nếu cần.

### Unit

Quan sát được `triệu đồng`, `Triệu VND`, `%`, `%/năm`, `đồng/cổ phiếu`. Unit chỉ được propagate khi cùng node hoặc header/table context thể hiện rõ unit dùng chung.

### Note

Recognizer đáng tin cậy nhất là explicit `Thuyết minh: <number>`.

### Qualifier

Qualifier-only container được chứng minh rõ là `Trong đó:`. Các câu văn bắt đầu bằng `Bao gồm ...` nhưng chứa nội dung dài không được tự coi là qualifier container.

## 4. Hierarchy rules

Tín hiệu chính là **bullet indentation**. Parent của một bullet là bullet gần nhất phía trước có indentation nhỏ hơn lớn nhất. Dataset chủ yếu dùng 0/4/8/12 spaces.

`Thuyết minh`, `Số cuối năm`, `Số đầu năm`, `Năm nay`, `Năm trước` ở dạng child attribute phải attach vào parent theo indentation.

Markdown heading chỉ tạo section context. Không được dùng kiến thức nghiệp vụ để gán parent khi indentation/layout đã hỏng.

Markdown table tạo một hierarchy riêng: header xác lập schema cột, các data row sau là siblings sử dụng schema đó.

## 5. Structural patterns

### P010 — qualifier_container
Priority 140. Match qualifier-only như `Trong đó:` và áp qualifier cho subtree.

### P006 — markdown_table_row
Priority 130. Parse theo header/schema của pipe table. Đây là pattern đặc biệt quan trọng cho báo cáo kết quả hoạt động.

### P005 — label_multi_period_inline
Priority 120. Một label có từ hai cặp value-period trên cùng dòng, ví dụ hai số `Năm nay`/`Năm trước`.

### P007 — named_attribute
Priority 110. Các key như `Thuyết minh`, `Chức vụ`, `Tỷ lệ sở hữu %`. Chỉ `Thuyết minh` map trực tiếp vào canonical `note`.

### P003 — period_value_attribute
Priority 100. Các child như `Số cuối năm: ...`, `Số đầu năm: ...`.

### P004 — label_value_inline
Priority 70. `label: value` không thuộc period/named-attribute.

### P009 — value_only_positional
Priority 60. Chỉ dùng khi value-only bullet vẫn nằm trong schema/header deterministic.

### P001 — label_or_container
Priority 20. Fallback structural label/container cho bullet có text nhưng chưa có value trên cùng dòng.

Chi tiết machine-readable nằm trong `structural_patterns.json`.

## 6. Pattern priority

Thứ tự kiểm tra:

```text
P010 qualifier_container
P006 markdown_table_row
P005 label_multi_period_inline
P007 named_attribute
P003 period_value_attribute
P004 label_value_inline
P009 value_only_positional
P001 label_or_container
```

Specific pattern luôn thắng generic pattern.

## 7. Ambiguous cases

Một node `value_only` không được gán period nếu không có ordered header/sibling schema rõ.

Dòng có nhiều số nhưng các số là tỷ lệ, ngày hoặc tham chiếu pháp lý có thể hình thức giống financial value. Structural parser chỉ trích field theo syntax; nếu production parser chỉ nhắm số liệu BCTC, nên thêm section scope trước pattern matching.

Nếu table bị mất separator/header do OCR, không được tự đoán cột dựa trên nghiệp vụ.

## 8. Unknown cases

Nhóm UNKNOWN chính là **degraded positional numeric lines**: số liệu bị tách khỏi label/header và xuất hiện như các dòng rời. Dataset có 71 sample loại này trong inventory.

Khuyến nghị: block-level recovery riêng hoặc Gemini fallback. Không tạo regex gán giá trị theo vị trí tuyệt đối toàn tài liệu vì không ổn định.

## 9. Coverage

```json
{
  "total_samples": 3287,
  "matched_samples": 3216,
  "unknown_samples": 71,
  "coverage": 0.9784
}
```

Coverage line-oriented đạt **97.84%**. Đây là coverage của structural pattern inventory, không phải parser accuracy.

## 10. Recommendations for parser implementation

Pipeline đề xuất:

```text
raw Markdown
  -> split page/section
  -> identify table blocks + bullet nodes
  -> compute indentation tree
  -> primitive recognizers
  -> generic feature extraction
  -> pattern matching theo priority
  -> attach attribute children vào parent
  -> validate raw preservation
  -> ambiguous/UNKNOWN routing
  -> canonical nodes
```

Không normalize số trong bước này. Không map sang B02/B03/B04 trong structural guide. Không dùng label nghiệp vụ làm pattern ID.

Đối với ABB, implementation nên ưu tiên hỗ trợ thật chắc ba cơ chế: `attribute children`, `multi-period inline`, và `Markdown table`. OCR positional recovery nên để thành module riêng vì đó là failure mode khác với structural parsing bình thường.

