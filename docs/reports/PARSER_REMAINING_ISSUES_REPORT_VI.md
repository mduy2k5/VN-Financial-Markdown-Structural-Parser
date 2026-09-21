# Báo cáo lỗi còn tồn đọng và nguyên nhân chính

**Ngày cập nhật:** 21/09/2026  
**Phạm vi:** batch 57 báo cáo trong md_reports, chạy bằng schema profile schema_v1_7  
**Mục đích:** phân biệt lỗi đã được xử lý với lỗi còn tồn đọng do nguồn dữ liệu, Markdown, schema hoặc parser.

## 1. Kết luận điều hành

Nguyên nhân chính của các trường hợp còn review_required hiện nay là **nguồn đầu vào Markdown không giữ đủ ngữ cảnh cấu trúc của báo cáo gốc**. Khi mất thông tin hàng, cột, mức thụt đầu dòng, quan hệ cha–con, phạm vi kỳ báo cáo hoặc ranh giới bảng, parser không còn đủ bằng chứng để xác định một giá trị thuộc dòng nào và kỳ nào.

Vì vậy, review_required không đồng nghĩa với parser đọc sai. Đây là trạng thái an toàn khi hệ thống thiếu bằng chứng hoặc gặp xung đột. Hệ thống giữ giá trị ở trạng thái chưa xác nhận thay vì tự gán sang một node khác và tạo ra kết quả nhìn có vẻ hợp lệ nhưng sai nghĩa.

Các lỗi schema đã được xác định ở BSI trong B01 và B03 đã được bổ sung bằng overlay có thể rollback. Phần còn lại chủ yếu là:

1. mất cấu trúc trong quá trình chuyển tài liệu gốc sang Markdown;
2. dữ liệu nguồn thiếu hoặc không đủ rõ để khôi phục quan hệ cha–con/kỳ báo cáo;
3. schema chưa thể bao phủ mọi biến thể theo tổ chức, ngành và mẫu biểu;
4. một số cảnh báo công thức và coverage cũ cần được xử lý riêng.

## 2. Những lỗi đã được xử lý

### 2.1. BSI B01 — thiếu các node con trong nhánh tài sản khác

Trước đây, một số dòng con trong nhánh tài sản khác không có node schema tương ứng. Parser có thể đọc được giá trị nhưng không thể gán đúng vào tên con vì schema chưa khai báo đủ cây cha–con.

Đã bổ sung các node có ngữ cảnh rõ ràng dưới nhánh tài sản khác, đồng thời bổ sung alias và parent context. Đây là lỗi schema, không phải bằng chứng cho thấy giá trị trong nguồn bị thiếu.

### 2.2. BSI B03 — dòng tiền cuối kỳ và dòng tiền cuối kỳ tiền mặt

Đã bổ sung cặp node:

- 103: dòng tiền cuối kỳ;
- 103.1: dòng tiền cuối kỳ tiền mặt.

Mapper hiện sử dụng form code rõ ràng để phân biệt các dòng cùng tên. Extractor cũng giữ riêng các dòng nhánh thập phân, không còn gộp 101.1 hoặc 103.1 vào dòng cha chỉ vì nhãn hiển thị giống nhau.

### 2.3. Khả năng rollback

Schema mới được nạp qua profile riêng, không ghi đè schema baseline. Có thể chạy lại bằng profile baseline nếu kết quả canary không cải thiện hoặc phát sinh xung đột:

    --schema-profile baseline

Profile triển khai hiện tại là schema_v1_7; profile baseline vẫn được giữ để so sánh và rollback.

### 2.4. Kết quả kiểm thử sau khi sửa

- 134 test pass;
- kiểm tra biên dịch flat_parser, src, app pass;
- batch 57/57 file chạy xong, không có runtime error;
- BSI B03 đạt 44/44 dòng theo schema mới;
- trong batch, 55 file có cash flow status ok, 1 file partial_source_coverage, 1 file no_structural_rows;
- 32 file đạt fingerprint ok, 25 file còn review_required.

