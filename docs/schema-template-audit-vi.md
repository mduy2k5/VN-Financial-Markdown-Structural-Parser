# Ghi chú triển khai schema theo bộ mẫu

## Phạm vi đã kiểm tra

Đã đọc các mẫu trong `docs/template` cho B01, B02, B03, B09 doanh nghiệp,
ngân hàng, công ty chứng khoán và bảo hiểm nhân thọ/phi nhân thọ. Kết luận
chung là một schema dùng chung vẫn phù hợp cho phần lõi, nhưng các biểu mẫu
theo ngành có dòng riêng, mã riêng và đôi khi đổi cấu trúc cột. Vì vậy phần
bổ sung được tách thành overlay, không sửa trực tiếp schema baseline.

## Profile đang dùng

`schema_v1_11` là profile mặc định. Nó gồm:

- B01: tách `Phải trả nội bộ ngắn hạn` và `Phải trả nội bộ dài hạn`; bổ sung
  alias cho cách viết trong mẫu, dấu `(*)`, nguồn vốn XDCB và tổng nguồn vốn;
  bổ sung dòng ngân hàng `Dự phòng rủi ro khác (Dự phòng cho công nợ tiềm ẩn)`.
- B02 ngân hàng: giữ các nhánh tài sản/nợ/vốn đặc thù và alias theo mẫu NHNN;
  mã `Vốn đầu tư XDCB, mua sắm tài sản cố định` được đưa về cùng semantic node
  với vốn đầu tư XDCB.
- B02 chứng khoán: bổ sung các dòng doanh thu/chi phí phái sinh, ủy thác/đấu
  giá, sửa lỗi giao dịch, đầu tư và các dòng thu nhập toàn diện còn thiếu.
- B03 ngân hàng: bổ sung alias cho dòng nhận lãi, nhận thu nhập dịch vụ, các
  điều chỉnh gián tiếp, đầu tư bất động sản và tài trợ dài hạn theo mẫu NHNN.
- B03 chứng khoán trực tiếp: bổ sung nhóm mua/bán tài sản tài chính, hoạt động
  kinh doanh, đầu tư, tài chính và đối chiếu tiền cuối kỳ.
- B03 gián tiếp: bổ sung các dòng điều chỉnh phi tiền tệ, vốn lưu động, đầu tư,
  tài chính và các nhánh tiền đầu/cuối kỳ theo mẫu CTCK; giữ lại các công thức cũ.
- B02 chứng khoán: lưu lại các mã biểu mẫu thay thế của dòng lưu ký và OCI AFS
  bằng `form_code_variants`, không dùng mã làm identity duy nhất.

Notes chạy bằng pipeline riêng. Chế độ `legacy` vẫn là mặc định; `v2` chỉ xử
lý phần thuyết minh với cây cha-con, kỳ, measure và movement, không thay đổi
quyết định của B01/B02/B03.

Catalog Notes doanh nghiệp `enterprise_v1` đã được dựng riêng từ mẫu B09/DN
và đối chiếu với 27 báo cáo doanh nghiệp. Catalog có các nhóm I–IX, các mục
chính của B09 và các nhãn nghiệp vụ thường gặp; việc khớp dùng cả mã mục và
tiêu đề để xử lý việc B09 lặp lại số thứ tự. Mục không đủ bằng chứng vẫn giữ
`raw_tree`, bảng nhiều cột giữ `raw_matrix`. Profile `none` là rollback mà
không thay đổi cấu trúc/giá trị nguồn.

## Rollback

```powershell
python app/pipeline.py <input> --schema-profile schema_v1_7
python app/pipeline.py <input> --schema-profile schema_v1_9
python app/pipeline.py <input> --schema-profile schema_v1_10
python app/pipeline.py <input> --schema-profile baseline
python app/pipeline.py <input> --notes-parser-mode legacy
```

Rollback chỉ đổi profile chạy, không xóa hay ghi đè các schema overlay.

## Kiểm chứng

- Toàn bộ test suite: `160 passed`.
- Batch smoke trên `57` file Markdown với `schema_v1_11`, tắt Notes để cô lập
  ba báo cáo chính: `error_count=0`; cả 57 file đều được xử lý và sinh
  manifest. Các trạng thái `review_required` còn lại là quality gate của dữ
  liệu/độ phủ từng file, không phải lỗi khởi động schema.
- Profile mới và profile baseline đều chạy được trên mẫu chứng khoán BSI.
- BSI và CTG ở profile mới vẫn map đủ các statement chính; profile cũ vẫn có
  thể chọn để so sánh ngược mà không cần khôi phục file.

Manifest của lần chạy được giữ trong workspace tạm tại
`tmp/batch_v111_20260922/manifest.json`; đây là artifact kiểm chứng cục bộ,
không phải dữ liệu production cần commit.

## Phần chưa coi là hoàn tất

Bộ ngân hàng, doanh nghiệp và chứng khoán vẫn là phạm vi production của profile
`schema_v1_11` cho các báo cáo chính. Phần Notes bảo hiểm hiện đã có profile
riêng `insurance_v1`, dùng chung cho báo cáo kết hợp nhân thọ/phi nhân thọ và
không trộn rule vào parser B01/B02/B03. Việc mở rộng schema mapping cho báo cáo
chính bảo hiểm vẫn là một hạng mục riêng, cần fixture/ground truth tương ứng.
