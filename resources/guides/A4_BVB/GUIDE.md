# Structural Parsing Guide — BVB

## 1. Scope

Guide này được xây dựng **riêng** từ `BVB_BCTC_2025_hop_nhat_kiem_toan.md`, gồm 81 page blocks. Không gộp pattern, ví dụ hay coverage từ ACB, ABB hoặc BAB.

Mục tiêu là đặc tả cấu trúc Markdown/text bán cấu trúc để phát triển parser bằng code. Guide không map chỉ tiêu nghiệp vụ sang B02/B03/B04 schema và không normalize số.

## 2. Dataset observations

BVB có nhiều hình thức cấu trúc cùng tồn tại:

1. `label -> Thuyết minh -> Số cuối năm/Số đầu năm`.
2. `label: value (Cuối năm); value (Đầu năm)` trên cùng dòng.
3. `period-container -> child label:value`, phổ biến trong thuyết minh.
4. Bullet dùng cả `*` và `-`.
5. Một số multi-column rows dùng `|` nhưng không phải Markdown table.
6. Có một Markdown pipe table thực sự trong phần chính sách phân loại nợ.
7. B04 có một số đoạn cột năm bị tái cấu trúc thành các block riêng, nên period context không phải lúc nào cũng nằm trong từng bullet.

## 3. Canonical structural model

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

`raw_value` phải giữ đúng nguồn: `(1.086.853)` không đổi thành số âm ở structural layer và `-` không đổi thành `0`.

## 4. Structural patterns

### P010 — qualifier_container
Qualifier-only như `Trong đó:`.

### P006 — markdown_table_row
Data row trong Markdown pipe table có header/schema explicit.

### P008 — pipe_delimited_inline_row
Bullet chứa nhiều segment phân tách `|`, ví dụ USD/EUR/Các ngoại tệ khác/Tổng cộng.

### P002 — period_container
Node chỉ chứa period như `Số cuối năm`, `Năm nay`, `Cuối năm`, `Dư nợ cuối năm`.

### P005 — label_multi_period_inline
Một label chứa từ hai value-period explicit, thường phân cách bằng `;`.

### P007 — named_attribute
Key:value structural attribute như `Thuyết minh`, `Số liệu thuyết minh`, `Chức vụ`, `Diễn giải`.

### P003 — period_value_attribute
Period ở lhs, value ở rhs.

### P004 — label_value_inline
Generic `label:value`, chỉ dùng sau các pattern cụ thể hơn.

### P001 — label_or_container
Fallback text/container node.

## 5. Priority

```text
P010 qualifier_container
P006 markdown_table_row
P008 pipe_delimited_inline_row
P002 period_container
P005 label_multi_period_inline
P007 named_attribute
P003 period_value_attribute
P004 label_value_inline
P001 label_or_container
```

## 6. Primitive recognizers

Chi tiết nằm trong `field_patterns.json`.

### Value

Quan sát được số phân nhóm bằng dấu chấm, số âm trong ngoặc, decimal comma, range và dấu `-`.

### Period

Các token quan trọng: `Số cuối năm`, `Số đầu năm`, `Năm nay`, `Năm trước`, `Cuối năm`, `Đầu năm`, `Dư nợ cuối năm`, `Dư nợ đầu năm`.

### Unit

Các unit gồm `Triệu đồng`, `triệu VND`, `%`, `%/năm`, `đồng/cổ phiếu`, và currency roles như `USD`, `EUR`.

### Note

Có `Thuyết minh: 5`, `Số liệu thuyết minh: 24`, `(Thuyết minh 29)`. Parenthetical số thuần như `(15)` nên giữ `reference_raw` nếu không có marker rõ.

## 7. Hierarchy

Parent-child dựa trên indentation và hỗ trợ cả marker `*` lẫn `-`.

Không cố định indentation level vì dataset có một số mức lệch. Dùng quy tắc **nearest previous node with lower indentation**.

P002 truyền period/unit context cho subtree. P003/P007 attach vào parent. P010 truyền qualifier.

P008 và P006 tự chứa schema/column pairing riêng.

## 8. B04 caveat

B04 của BVB có đoạn số liệu hai năm bị tái biểu diễn thành hai block thay vì mỗi dòng có cả hai period. Nếu period nằm ở plain heading ngoài bullet, parser production cần có **section/header context resolver** trước pattern matching.

Không được tự ghép hai block chỉ dựa vào việc label giống nhau nếu không có period/header evidence.

## 9. Noise policy

Có 3 root bullet chỉ là số trang: `50`, `61`, `70`. Chúng bị loại khỏi structural samples.

OCR footer/logo fragments ngoài bullet/table không được ép vào tree.

## 10. Coverage

```json
{
  "raw_content_bullets": 2679,
  "excluded_noise_bullets": 3,
  "markdown_table_data_rows": 2,
  "total_samples": 2678,
  "matched_samples": 2678,
  "unknown_samples": 0,
  "coverage": 1.0
}
```

Coverage **100%** là coverage phân loại structural samples trong scope, không phải parser accuracy.

## 11. Recommended implementation order

```text
Markdown
  -> split Page / Content
  -> remove Metadata
  -> remove root page-number noise
  -> detect Markdown tables
  -> detect '*' and '-' bullet nodes
  -> compute indentation tree
  -> resolve section/header context
  -> primitive recognizers
  -> pattern selection by priority
  -> propagate period/unit/qualifier
  -> attach note/value attributes
  -> preserve raw values
  -> UNKNOWN routing
  -> canonical structural nodes
```

Đối với BVB, ba phần nên được implement chắc trước là `period_value_attribute`, `period_container`, và `multi_period/pipe-delimited inline rows`.
