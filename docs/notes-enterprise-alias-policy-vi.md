# Alias cho thuyết minh BCTC doanh nghiệp

## Cơ sở xây dựng

`resources/schemas/notes_aliases_enterprise_v1.json` là catalog tùy chọn cho
thuyết minh doanh nghiệp theo TT200. Catalog được đối chiếu với bốn mẫu Word
cũ B01, B02, B03 và B09 trong `docs/template/`, trong đó B09 là nguồn chính
cho các nhóm chính sách kế toán, thuyết minh Bảng cân đối kế toán, Kết quả
kinh doanh, Lưu chuyển tiền tệ và thông tin khác. Các tiêu đề biến thể thường
gặp trong báo cáo doanh nghiệp cũng được thêm như `title_aliases`.

B09 dùng lại số thứ tự ở nhiều nhóm. Vì vậy section chỉ được coi là khớp khi
có tiêu đề tương ứng; mã số một mình chỉ là fallback khi catalog có đúng một
section dùng mã đó. Tiêu đề có hậu tố `(tiếp theo)` được coi là phần tiếp của
mục gốc.

## Quy tắc lưu dữ liệu

- Khớp alias: chỉ thêm metadata `canonical_plus_raw`, không đổi nhãn hoặc giá
  trị nguồn.
- Không khớp alias: lưu `raw_tree`, gồm nhãn gốc, cây cha-con, giá trị theo
  đúng thứ tự, `raw_cells`, header, kỳ và `source_column`.
- Bảng có trên hai cột hoặc dòng có trên hai giá trị: lưu `raw_matrix`; số
  cột không bị giới hạn bởi catalog.
- Nhãn lặp trong một section không có hierarchy/block context đủ mạnh không
  được gán alias; dữ liệu vẫn còn nguyên trong cây nguồn.
- Fuzzy matching không được bật. Mục nghiệp vụ mới hoặc tên riêng của từng
  doanh nghiệp đi vào raw fallback cho đến khi có đủ bằng chứng để bổ sung.

## Cách bật/tắt

- `--notes-alias-profile auto`: tự bật `enterprise_v1` cho báo cáo doanh
  nghiệp;
- `--notes-alias-profile enterprise_v1`: bật tường minh;
- `--notes-alias-profile none`: tắt annotation và quay về lưu cây nguồn.

Đây là lớp bổ sung độc lập. Tắt alias không làm thay đổi parser B01–B03 hay
giá trị Notes đã trích xuất; chỉ bỏ metadata alias.