Các kết quả trên chứng minh thay đổi schema không làm pipeline bị hỏng, nhưng chưa chứng minh mọi review_required đều đã được giải quyết vì một phần nguyên nhân nằm ngoài schema.

## 3. Các lỗi còn tồn đọng

### 3.1. Mất cấu trúc khi chuyển từ tài liệu gốc sang Markdown — nguyên nhân chính

Markdown hiện chỉ giữ phần chữ và số ở mức không ổn định. Trong một số file, các thông tin sau bị mất hoặc bị biến dạng:

- vị trí hàng và cột;
- mức thụt đầu dòng hoặc dấu hiệu thể hiện cấp cha–con;
- ranh giới giữa các bảng;
- tiêu đề kỳ hiện tại và kỳ trước;
- số trang, tọa độ vùng trên trang và thứ tự đọc;
- nhãn của dòng con;
- form code hoặc chỉ dấu biểu mẫu.

Khi các thông tin này mất, một đoạn Markdown có thể vẫn chứa đủ số và tên nhưng không còn cho biết chắc chắn số đó thuộc dòng cha, dòng con, cột hiện tại hay cột so sánh. Đây là lỗi của lớp ingestion/evidence, không thể khắc phục đáng tin cậy chỉ bằng cách thêm regex.

Trường hợp VCB đã được kiểm tra trực tiếp là ví dụ điển hình: bản gốc thể hiện một dòng tổng và hai dòng con, nhưng dữ liệu Markdown bị lệch/thiếu ngữ cảnh cột. Nếu parser tự đoán theo vị trí dòng, nó có thể gán nhầm số; vì vậy trường hợp này phải giữ cảnh báo thay vì coi là lỗi schema.

### 3.2. Dòng cha–con cùng tên hoặc thiếu nhãn con

Một số nguồn dùng cùng một nhãn cho dòng cha và dòng con, hoặc không đặt nhãn cho giá trị con. Khi không có thêm parent context, form code, indentation hoặc tọa độ bảng, tên nhãn đơn lẻ không đủ để chọn node.

Các trường hợp đã có bằng chứng form code hoặc cấu trúc rõ đã được xử lý bằng schema overlay. Các trường hợp chỉ có một nhãn giống nhau nhưng không có bằng chứng phân biệt vẫn chưa thể tự động map an toàn.

### 3.3. Phạm vi kỳ báo cáo chưa rõ

Một số bảng B02 hoặc bảng biến thể trình bày đồng thời số quý, lũy kế, năm trước hoặc số cuối kỳ nhưng Markdown không giữ được tiêu đề cột tương ứng. Parser có thể đọc đúng số nhưng không xác định chắc số đó thuộc kỳ nào.

Đây là lỗi thiếu metadata kỳ báo cáo. Bổ sung alias tên dòng không giải quyết được vấn đề này.

### 3.4. Dữ liệu nguồn thực sự thiếu hoặc không được công bố

Có các file không có bảng, không có dòng tương ứng, chỉ có dấu gạch ngang, hoặc chỉ công bố một trong các kỳ. Những trường hợp này không nên bị coi là parser bỏ sót.

Khi không có bằng chứng trong nguồn, hệ thống phải trả về source-only, partial_source_coverage hoặc review_required tùy mức độ, thay vì tự tạo giá trị hoặc suy ra dòng không được công bố.

### 3.5. Schema chưa bao phủ toàn bộ biến thể của các ngành

Schema overlay đã xử lý các nhánh có bằng chứng rõ trong BSI, nhưng không thể coi đó là bộ schema đầy đủ cho toàn bộ ngành. Một số node chỉ xuất hiện ở một tổ chức hoặc một mẫu báo cáo chưa có đủ bằng chứng để đưa vào schema chung.

