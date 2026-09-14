# Structural Parsing Guide — BVH

## 1. Scope
Guide này được xây dựng riêng từ `BVH_BCTC_2025_hop_nhat_kiem_toan(1).md`, gồm 115 Content blocks. Không gộp pattern/coverage từ BVB, ACB, ABB hoặc BAB.

## 2. Dataset observations
BVH là dataset doanh nghiệp/bảo hiểm và có representation biến đổi rõ rệt giữa các trang. Có ít nhất bốn hình thức quan trọng: Markdown table nhiều cột; nested bullet dạng `Mã số -> Chỉ tiêu -> Thuyết minh -> 2025/2024`; period-container làm parent; và inline/pipe rows. Một số trang còn chứa lời dẫn hội thoại của LLM như “Tuyệt vời!...”, phải coi là noise preprocessing chứ không phải financial node.

## 3. Canonical model
```json
{"label":null,"qualifier":null,"note":null,"values":[{"raw_value":null,"period":null,"unit":null,"role":null}],"children":[]}
```
`raw_value` luôn được bảo toàn.

## 4. Structural patterns
P010 qualifier_container; P006 markdown_table_row; P008 pipe_delimited_inline_row; P002 period_container; P005 label_multi_period_inline; P007 named_attribute; P003 period_value_attribute; P004 label_value_inline; P001 label_or_container.

Priority: `P010 > P006 > P008 > P002 > P005 > P007 > P003 > P004 > P001`.

## 5. BVH-specific parsing issue: mixed representation
Trang 10 dùng table chuẩn với các cột Mã số/Tài sản/Thuyết minh/2025/2024, trong khi trang 11 chuyển thành bullet tree với `Mã số`, label, `Thuyết minh`, `Ngày 31 tháng 12 năm 2025`, `Ngày 31 tháng 12 năm 2024`. Hai dạng có thể cùng semantic meaning nhưng không được parse bằng cùng một local extraction rule. Parser phải detect representation trước, sau đó mới canonicalize.

## 6. Hierarchy
Bullet hierarchy dựa trên indentation theo nearest-less-indented. P002 truyền period/unit. P007 attach attribute; `Thuyết minh` map note, `Mã số` nên lưu ordinal/code riêng. Table có scope/schema riêng và không dùng indentation.

## 7. Primitive recognition
Value gồm số nhóm bằng dấu chấm, ngoặc âm, decimal comma, plain integer và `-`. Period gồm full Vietnamese dates và fiscal-year labels. Unit gồm VND/VNĐ/đồng, %, cổ phần. Date spans phải được mask trước value detection để tránh lấy 31, 12, 2025 thành số liệu.

## 8. Noise / ambiguity
Loại root page-number bullet. LLM conversational preamble là prose noise. Generic `label:value` có thể là thông tin doanh nghiệp, tỷ lệ hay financial amount; structural parser không tự phân loại nghiệp vụ. Nếu mục tiêu downstream chỉ là BCTC chính, cần section gating.

## 9. Coverage
Inventory scoped: 3389 samples = 3.261 bullet nodes sau noise + 128 Markdown table data rows. Tất cả được phân loại bởi grammar hiện tại, coverage structural 100%. Con số này không phải parser accuracy.

## 10. Recommended pipeline
```text
raw Markdown
 -> split Page/Content
 -> remove Metadata + LLM preamble/footer noise
 -> detect Markdown tables
 -> parse bullet tree
 -> resolve period/header context
 -> primitive recognizers (mask dates first)
 -> pattern selection by priority
 -> attach attributes / propagate period
 -> canonical structural nodes
 -> UNKNOWN fallback when context insufficient
```
