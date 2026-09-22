# Chính sách alias Notes công ty chứng khoán

## Phạm vi

Profile "securities_v1" áp dụng riêng cho phần thuyết minh của công ty chứng
khoán. Catalog được đối chiếu với mẫu B01–B05 CTCK trong
[docs/template/BCTC-CK.pdf](template/BCTC-CK.pdf), đồng thời bao phủ hai
kiểu đánh số đã gặp trong dữ liệu thực tế:

- bộ thuyết minh BSI: các mục chính từ 5 đến 36;
- bộ thuyết minh CTS: các mục 3.x đến 12.

Một mã mục không được dùng một mình khi mã đó bị lặp ở nhiều nhóm. Parser ưu
tiên đồng thời mã mục và tiêu đề; tiêu đề có hậu tố "(tiếp theo)" được coi là
phần tiếp của cùng chủ đề. Nếu chỉ có mã mục nhưng có nhiều ứng viên, section
không được gán alias để tránh nhận nhầm.

## Chính sách dữ liệu

Alias chỉ bổ sung metadata schema_alias cho section, block và row. Nó không
đổi nhãn nguồn, không đổi thứ tự giá trị và không biến bảng nhiều cột thành
bảng hai kỳ.

- Dòng không khớp vẫn ở raw_tree cùng hierarchy, kỳ, giá trị và provenance.
- Bảng có nhiều cột vẫn ở raw_matrix, giữ header, ô trống, thứ tự cột và
  source_column.
- Các nhãn lặp như Tổng cộng, Số đầu năm hoặc tên loại chứng khoán chỉ được
  map khi xuất hiện duy nhất trong section; nếu lặp, chúng được giữ raw để
  tránh gán sai cha/con.

## Cách bật và rollback

Với sector securities, auto tự chọn securities_v1. Có thể bật rõ ràng bằng:

~~~powershell
python app/pipeline.py <report.md> --sector securities --notes --notes-parser-mode v2 --notes-alias-profile securities_v1
~~~

Rollback chỉ cần chạy lại với:

~~~powershell
--notes-alias-profile none
~~~

Khi rollback, parser vẫn đọc cùng Markdown và sinh cùng cây Notes; chỉ lớp
metadata alias được tắt. Profile không được dùng để sửa hoặc thay thế dữ liệu
của B01, B02, B03.

