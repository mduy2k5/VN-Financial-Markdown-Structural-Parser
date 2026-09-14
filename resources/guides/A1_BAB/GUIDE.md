# Structural Parsing Guide

## 1. Dataset overview

Đã khảo sát toàn bộ `BAB.md` (51 page marker, 4.407 dòng). Trong các `## Content` có 2.000 bullet; theo định nghĩa sample cấu trúc (bullet có value/period/unit/note/qualifier hoặc có descendant mang các tín hiệu đó, đồng thời loại prose dài không có cấu trúc field rõ), có **1,835 samples**. 1,822 samples match deterministic vào 10 pattern, 13 samples để `UNKNOWN`; coverage **99.29%**.

Điểm quan trọng: dataset không dùng một template duy nhất. Cùng dữ liệu hai kỳ có thể nằm inline (`value unit (period); value unit (period)`), nằm dưới label dưới dạng child `Năm/Ngày: value`, hoặc chỉ là hai value con dựa vào header cột. Vì vậy parser phải tách **structure detection** khỏi **primitive field recognition**.

## 2. Canonical semantic model

```json
{
  "label": null,
  "qualifier": null,
  "note": null,
  "values": [{"raw_value": "...", "period": null, "unit": null, "role": null}],
  "children": []
}
```

`raw_value` luôn giữ nguyên. `-`, `(1.564.458)`, `13.570,476` (nếu xuất hiện) không được tự sửa/normalize. Field không có bằng chứng thì `null`/`unknown`.

## 3. Primitive field recognition

- **Value:** quan sát số plain, số phân nhóm bằng `.`, số âm bằng ngoặc, và `-`. Trước khi nhận value phải mask date/year, numbering và note-reference.
- **Period:** `31/12/2025`, `Ngày 31/12/2025`, `Tại ngày ...`, `Số dư tại ngày ...`, `Năm 2025/2024`, `Năm nay/Năm trước`.
- **Unit:** `triệu đồng`, `Triệu đồng`, `triệu VND`, `Triệu VND`, `đồng`, `%`; unit có thể inline hoặc scoped ở header/node `Đơn vị`.
- **Note:** explicit `Thuyết minh: 8.2`; ngoài ra `5.1: 585.389` chỉ được hiểu `5.1` là note khi active table context chứng minh có cột Thuyết minh.
- **Role:** không thấy marker structural đáng tin cậy như `Trình bày lại`; không gán reported/restated chỉ dựa trên năm.
- **Qualifier:** structural forms quan sát được gồm `Trong đó:`, `Chi tiết:`, `Theo kỳ hạn:`, `Phân loại theo nguồn:`. Từ “bao gồm” trong prose không đủ bằng chứng.

Chi tiết regex/rule nằm trong `field_patterns.json`.

## 4. Hierarchy rules

Tín hiệu mạnh nhất là indentation của nested bullet (thường 0/4/8/12/16 spaces). Parent là bullet gần nhất phía trước có indent nhỏ hơn; khi indent giảm, pop stack. Markdown heading chỉ mở section scope và không được dùng để đảo quan hệ bullet. Period/unit header là context carrier, không phải parent override.

Không suy parent-child từ nghiệp vụ. Không tự nối tree qua `# Page` trừ khi có bằng chứng continuation rõ; nếu nối bảng qua trang mà column context không chắc chắn thì đánh `ambiguous`.

## 5. Structural patterns

| ID | Pattern | Priority | Count | Ý nghĩa |
|---|---|---:|---:|---|
| P001 | `label_multi_period_inline` | 100 | 68 | Label + >=2 value-period trong một node |
| P002 | `label_with_period_bearing_children` | 95 | 227 | Label/container + child/descendant period-value |
| P007 | `qualifier_node` | 92 | 13 | `Trong đó/Chi tiết/...` với subtree hoặc value |
| P003 | `label_with_positional_value_children` | 90 | 30 | Label + value-only children, map theo header cột |
| P004 | `period_value_attribute` | 85 | 517 | `Năm/Ngày/Tại ngày ...: value` |
| P005 | `label_single_value_inline` | 80 | 746 | Label/key + một value inline |
| P008 | `label_with_keyed_attribute_children` | 75 | 74 | Parent + các child `key:value` |
| P006 | `bare_value_positional` | 70 | 103 | Value-only node, cần context |
| P010 | `context_header_or_unit_carrier` | 60 | 26 | Period/unit/note header dùng làm context |
| P009 | `structural_container` | 50 | 18 | Container label chỉ giữ hierarchy |

### P001 — label_multi_period_inline

Nhận diện khi một node có label và ít nhất hai value + hai period inline. Tách label trước vùng value đầu tiên; chia segment bằng `;`/`,` khi chúng phân tách cặp; ghép period trong ngoặc với value ngay trước. Đây là pattern cụ thể nhất nên chạy đầu tiên.

### P002 — label_with_period_bearing_children

Dùng khi label cha chứa các child như `Năm 2025: ...`, `Ngày 31/12/2025: ...`. Child P004 không có label nghiệp vụ riêng được fold thành `values[]` của parent. Child có label riêng vẫn là child semantic node, không được hấp thụ.

