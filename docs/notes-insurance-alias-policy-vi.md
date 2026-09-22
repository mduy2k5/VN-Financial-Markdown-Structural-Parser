# Chính sách alias Notes công ty bảo hiểm

## Phạm vi

Profile `insurance_v1` áp dụng riêng cho phần thuyết minh của doanh nghiệp
bảo hiểm. Catalog được đối chiếu với hai mẫu:

- [BCTC-BHNT.pdf](template/BCTC-BHNT.pdf): bảo hiểm nhân thọ và tái bảo hiểm;
- [BCTC-BHPNT.pdf](template/BCTC-BHPNT.pdf): bảo hiểm phi nhân thọ và tái bảo hiểm.

Một báo cáo thực tế có thể hợp nhất cả hoạt động nhân thọ và phi nhân thọ.
Vì vậy profile dùng một catalog chung, trong đó các dòng như doanh thu phí,
hoa hồng, dự phòng nghiệp vụ và phải trả bảo hiểm vẫn giữ nhãn riêng cho hai
nhánh. Không tách hai nhánh thành hai parser độc lập vì chúng thường xuất hiện
chung trong cùng section và cùng ma trận kỳ.

Catalog cũng bao phủ một số nhóm chỉ tiêu có hình thức giống doanh nghiệp:
tài sản cố định, hàng tồn kho, thuế và thuế hoãn lại, vốn chủ sở hữu, hoạt
động tài chính, chi phí quản lý, lợi nhuận khác, bên liên quan, bộ phận, cam
kết và EPS. Đây là alias theo đúng mã mục và tiêu đề của Notes bảo hiểm, không
phải là dùng nguyên xi catalog doanh nghiệp.

## Chính sách dữ liệu

Alias chỉ bổ sung `schema_alias` cho section, block và row. Nó không đổi nhãn
nguồn, không đổi thứ tự giá trị, không loại bỏ dòng và không biến bảng nhiều
cột thành bảng hai kỳ.

- Dòng không khớp vẫn ở `raw_tree` cùng hierarchy, kỳ, giá trị và provenance.
- Bảng nhiều cột vẫn ở `raw_matrix`, giữ header, ô trống, thứ tự cột và
  `source_column`.
- Mã mục và tiêu đề phải cùng khớp. Một mã mục bị lặp nhưng khác tiêu đề sẽ
  không được gán nhầm alias.
- Các dòng nhân thọ và phi nhân thọ được gắn alias khác nhau trong cùng section;
  dữ liệu gốc vẫn là nguồn sự thật.

## Cách bật và rollback

Với sector `insurance`, `--notes-alias-profile auto` tự chọn `insurance_v1`.
Có thể bật rõ ràng bằng:

~~~powershell
python app/pipeline.py <report.md> --sector insurance --notes --notes-parser-mode v2 --notes-alias-profile insurance_v1
~~~

Rollback lớp alias bằng:

~~~powershell
--notes-alias-profile none
~~~

Khi rollback, parser vẫn đọc cùng Markdown và sinh cùng cây Notes; chỉ metadata
alias được tắt. Profile không sửa B01, B02 hoặc B03.
