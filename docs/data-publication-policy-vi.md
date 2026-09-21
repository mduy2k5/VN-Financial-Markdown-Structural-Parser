# Chính sách công bố dữ liệu input/output

Ngày rà soát: 21/09/2026.

Tài liệu này là policy vận hành của repository, không phải ý kiến tư vấn pháp
lý. Trước khi public dữ liệu thật hoặc dùng cho sản phẩm thương mại, cần người
phụ trách pháp chế xác nhận theo nguồn cụ thể và điều khoản của nền tảng đã
thu thập dữ liệu.

## Kết luận cho dữ liệu hiện tại

Chưa đưa nguyên trạng `md_reports/`, `ground_truth/` hoặc
`output/row_scan_assist_final/` lên GitHub công khai.

Lý do đã kiểm tra trong workspace:

- 57 Markdown là bản OCR/serialize của báo cáo tài chính, không kèm manifest
  license hoặc giấy phép tái phân phối;
- metadata còn `_id`, `s3_key`, thời điểm xử lý và đường dẫn kho nội bộ;
- source có dấu hiệu chứa email, điện thoại, địa chỉ, chữ ký và thông tin nhận
  dạng;
- output production giữ tên source, hash, dòng nguồn, label, raw text hoặc
  provenance trong các report/audit; tổng output mới nhất khoảng 76 MiB.

Vì vậy, việc source có thể tải/xem công khai chỉ chứng minh khả năng truy cập
theo bối cảnh công bố; không tự nó chứng minh quyền tái bản toàn văn, quyền
phân phối lại hoặc quyền cấp license cho bản OCR và output phái sinh.

## Cơ sở pháp lý cần kiểm tra

- [Luật sửa đổi, bổ sung một số điều của Luật Sở hữu trí tuệ số
  07/2022/QH15](https://vanban.chinhphu.vn/?classid=1&docid=206240&org=&pageid=27160)
  có hiệu lực từ 01/01/2023. Quyền tác giả/quyền tài sản và việc sử dụng bản
  sao, tác phẩm phái sinh hoặc sưu tập dữ liệu phải được xem xét riêng; dữ liệu
  công khai không phải là giấy phép blanket cho toàn bộ cách trình bày báo cáo.
- [Luật Chứng khoán số 54/2019/QH14](https://vanban.chinhphu.vn/default.aspx?docid=198541&lang=vi&pageid=27160)
  và [Thông tư 96/2020/TT-BTC](https://vbpl.vn/FileData/TW/Lists/VBPQ/Attachments/146048/VanBanGoc_96-2020-TT-BTC.pdf)
  quy định nghĩa vụ công bố thông tin của chủ thể thuộc phạm vi điều chỉnh.
  Nghĩa vụ công bố nhằm bảo đảm tiếp cận thông tin; không nên suy diễn thành
  quyền tái phân phối không điều kiện lên một repository khác.
- [Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15](https://vanban.chinhphu.vn/?classid=1&docid=214590&pageid=27160&typegroup=)
  có hiệu lực từ 01/01/2026 và [Nghị định 356/2025/NĐ-CP](https://vbpl.vn/bocongan/Pages/vbpq-toanvan.aspx?ItemID=187276)
  có hiệu lực cùng ngày. Nghị định 356 nêu Nghị định 13/2023 hết hiệu lực từ
  thời điểm đó; policy không dùng Nghị định 13 làm căn cứ hiện hành.

Đây là cách đọc thận trọng từ các văn bản trên: cần tách ba câu hỏi độc lập
trước khi public: (i) báo cáo có được công bố không, (ii) bản cụ thể có được
sao chép/tái phân phối không, và (iii) artifact có chứa dữ liệu cá nhân hoặc
metadata nội bộ không.

## Điều kiện để đưa dữ liệu lên GitHub

### Input raw

Chỉ publish khi mỗi file có ít nhất:

1. nguồn chính thức hoặc nguồn được cấp phép;
2. URL nguồn, ngày truy cập, ticker, kỳ báo cáo và chủ thể phát hành;
3. căn cứ quyền sử dụng: license rõ ràng, permission của chủ sở hữu, hoặc
   clearance nội bộ có người chịu trách nhiệm;
4. bản đã loại metadata nội bộ, secret, thông tin cá nhân không cần thiết và
   nội dung không thuộc phạm vi demo.

Không commit `_id`, `s3_key`, URL bucket/private storage, token, cookie, đường
dẫn nội bộ hoặc nguyên văn phần chữ ký/địa chỉ nếu không cần cho test parser.

### Output và audit

Output là artifact phái sinh, không tự động được phép chỉ vì input đã công khai.
Trước khi publish phải:

- bỏ `raw_text` và provenance có thể tái tạo toàn văn khi không cần thiết;
- bỏ absolute local path, source metadata nội bộ và dữ liệu cá nhân;
- giữ schema/version, số liệu đánh giá và kết quả test ở mức tối thiểu cần cho
  tái lập;
- gắn attribution và ghi rõ output được tạo bởi parser, không phải báo cáo
  chính thức của doanh nghiệp.

### Release hiện tại

Repository public hiện chỉ nhận code/schema/test/docs. Có thể bổ sung fixture
synthetic hoặc evaluation summary đã redaction; không đưa 57 source Markdown và
full production/audit output lên cho tới khi có clearance bằng văn bản hoặc
license cho phép tái phân phối.