### P003 — label_with_positional_value_children

Dùng cho table bị LLM trải dọc: label có hai child value-only, còn period/unit nằm ở header cột. Map theo index. Nếu số value không tương thích số cột thì `ambiguous`, không đoán.

### P004 — period_value_attribute

Period explicit + value cùng node. Đây thường là attribute child của P002. Period explicit thắng P005.

### P005 — label_single_value_inline

Dạng phổ biến nhất: `label: value`. Period có thể null hoặc inherited từ ancestor period scope. Nếu key là reserved field (`Thuyết minh`, `Đơn vị`) thì field recognizer xử lý trước, không coi là business label.

### P006 — bare_value_positional

Node chỉ có value. Không tự tạo label. Chỉ có thể gán period/label thông qua P003 hoặc ancestor context; thiếu context thì ambiguous.

### P007 — qualifier_node

Tách qualifier khỏi label và giới hạn scope theo indentation. `Trong đó:` rỗng có children là container; `Trong đó: <label>: <values>` có thể vừa mang qualifier vừa mang data.

### P008 — label_with_keyed_attribute_children

Parent có các child dimension/value như `Đến 01 tháng: ...`, `Tổng: ...`. Mỗi child thành semantic child riêng; không ép thành `values[]` của parent nếu key là một dimension/label độc lập.

### P009 — structural_container

Container chỉ giữ hierarchy khi dữ liệu nằm sâu hơn và không có direct extraction strategy mạnh hơn. Không kéo values từ descendants lên parent.

### P010 — context_header_or_unit_carrier

Header như `31/12/2025 (Triệu VND)` hoặc `Triệu đồng` được lưu vào context stack. Nó hỗ trợ P003/P006 nhưng không phát sinh business row độc lập.

## 6. Pattern priority

Thứ tự deterministic: **P001 → P002 → P007 → P003 → P004 → P005 → P008 → P006 → P010 → P009**. Sau detect phải chạy validation; pattern fail validation thì thử pattern tiếp theo.

Các exclusion quan trọng: có >=2 period/value inline thì P001, không P005; period explicit + một value thì P004, không P005; direct value-only children + column context thì P003; direct keyed-value children thì P008; P009 chỉ là fallback container.

## 7. Ambiguous cases

1. `5.1: 585.389`: `5.1` chỉ là note nếu header/table context có cột Thuyết minh; ngoài context đó không suy.
2. Hai value-only children nhưng thiếu/mất header period: giữ raw values nhưng period `null`, hoặc đánh ambiguous nếu downstream yêu cầu period.
3. Cross-page table continuation: không nối chỉ vì tên chỉ tiêu có vẻ liên quan.
4. Unit-only nodes ở bảng phức tạp: chỉ inherit trong scope indentation/column xác định; không broadcast toàn page.

Output ambiguity:

```json
{"status":"ambiguous","reason":"column/value count mismatch","candidate_patterns":["P003","P006"]}
```

## 8. Unknown cases

Có **13 UNKNOWN**. 11 là narrative bullet có từ tài chính/năm/số nhưng không có field structure đủ chắc; 2 là report title/document label lọt qua candidate heuristic. Đây không phải bằng chứng để tạo pattern tài chính mới. Khuyến nghị pre-filter document chrome/prose; nếu downstream vẫn cần biến chúng thành data thì dùng LLM fallback thay vì regex yếu.

## 9. Coverage

- Total structural samples: **1,835**
- Matched: **1,822**
- UNKNOWN: **13**
- Coverage: **99.29%**

Coverage cao không đồng nghĩa mọi node đều có đầy đủ period/unit/note. Pattern chỉ xác định extraction strategy; semantic fields thiếu vẫn phải null/unknown.

## 10. Recommendations for parser implementation

1. Parse Markdown thành page/heading/bullet tree trước; tuyệt đối không regex toàn văn một lượt.
2. Tạo feature extractor dùng chung: indent, bullet depth, inline value spans, period spans, unit spans, reserved keys, qualifier, child signatures, active column context.
3. Mask date/year/note/numbering trước value recognition để giảm false positive.
4. Dùng context stack tách biệt với parent stack: hierarchy và column context là hai khái niệm khác nhau.
5. Chạy pattern theo priority + validation; log `pattern_id`, confidence/evidence và raw source span.
6. Không normalize `raw_value` trong parser structural. Tạo stage normalization riêng sau extraction.
7. Mọi inheritance (period/unit) nên lưu provenance (`explicit`, `ancestor_scope`, `column_header`) để debug.
8. Với P003/P006, nếu context thiếu hoặc count mismatch thì ambiguous thay vì positional guess.
9. UNKNOWN/prose nên được pre-filter trước LLM fallback để tránh chi phí không cần thiết.
10. Dùng `coverage_report.json` làm baseline regression; khi thêm dataset mới, chỉ tạo pattern mới nếu extraction strategy thực sự khác.

---

Các file JSON là đặc tả máy đọc; tài liệu này cố ý giữ cùng ID, priority, count và policy với chúng.
