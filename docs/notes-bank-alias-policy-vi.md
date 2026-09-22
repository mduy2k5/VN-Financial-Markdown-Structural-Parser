# Alias cho thuyết minh BCTC ngân hàng

## Phạm vi

`resources/schemas/notes_aliases_bank_v1.json` là catalog tùy chọn cho vùng
B05/TCTD. Catalog này chỉ gắn `alias_id` cho section hoặc dòng đã có bằng
chứng tên/kỳ rõ ràng. Nó không được dùng để loại dòng, đổi nhãn nguồn hay ép
thuyết minh về cấu trúc hai cột của B01–B03.

## Quy tắc lưu dữ liệu

- Khớp alias: lưu thêm metadata `canonical_plus_raw`.
- Không khớp alias: lưu `raw_tree`, gồm nhãn gốc, cây cha-con, giá trị theo
  đúng thứ tự, `raw_cells`, header, kỳ và `source_column`.
- Bảng có trên hai cột hoặc dòng có trên hai giá trị: lưu theo `raw_matrix`;
  số cột không bị giới hạn bởi schema alias.
- Alias chỉ khớp exact trong phạm vi section. Không fuzzy-match để tránh đưa
  cùng một nhãn như `Tổng cộng`, `Giá gốc` vào sai bảng.
- Nhãn lặp lại trong cùng section mà chưa có hierarchy/block context đủ mạnh
  cũng không được gán alias; chúng đi vào `raw_tree` để tránh gộp nhầm các
  bảng khác nhau.

Vì vậy, thêm một dòng nghiệp vụ mới vào B05 không cần sửa schema ngay: dòng
được giữ nguyên trước, sau đó mới có thể bổ sung alias khi đã có đủ bằng chứng
từ nhiều báo cáo ngân hàng.

## Cách bật/tắt

- `--notes-alias-profile auto`: tự bật `bank_v1` cho báo cáo ngân hàng;
- `--notes-alias-profile bank_v1`: bật tường minh;
- `--notes-alias-profile none`: tắt annotation và quay về lưu cây nguồn.

Đây là lớp bổ sung độc lập. Tắt alias không làm thay đổi parser B01–B03 hay
giá trị Notes đã trích xuất; chỉ bỏ metadata alias.

## Kiểm tra hồi quy

Case VCB dùng để kiểm tra:

- dòng inline `60.984.052 (31/12/2025), 38.999.507 (31/12/2024, đã kiểm toán)`
  trở thành hai giá trị có `source_column` 1 và 2;
- bảng Markdown giữ nguyên header và raw cell;
- các dòng không có trong catalog vẫn xuất hiện với `storage_mode=raw_tree`;
- các panel lặp lại như `Triệu VND` không bị gộp mất thứ tự nguồn.