Ví dụ, không nên tự thêm một node như 103.2 chỉ vì đoán rằng mọi báo cáo chứng khoán đều có cùng cấu trúc. Node mới chỉ nên được thêm khi có source evidence, form code hoặc quy tắc cấu trúc lặp lại được xác nhận.

Do đó, các dòng source-only còn lại phải được phân loại tiếp: nếu nguồn có cây cha–con rõ nhưng schema thiếu node thì đó là schema gap; nếu nguồn cũng mất cấu trúc thì đó là source/Markdown gap.

### 3.6. Cảnh báo công thức còn tồn đọng

Batch hiện còn 8 file với tổng cộng 11 kiểm tra công thức thất bại. So sánh focused giữa baseline và overlay cho thấy nhóm cảnh báo này không được tạo ra bởi schema overlay mới. Đây là nhóm vấn đề cần điều tra riêng theo nguồn dữ liệu, công thức báo cáo hoặc quy tắc kiểm tra; không nên gộp vào lỗi cây schema.

## 4. Nguyên nhân được xếp theo mức độ ảnh hưởng

### Nguyên nhân chính — mất ngữ cảnh cấu trúc ở lớp nguồn/Markdown

Đây là nguyên nhân lớn nhất vì nó làm mất chính bằng chứng cần thiết để phân biệt cột, kỳ, cấp cha–con và ranh giới bảng. Khi bằng chứng đã mất, parser tốt hơn cũng không thể khôi phục chắc chắn trong mọi trường hợp.

### Nguyên nhân thứ hai — schema coverage chưa đầy đủ

Một số dòng có thật trong nguồn nhưng chưa có node hoặc alias tương ứng. Đây là nguyên nhân có thể xử lý bằng cách mở rộng schema có kiểm soát. Các gap BSI đã được xử lý theo cách này.

### Nguyên nhân thứ ba — dữ liệu gốc thiếu hoặc mơ hồ

Nguồn có thể không công bố dòng, không có kỳ so sánh, chỉ có một cột, dùng dấu gạch ngang hoặc trình bày không nhất quán. Parser không nên biến thiếu dữ liệu thành một giá trị hợp lệ.

### Nguyên nhân thứ tư — lỗi biên parser lịch sử

Nhóm này gồm gộp nhầm các dòng nhãn giống nhau và không phân biệt được decimal branch. Các trường hợp đã có bằng chứng cụ thể ở BSI đã được sửa và có regression test. Chỉ nên mở lỗi parser mới khi chứng minh được source context đầy đủ nhưng output vẫn sai.

## 5. Ảnh hưởng đến kết quả

Các lỗi còn tồn đọng có thể làm:

- giảm tỷ lệ mapping hoặc coverage;
- tăng số file bị đánh dấu review_required;
- để lại một số dòng ở trạng thái source-only;
- làm các phép kiểm tra công thức không chạy được hoặc phát cảnh báo vì thiếu đầu vào;
- buộc người kiểm tra xác nhận thủ công các trường hợp thiếu bằng chứng.

Cơ chế hiện tại tạo ra nhiều cảnh báo hơn trong một số file, nhưng đây là trade-off cần thiết để tránh false positive: một giá trị bị bỏ lại để review an toàn hơn một giá trị được map sai sang node cha hoặc node con.

Không có bằng chứng cho thấy schema overlay đã làm hỏng toàn bộ pipeline. Ngược lại, BSI đạt đủ 44/44 dòng B03 sau overlay và toàn batch chạy không có runtime error. Tuy nhiên, không được suy ra rằng mọi review_required còn lại là lỗi parser; cần phân loại theo bằng chứng nguồn.

## 6. Giải pháp đề xuất để xử lý phần còn lại

### 6.1. Bổ sung evidence contract ở lớp ingestion

Mỗi dòng nguồn nên giữ sidecar metadata tối thiểu:

- số trang;
- mã bảng;
- số hàng và số cột;
- tọa độ bounding box;
- raw label và normalized label;
- mức thụt đầu dòng;
- parent hint;
- tiêu đề kỳ của từng cột;
- form code nếu có;
- liên kết về đoạn text hoặc ảnh nguồn.

