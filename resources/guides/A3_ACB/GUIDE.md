# Structural Parsing Guide — ACB

## 1. Scope

Guide này được xây dựng **riêng từ** `ACB_BCTC_2025_hop_nhat_kiem_toan.md`, gồm 100 page blocks. Không gộp pattern, examples hay coverage từ ABB/BAB.

Mục tiêu là đặc tả cấu trúc Markdown/text bán cấu trúc để code có thể nhận diện node, hierarchy, period, note, unit và raw value. Guide **không** map chỉ tiêu vào schema B02/B03/B04 và không thực hiện semantic normalization nghiệp vụ.

## 2. Dataset observations

ACB có ba nhóm biểu diễn số liệu nổi bật:

1. **Parent label + child attributes**: `Thuyết minh`, `Tại ngày 31.12.2025`, `Tại ngày 31.12.2024`.
2. **Label + hai value-period trên cùng dòng**: dùng dấu phẩy hoặc `|`, phổ biến ở B02 trang tiếp theo và B04.
3. **Period-container + child label:value**: node chỉ chứa `31.12.2025` / `31.12.2024`, sau đó các child mang số liệu.

Điểm số 3 phải được xử lý riêng. Nếu parser coi `31.12.2025` là numeric value thì hierarchy của nhiều thuyết minh sẽ sai.

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

`raw_value` được bảo toàn tuyệt đối. Ví dụ `(7.624.729)` vẫn là `(7.624.729)` và `-` vẫn là `-`.

## 4. Primitive recognizers

Chi tiết machine-readable nằm trong `field_patterns.json`.

### Value

Quan sát được số dùng dấu chấm phân nhóm, số âm bằng ngoặc, decimal comma, số lượng cổ phiếu lớn và dấu `-`.

Không normalize ở structural layer.

### Period

Các dạng chính:

- `Tại ngày 31.12.2025`
- `31.12.2025`
- `Năm 2025`
- `năm 31.12.2025`

Period có thể nằm ở cùng dòng value hoặc trở thành một parent node riêng.

### Note

ACB có ít nhất ba dạng:

- `Thuyết minh: 4`
- `(Thuyết minh 22)`
- `(Thuyết minh trang 15)`

`Thuyết minh trang 15` không nên tự động đồng nhất với note id `15` nếu downstream yêu cầu số thuyết minh.

### Unit

Các unit nổi bật: `triệu VND`, `triệu đồng`, `%`, `VND/cổ phiếu`, `đồng/cổ phiếu`, `cổ phiếu`.

## 5. Structural patterns

### P010 — qualifier_container
Qualifier-only node như `Trong đó:`.

### P002 — period_container
Node chỉ là period và làm parent cho các child value. Đây là pattern riêng quan trọng của ACB.

### P005 — label_multi_period_inline
Một label chứa ít nhất hai value-period explicit. Separator có thể là `,` hoặc `|`.

### P007 — named_attribute
Các key cấu trúc như `Thuyết minh`, `Tên công ty`, `Lĩnh vực kinh doanh`, `Tiêu chí`.

### P003 — period_value_attribute
Period nằm ở lhs trước `:` và value ở rhs.

### P004 — label_value_inline
Fallback cho `label: numeric/value`. Pattern này cố ý structural, không khẳng định mọi numeric token là chỉ tiêu tài chính.

### P001 — label_or_container
Fallback bullet text/container.

## 6. Pattern priority

```text
P010 qualifier_container
P002 period_container
P005 label_multi_period_inline
P007 named_attribute
P003 period_value_attribute
P004 label_value_inline
P001 label_or_container
```

Specific pattern phải thắng generic pattern.

## 7. Hierarchy

Nguồn tín hiệu chính là indentation. Các mức phổ biến là 0, 4, 8, 12, 16 và 20 spaces.

Parent = bullet gần nhất phía trước có indentation nhỏ hơn lớn nhất.

P003/P007 attach vào parent. P002 và P010 tạo context cho subtree.

Markdown heading chỉ tạo section context, không được dùng để sửa parent bằng kiến thức nghiệp vụ.

## 8. Important ambiguities

`label:value` có thể là financial amount, tỷ lệ, số lượng cổ phiếu, số năm hoặc một structured fact. Structural parser chỉ nhận cấu trúc; financial parser downstream phải dùng section/schema context.

Các parenthetical chứa năm hoặc số luật có thể tạo false numeric candidates nếu regex quá rộng. Value detection phải ưu tiên rhs/clause và explicit unit/period.

Các item number như `01.`, `14.3.` hoặc `(i)` nên được tách thành ordinal khi cần nhưng không được dùng làm semantic mapping.

## 9. Noise and UNKNOWN policy

Ba bullet chỉ chứa số trang ở root được xác định là document footer noise và loại khỏi denominator.

Plain OCR fragments ngoài bullet tree không được ép vào hierarchy.

Nếu một dòng mất indentation và không còn explicit period/schema context, parser phải giữ UNKNOWN thay vì đoán.

## 10. Coverage

Scored inventory:

```json
{
  "raw_content_bullets": 3673,
  "excluded_noise": 3,
  "total_samples": 3670,
  "matched_samples": 3670,
  "unknown_samples": 0,
  "coverage": 1.0
}
```

Coverage **100%** chỉ có nghĩa toàn bộ bullet structural nodes trong scope có thể được phân loại bằng grammar trên. Nó **không** có nghĩa extraction precision = 100%.

## 11. Recommended parser order

```text
Markdown
  -> split Page / Content
  -> remove Metadata + document noise
  -> parse headings
  -> parse bullet indentation tree
  -> primitive field recognizers
  -> pattern selection by priority
  -> propagate period / qualifier context
  -> attach note / period-value attributes
  -> validate raw preservation
  -> UNKNOWN routing
  -> canonical structural nodes
```

Đối với ACB, parser production nên ưu tiên implement chắc `period_container` và `multi_period_inline` trước khi thêm heuristic phức tạp.