Đây là giải pháp gốc cho lỗi hiện tại. Khi evidence còn đủ, parser mới có thể tách cha–con và xác định kỳ một cách có kiểm chứng.

### 6.2. Dùng exhaustive candidate search có điều kiện, không dùng đoán mù

Có thể vét cạn các bằng chứng về kỳ, nhãn, form code, vị trí và quan hệ cha–con để tạo danh sách ứng viên. Nhưng candidate chỉ được tự động chọn khi:

- chỉ còn một ứng viên có điểm tin cậy vượt ngưỡng;
- không có xung đột kỳ hoặc parent context;
- kiểm tra tổng/chi tiết và công thức liên quan không mâu thuẫn.

Nếu còn nhiều ứng viên, kết quả phải là review_required kèm evidence, không được ép map.

### 6.3. Mở rộng schema theo overlay có version

Mỗi schema addition cần có source evidence, test hồi quy, so sánh baseline và overlay, cùng điều kiện rollback. Không đưa các nhãn suy đoán hoặc fuzzy match rộng vào schema chung.

### 6.4. Tách ba nhóm chất lượng khi báo cáo

Báo cáo production nên tách riêng:

1. parser/schema error: nguồn đủ rõ nhưng output sai;
2. source/Markdown insufficiency: nguồn đầu vào không đủ cấu trúc;
3. formula/data quality warning: dữ liệu hoặc phép kiểm tra không đủ điều kiện.

Việc tách này giúp không quy toàn bộ tỷ lệ review_required thành lỗi parser.

## 7. Cơ chế triển khai và rollback

Trước khi promote schema overlay, chạy song song baseline và overlay trên cùng một batch, sau đó so sánh:

- mapping coverage;
- số conflict;
- số review_required;
- số source-only;
- kết quả công thức;
- các node mới được map.

Chỉ promote khi coverage tăng mà conflict và formula warning không tăng bất thường. Nếu không đạt, chạy lại profile baseline:

    python -m app.pipeline <input> --schema-profile baseline

Overlay không được sửa trực tiếp baseline nên việc rollback chỉ là đổi profile và chạy lại; output của lần chạy trước vẫn được giữ để đối chiếu.

## 8. Tài liệu và bằng chứng liên quan

- [Manifest batch schema v1.7](output/validation_schema_v17_batch_final/manifest.json)
- [Summary so sánh production](output/validation_schema_v17_batch_final/audit/comparison_summary.csv)
- [Bằng chứng BSI B03 sau overlay](output/validation_schema_v17_bsi_final/audit/BSI_BCTC_2025_hop_nhat_kiem_toan.cashflow.canonical.json)
- [Metadata lần chạy baseline để rollback](output/validation_schema_baseline_bsi_final/audit/run_metadata.json)
- [Báo cáo bằng chứng VCB, BSI, VIB](PARSER_EVIDENCE_VCB_BSI_VIB_VI.md)
- [Báo cáo ảnh hưởng của Markdown](MARKDOWN_IMPACT_REPORT_VI.md)

## 9. Kết luận cuối cùng

Tóm lại, lỗi còn tồn đọng hiện nay **chủ yếu do mất cấu trúc và ngữ cảnh trong dữ liệu Markdown đầu vào**, không phải do các lỗi schema BSI đã xác định trước đó. Schema coverage vẫn là nguyên nhân thứ cấp và sẽ tiếp tục xuất hiện ở các mẫu báo cáo mới, nhưng phải xử lý bằng evidence và overlay có kiểm soát. Dữ liệu gốc thiếu hoặc không rõ phải được giữ ở trạng thái review, không được suy đoán.

Để đưa hệ thống production ổn định, cần ưu tiên khôi phục evidence từ tài liệu gốc, giữ cơ chế review_required, mở rộng schema theo bằng chứng, và duy trì chạy canary cùng rollback về baseline.
