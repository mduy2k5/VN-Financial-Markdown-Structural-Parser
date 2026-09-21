# Báo cáo hướng dẫn đọc toàn bộ dự án Flatten

## 1. Mục đích của báo cáo

Báo cáo này được viết để một người mới có thể đọc dự án từ đầu mà không phải
đoán ý nghĩa của các từ tiếng Anh trong tên file, tên hàm hoặc comment.

Mỗi phần trả lời bốn câu hỏi:

1. File này xuất hiện ở đâu trong luồng xử lý?
2. Hàm hoặc lớp trong file nhận dữ liệu gì?
3. Nó trả về hoặc thay đổi dữ liệu gì?
4. Vì sao dự án cần nó và bên trong nó làm những việc gì?

Tên hàm trong code được giữ nguyên để người đọc có thể tìm trực tiếp trong
trình soạn thảo. Phần giải thích bên dưới dùng tiếng Việt đời thường.

---
---

## 2. Bức tranh lớn của dự án

Dự án nhận các file báo cáo tài chính tiếng Việt đã được chuyển thành Markdown.
Một file báo cáo có thể chứa hàng nghìn dòng: thông tin công ty, ba báo cáo
chính và phần thuyết minh. Nhiệm vụ của chương trình là tìm đúng từng phần,
đọc các dòng số liệu của từng năm, rồi tạo ra JSON thống nhất.

Ba báo cáo chính là:

- B01: bảng cân đối kế toán, còn gọi là báo cáo tình hình tài chính.
- B02: báo cáo kết quả hoạt động kinh doanh.
- B03: báo cáo lưu chuyển tiền tệ.

Phần Notes là thuyết minh báo cáo tài chính. Notes được đọc thêm để cung cấp
chi tiết và liên kết với báo cáo chính, nhưng không được tự ý ghi đè số liệu
của B01, B02 hoặc B03.

### 2.1. Luồng xử lý một file

~~~text
File Markdown
    |
    v
app/pipeline.py::main
    |
    +--> chọn file cần chạy
    +--> đọc file và tính mã kiểm tra của file
    +--> tìm năm hiện tại, năm so sánh và đơn vị tiền
    +--> chạy B02
    |       +--> tìm vùng B02
    |       +--> tách các dòng
    |       +--> gán dòng vào trường chuẩn
    |       +--> kiểm tra và khôi phục dữ liệu thiếu
    |
    +--> chạy B03
    |       +--> tìm vùng B03
    |       +--> xác định loại ngành và phương pháp trực tiếp/gián tiếp
    |       +--> tách dòng
    |       +--> gán dòng vào trường chuẩn
    |
    +--> chạy B01
    |       +--> dựng cây cấu trúc từ các dòng Markdown
    |       +--> tìm giá trị trong từng nút
    |       +--> gán nút vào bảng chuẩn
    |       +--> kiểm tra tổng tài sản và nguồn vốn
    |
    +--> chạy Notes
    |       +--> tìm vùng thuyết minh
    |       +--> chia thành các đề mục và bảng
    |       +--> đọc dòng và liên kết với báo cáo chính
    |
    +--> đưa kết quả nội bộ về mẫu JSON dùng cho hệ thống khác
    +--> ghi report JSON và manifest.json
~~~

Thứ tự gọi trong process_one() là B02, B03, B01 rồi Notes. Đây là thứ tự được
cố ý chọn trong code, không phải thứ tự xuất hiện trên mọi báo cáo giấy.

### 2.2. Các lớp dữ liệu

Một dòng đi qua nhiều dạng dữ liệu:

~~~text
văn bản gốc
    -> dòng đã tách
    -> dòng có nhãn và giá trị
    -> dòng đã gán trường chuẩn
    -> bản ghi chuẩn nội bộ
    -> JSON production
~~~

Giải thích các từ thường gặp:

| Từ trong code | Nghĩa trong dự án |
|---|---|
| source | File Markdown gốc. |
| report | Toàn bộ báo cáo của một doanh nghiệp. |
| statement | Một phần báo cáo: B01, B02 hoặc B03. Không phải câu lệnh lập trình. |
| row | Một dòng dữ liệu được tách từ source. |
| field | Một trường dữ liệu, ví dụ doanh thu hoặc tiền mặt. |
| node | Một mục trong cây dữ liệu hoặc trong bảng chuẩn. |
| schema | Bản thiết kế cho biết các trường chuẩn được phép tồn tại. |
| alias | Một cách viết khác của cùng một trường chuẩn. |
| catalog | Bộ tra cứu được tạo từ schema và alias. Nó không phải cơ sở dữ liệu. |
| scope | Khoảng dòng bắt đầu và kết thúc của một báo cáo. |
| extract | Lấy nhãn, số, năm, đơn vị và mã ra khỏi dòng. |
| map | Gán dòng nguồn vào trường chuẩn. |
| canonical | Kết quả nội bộ đã được đưa về tên và cấu trúc chuẩn. |
| observation | Điều chương trình quan sát được từ source, kể cả khi chưa gán chắc chắn. |
| provenance | Dấu vết cho biết dữ liệu lấy từ file nào, dòng nào, bằng cách nào. |
| recovery | Đọc lại để khôi phục dòng hoặc giá trị bị tách/bỏ sót. |
| reconcile | Đối chiếu các kết quả và ghi lại điểm khác nhau. |
| audit | File chi tiết để con người kiểm tra, không phải output chính. |
| manifest | Danh sách ngắn gọn các report đã chạy. |
| fallback | Cách xử lý dự phòng khi cách chính không đủ bằng chứng. |
| evidence | Bằng chứng dùng để quyết định, ví dụ tiêu đề, số dòng, từ khóa. |
| candidate | Một khả năng đang được xem xét. |
| confidence | Mức tin cậy của một quyết định, thường nằm trong khoảng 0 đến 1. |
| coverage | Tỷ lệ dữ liệu đã nhận diện được. |
| unit | Đơn vị, ví dụ đồng, nghìn đồng, triệu đồng, tỷ đồng. |
| sector | Nhóm ngành: doanh nghiệp, ngân hàng, chứng khoán hoặc bảo hiểm. |

---

## 3. Các file cấu hình phải đọc trước code

### 3.1. Schema

Các file nằm trong resources/schemas/.

Ví dụ income_statement_schema.json có các trường:

~~~text
INCOME.ENTERPRISE.REVENUE_NET
INCOME.ENTERPRISE.COGS
INCOME.ENTERPRISE.GROSS_PROFIT
~~~

Mỗi trường thường có:

- mã định danh ổn định;
- tên tiếng Việt chuẩn;
- nhóm ngành được phép dùng;
- mã dòng trên biểu mẫu nếu có;
- công thức hoặc quan hệ với trường khác.

Schema trả lời câu hỏi: “Kết quả chuẩn phải có những mục nào?”.

### 3.2. Alias

Alias trả lời câu hỏi: “Trong file nguồn, cùng một mục có thể được viết như
thế nào?”.

Ví dụ một trường chuẩn có thể nhận các dòng:

~~~text
Doanh thu thuần
Doanh thu thuần về bán hàng và cung cấp dịch vụ
Doanh thu thuần bán hàng và cung cấp dịch vụ
~~~

B01 có alias kèm ngữ cảnh cha vì những nhãn như Nguyên giá có thể xuất hiện ở
nhiều nhóm tài sản khác nhau. B02 thường có nhóm exact cho nhãn chính xác. B03
có thể dùng dạng đơn giản node_id -> danh sách câu thay thế.

### 3.3. Guide

resources/guides/ mô tả các hình dạng thường gặp của dữ liệu Markdown:

- dòng bảng có dấu |;
- dòng bullet thụt vào;
- dòng tiêu đề rồi các dòng kỳ;
- giá trị nằm trước nhãn;
- hai cột năm bị tách thành hai khối;
- dòng tiếp nối từ trang khác.

Guide không chứa số liệu của doanh nghiệp. Nó chỉ nói cho parser biết cách đọc
những kiểu trình bày khác nhau.

---

## 4. Thứ tự đọc code đề xuất

Đọc theo một báo cáo đi qua hệ thống, không đọc tất cả file theo thứ tự tên:

1. app/pipeline.py::main() để biết chương trình bắt đầu ở đâu.
2. app/pipeline.py::process_one() để thấy một file đi qua những bước nào.
3. app/pipeline.py::run_income() và B02 để hiểu một đường đi đơn giản.
4. app/pipeline.py::run_cashflow() và B03 vì có thêm loại ngành/phương pháp.
5. src/b01_financial_position/extractor.py rồi flat_parser/pipeline.py vì B01 có cấu trúc phức tạp nhất.
6. src/notes/pipeline.py để hiểu phần thuyết minh bổ sung.
7. src/common/output_contract.py để biết kết quả cuối được đóng gói thế nào.
8. Các file phục hồi, đối chiếu và kiểm tra chất lượng.
9. Tests để xem từng quy tắc được bảo vệ bằng ví dụ nào.

---

## 5. File điều phối chính: app/pipeline.py

File này không tự phân tích sâu từng dòng tài chính. Nó giống người điều phối:
đọc source một lần, gọi đúng bộ xử lý, ghép kết quả và ghi file.

### 5.1. statement_locator(schema_path, aliases_path)

Đầu vào:

- schema_path: đường dẫn file mô tả các trường chuẩn.
- aliases_path: đường dẫn file chứa các cách viết thay thế.

Đầu ra:

- Một đối tượng StatementLocator đã đọc và lập bộ tra cứu.
- None nếu lớp StatementLocator không được import.

Cách hoạt động:

1. Kiểm tra lớp StatementLocator có được nạp thành công hay không.
2. Nếu không có, trả None để hàm gọi dùng cách tìm vùng dự phòng.
3. Nếu có, tạo StatementLocator từ hai file cấu hình.
4. @lru_cache(maxsize=3) giữ lại tối đa ba đối tượng theo cặp đường dẫn.
5. Gọi lại với cùng hai chuỗi đường dẫn sẽ lấy đúng đối tượng cũ.

Vì sao hàm xuất hiện? Việc đọc JSON alias và xây hàng trăm mục tra cứu tốn
thời gian. B02 và B03 xử lý nhiều file trong cùng một lần chạy, nên không cần
làm lại việc đó cho từng file.

Điểm cần nhớ: cache này chỉ giữ bộ định vị, không giữ kết quả của từng báo cáo.
Mỗi source vẫn được quét riêng.

### 5.2. attach_locator_metrics(metrics, scope)

Đầu vào:

- metrics: thống kê đã có của một báo cáo.
- scope: kết quả chọn vùng, có thể chứa thông tin locator.

Đầu ra:

Chính object metrics ban đầu, nhưng được bổ sung:

- locator có bật hay không;
- có được chấp nhận hay không;
- lý do chấp nhận/từ chối;
- mức tin cậy;
- số lần alias khớp;
- số dòng ứng viên.

Cách hoạt động:

Hàm không thay đổi số liệu canonical. Nó chỉ lấy thông tin chẩn đoán từ
scope["locator"] và đưa vào phần parser của metrics để sau này biết vì sao
parser chọn vùng đó.

### 5.3. write_json(path, obj)

Đầu vào:

- path: đường dẫn file sẽ ghi.
- obj: dữ liệu có thể chuyển thành JSON.

Đầu ra:

Không trả dữ liệu. Tác dụng chính là tạo file JSON trên đĩa.

Cách hoạt động:

1. Tạo thư mục cha nếu chưa có.
2. Chuyển object thành JSON.
3. Giữ tiếng Việt bằng ensure_ascii=False.
4. Thụt dòng hai khoảng để người đọc dễ mở.

### 5.4. attach_source_provenance(...)

Đầu vào:

- canonical: kết quả chuẩn nội bộ, có thể là None.
- tên file nguồn;
- mã SHA-256 của file;
- năm hiện tại và năm trước;
- thông tin cách suy luận năm.

Đầu ra:

Chính canonical sau khi có thêm tên file, mã file và thông tin kỳ. Nếu không có
canonical thì giữ None.

Cách hoạt động:

Hàm ghi thông tin nguồn vào hai nơi: các trường cấp cao và khối provenance.
Mục đích là khi thấy một giá trị sai, người kiểm tra biết nó đến từ file nào và
thuộc hai năm nào.

### 5.5. scan_statement_context(text)

Đầu vào:

- Toàn bộ nội dung Markdown.

Đầu ra:

- Một dictionary mô tả vùng B01/B02/B03/Notes và ngành được nhận diện.
- None nếu bộ quét không sẵn sàng hoặc gặp lỗi.

Cách hoạt động:

1. Chuẩn hóa các dòng.
2. Loại dòng nhiễu.
3. Gọi scan_statements.
4. Nếu có lỗi, nuốt lỗi và trả None để Notes tự tìm vùng bằng cách khác.

Hàm này được gọi trước Notes để Notes có thêm thông tin về các vùng báo cáo
chính. Nó không tạo Notes IR và không đọc output cũ.

### 5.6. remove_report_artifacts(output_dir, base)

Đầu vào:

- thư mục output hoặc audit;
- tên gốc của report.

Đầu ra:

Không trả dữ liệu.

Cách hoạt động:

Chỉ xóa đúng các file tạm đã biết của report đang chạy lại, chẳng hạn file
canonical, comparison và Notes rows. Hàm không xóa cả thư mục và không đụng
đến source.

Vì sao cần? Nếu lần chạy trước có dữ liệu nhưng lần chạy mới không tạo lại
được, file cũ không được phép nằm lại và làm người dùng tưởng đó là kết quả mới.

### 5.7. prune_stale_report_artifacts(output_dir, active_bases)

Đầu vào:

- thư mục audit;
- tập tên report thực sự còn trong batch hiện tại.

Đầu ra:

Không trả dữ liệu.

Cách hoạt động:

Duyệt các file audit có hậu tố đã biết, chỉ giữ file có tên nằm trong tập report
đang chạy. Các file của report đã bị bỏ khỏi input sẽ được xóa.

### 5.8. clear_legacy_output(output_dir)

Xóa các file output phẳng của phiên bản cũ, ví dụ summary cũ hoặc Notes rows
cũ nằm cạnh manifest.json. Output mới chỉ nên có manifest.json, thư mục
reports/ và, khi bật, thư mục audit/.

### 5.9. prune_stale_production_reports(reports_dir, active_report_filenames)

Giữ lại đúng các report JSON của batch hiện tại trong reports/. Nó ngăn một
report của lần chạy cũ xuất hiện như thể vẫn thuộc batch mới.

### 5.10. ensure_output_is_outside_input(input_path, output_dir)

Đầu vào:

- thư mục/file input;
- thư mục output.

Đầu ra:

Không trả dữ liệu; ném lỗi nếu output nằm bên trong cây input.

Vì sao cần? Nếu output được ghi bên trong thư mục Markdown, lần chạy sau có thể
đọc nhầm file sinh ra như một file input. Hàm chặn lỗi này trước khi tạo output.

### 5.11. stem_base(path)

Lấy tên gốc của file và loại các hậu tố thể hiện biến thể, ví dụ bản kiểm toán
hoặc bản hợp nhất. Kết quả được dùng để gom các file cùng một báo cáo.

### 5.12. select_md_files(input_path)

Đầu vào:

- một file Markdown hoặc một thư mục.

Đầu ra:

- danh sách file Markdown được chọn.

Cách hoạt động:

1. Kiểm tra input tồn tại.
2. Nếu là file, kiểm tra phần mở rộng.
3. Nếu là thư mục, tìm Markdown ở cấp trên cùng.
4. Nếu không thấy, tìm đệ quy bên dưới.
5. Gom các tên gốc trùng nhau.
6. Chọn một bản đại diện cho mỗi report.

### 5.13. run_income(...)

Đây là cửa vào xử lý B02.

Đầu vào:

- đường dẫn Markdown;
- năm hiện tại và năm trước;
- ngành được ép nếu người dùng truyền vào;
- đơn vị tiền làm giá trị dự phòng.

Đầu ra:

Dictionary gồm canonical, metrics, rows, scope và sector.

Cách hoạt động:

1. Đọc text.
2. Tìm hai năm.
3. Lấy locator B02 từ cache.
4. Locator đề xuất vùng B02.
5. extract_income_fallback đọc nhiều kiểu trình bày.
6. adapt_row đổi dictionary thô thành IncomeRow.
7. Chọn ngành hoặc dùng ngành được ép từ CLI.
8. Nếu không có dòng, trả trạng thái chẩn đoán và không tạo canonical rỗng.
9. Tạo IncomeMapper từ schema và alias.
10. Map từng row.
11. Dùng source recovery để tìm thêm dòng bị bỏ sót.
12. Đối chiếu observation.
13. Tạo metrics.

Locator chỉ giúp thu hẹp vùng. Extractor vẫn chịu trách nhiệm đọc dòng; mapper
mới chịu trách nhiệm gán trường.

### 5.14. run_cashflow(...)

Đây là cửa vào xử lý B03.

Đầu vào:

- đường dẫn Markdown;
- hai năm;
- đơn vị tiền dự phòng.

Đầu ra:

Dictionary gồm canonical, metrics, rows, scope, sector và method.

Cách hoạt động:

1. Đọc source và xác định năm.
2. Lấy locator B03.
3. Extractor tìm vùng lưu chuyển tiền tệ.
4. Xác định ngành và phương pháp trực tiếp/gián tiếp.
5. Nếu chưa biết phương pháp nhưng các dòng đã có, thử suy luận lại từ nhãn.
6. Nếu ngành hoặc phương pháp chưa được hỗ trợ an toàn, giữ row để review,
   không ép vào schema sai.
7. Tạo CashFlowMapper.
8. Map row.
9. Khôi phục dòng generic và bảng mã-kỳ nếu có.
10. Giữ riêng bảng bổ sung của công ty chứng khoán.
11. Đối chiếu observation và tạo metrics.

Mã biểu mẫu chỉ là bằng chứng phụ. Nhãn và ngữ cảnh section mới là căn cứ chính
để tránh map nhầm hai dòng có cùng mã.

### 5.15. process_one(...)

Đây là hàm quan trọng nhất để hiểu toàn bộ một report.

Đầu vào:

- một file Markdown;
- thư mục audit tùy chọn;
- năm hiện tại/năm trước;
- ngành được truyền từ CLI;
- parser B01 dùng lại;
- cờ bật/tắt Notes;
- thông tin suy luận năm.

Đầu ra:

Dictionary tóm tắt report và chứa thêm production JSON.

Cách hoạt động:

1. Đọc source một lần.
2. Tính SHA-256 từ bytes của file.
3. Tìm đơn vị chung của tài liệu.
4. Xóa artifact cũ của report nếu bật audit.
5. Gọi run_income.
6. Gọi run_cashflow.
7. Gắn nguồn và kỳ cho B02/B03.
8. Tạo hoặc dùng lại FinancialPositionSourceParser.
9. Chạy B01.
10. Chọn đơn vị chung cho ba báo cáo.
11. Ghi canonical audit nếu được yêu cầu.
12. Tạo primary_for_notes từ ba báo cáo chính.
13. Chạy Notes với source và primary.
14. Xuất Notes rows nếu có.
15. Gọi clean_statement cho B01/B02/B03.
16. Gọi clean_notes cho Notes.
17. Gọi build_production_report.
18. Nếu bật audit, ghi comparison và canonical chi tiết.
19. Trả summary cùng production JSON.

Điểm bảo vệ quan trọng: Notes nhận kết quả báo cáo chính để liên kết, nhưng
không trở thành nguồn chính thay cho B01/B02/B03.

### 5.16. main()

Đầu vào là các tham số dòng lệnh: input, output, năm, ngành, Notes và audit.

Đầu ra là reports/*.json, manifest.json và audit files nếu được bật.

Cách hoạt động:

1. Đọc tham số.
2. Chọn Markdown.
3. Kiểm tra output nằm ngoài input.
4. Dọn output cũ đúng phạm vi.
5. Tạo parser B01 dùng chung cho cả batch.
6. Với từng file, suy luận năm và gọi process_one.
7. Ghi production JSON theo tên chứa tên file và một phần SHA-256.
8. Xóa report production không còn active.
9. Tạo manifest.
10. Nếu có lỗi xử lý file, in lỗi và kết thúc với mã lỗi.

---

## 6. B02: báo cáo kết quả kinh doanh

### 6.1. src/b02_income/scope.py

File này tìm vùng B02 trước khi extractor đọc chi tiết.

| Hàm | Đầu vào | Đầu ra | Công dụng |
|---|---|---|---|
| strip_md | một giá trị bất kỳ | chuỗi sạch | Bỏ dấu Markdown và khoảng trắng. |
| clean_value | ô văn bản | số/chuỗi đã làm sạch hoặc None | Loại các ô không phải dữ liệu. |
| _period_role_and_priority | nhãn kỳ, hai năm | vai trò và điểm ưu tiên | Phân biệt năm hiện tại, năm trước, lũy kế. |
| parse_period_line | một dòng, hai năm | các giá trị kỳ | Đọc dòng chứa ngày/năm và số. |
| _candidate_score | danh sách dòng, vị trí, hai năm | điểm số | Chấm điểm một tiêu đề B02. |
| _heading_candidates | các dòng, hai năm | danh sách ứng viên | Tìm các dòng có dáng tiêu đề. |
| _scope_end_for_candidate | các dòng, vị trí bắt đầu | vị trí kết thúc | Dừng trước báo cáo kế tiếp hoặc giới hạn tối đa. |
| _find_notes_start | các dòng | vị trí Notes | Không cho B02 ăn sang phần thuyết minh. |
| _candidate_viability | vùng ứng viên và context | thông tin khả dụng | Kiểm tra vùng có dòng dữ liệu thật hay chỉ là mục lục. |
| choose_income_scope | toàn bộ text và năm | dòng, start, end, score | Chọn vùng B02 tốt nhất. |

### 6.2. src/b02_income/extractor.py

File này phải chịu được nhiều kiểu Markdown khác nhau. Một số file có bảng
đúng chuẩn; một số file bị chuyển thành bullet hoặc các cột bị tách rời.

#### Chuẩn hóa và đọc một dòng

- fold: bỏ dấu, đổi chữ thường và gom khoảng trắng để so sánh.
- _is_cumulative_period_label: nhận diện nhãn lũy kế để không nhầm thành năm so sánh.
- _primary_period_priority: chọn giá trị ưu tiên khi một dòng có nhiều kỳ.
- is_non_item_header_or_noise: loại dòng tiêu đề, đơn vị, mã số và nhiễu.
- _bullet_info: lấy độ thụt, dấu bullet và phần nội dung.
- _strip_leading_index: bỏ số thứ tự đầu dòng.
- _row: tạo dictionary row chuẩn từ nhãn, hai giá trị và metadata.

#### Đọc từng kiểu trình bày

- extract_pipe_table: đọc bảng Markdown có dấu |.
- _parse_descendants: đọc các dòng con thụt vào dưới một dòng cha.
- extract_period_children: đọc các dòng con đại diện cho hai kỳ.
- extract_positional_children: đọc giá trị con dựa vào vị trí.
- extract_inline_period_rows: đọc dòng có nhãn và hai kỳ trên cùng dòng.
- extract_heading_attribute_rows: đọc tiêu đề có thuộc tính kỳ/đơn vị.
- extract_plain_text_code_rows: đọc văn bản thường có mã dòng.
- _plain_label_before_code: lấy nhãn đứng trước mã.
- _plain_next_label_code: lấy nhãn và mã ở các dòng kế tiếp.
- _interleaved_pair_layout: nhận diện hai giá trị hiện tại/trước đây bị xen kẽ.
- extract_interleaved_formula_pairs: phục hồi cặp giá trị dựa trên công thức.
- _collect_vector_labels: lấy danh sách nhãn trong bố cục cột dọc.
- _infer_vector_gap: đo một khoảng thiếu trong vector giá trị.
- extract_vector_column_major: xử lý bố cục nhãn một khối, số một khối khác.
- extract_column_major: gom các cách đọc cột tách rời.
- extract_code_led_mixed_rows: xử lý layout bắt đầu bằng mã dòng.
- extract_year_section_rows: xử lý mỗi năm nằm trong một section riêng.
- extract_label_list_column_major: xử lý danh sách nhãn và khối số tách nhau.

#### Gom và chọn kết quả

- _norm_dedupe_label: chuẩn hóa nhãn để khử trùng lặp.
- dedupe: nếu nhiều collector đọc cùng một dòng, giữ bản có bằng chứng tốt hơn.
- _extract_rows_for_scope: gọi toàn bộ collector, ghép row và khử trùng lặp.
- extract_income_fallback: cửa vào chính cho B02; chọn scope, chạy collector,
  đo đơn vị và trả rows.
- augment_income_rows: chạy thêm một lượt đọc dự phòng rồi ghép với rows có sẵn.

### 6.3. src/b02_income/mapper.py

#### Các hàm chuẩn hóa

- _find_root: tìm thư mục dự án để xác định vị trí resources.
- strip_md: bỏ ký hiệu Markdown.
- strip_mapping_qualifiers: bỏ phần chỉ dùng để diễn giải mapping.
- fold: chuẩn hóa nhãn để so sánh.
- semantic_label_similarity: tính mức giống nhau về nội dung của hai nhãn.
- clean_source_label_and_code: tách nhãn nghiệp vụ khỏi mã và tham chiếu.
- parse_number: đổi chuỗi số tiếng Việt thành số Python.
- _first: lấy giá trị đầu tiên trong một nhóm tên khóa.
- _source_raw_text: tìm lại câu nguồn để lưu dấu vết.
- _year_from_period: lấy năm từ thông tin kỳ.
- _role_from_period: đổi kỳ thành current hoặc previous.
- _extract_period_payload: lấy các cặp kỳ-giá trị từ nhiều dạng dictionary.

#### IncomeRow

IncomeRow là object đại diện cho một dòng B02 sau khi extractor đã đọc. Nó giữ
nhãn nguồn, hai giá trị, mã, ghi chú, vị trí dòng, đơn vị, pattern và trạng thái.

- adapt_row: đổi dictionary thô thành IncomeRow.
- _looks_like_row: kiểm tra object có đủ dấu hiệu là một dòng hay không.
- discover_rows: đi qua object lồng nhau để tìm tất cả row.
- dedupe_rows: giữ row tốt nhất trong các row trùng.

#### IncomeMapper

- __init__: đọc schema/alias, lọc node theo ngành và lập bảng tra cứu nhãn.
- map_row: thử nhãn chính xác, ngữ cảnh cha, biểu thức dự phòng và so sánh
  từng từ; chỉ nhận kết quả đủ điểm và không mơ hồ.
- map_rows: gọi map_row cho toàn bộ danh sách.
- canonical: nhóm row theo node, điền hai kỳ, lưu occurrence, conflict và công thức.

#### Các hàm tiện ích cuối file

- detect_special_sector: phát hiện ngành đặc biệt từ các row.
- auto_sector: chạy mapper thử theo từng ngành và chọn ngành phù hợp.
- infer_years: tìm hai năm từ object dữ liệu.
- load_rows: đọc JSON row rồi chuyển thành IncomeRow.
- save_debug_rows: ghi row trung gian để điều tra.

### 6.4. src/b02_income/validator.py

- fold: chuẩn hóa nhãn.
- _label_implies_income: xem nhãn có mang nghĩa thu nhập không.
- _label_implies_expense: xem nhãn có mang nghĩa chi phí không.
- normalize_bank_semantic_signs: chuẩn hóa dấu của dòng ngân hàng.
- normalize_enterprise_formula_signs: chuẩn hóa dấu theo công thức doanh nghiệp.
- normalize_securities_semantic_signs: chuẩn hóa dấu dòng chứng khoán.
- validate_securities_formulas: kiểm tra công thức của chứng khoán.
- validate_insurance_formulas: kiểm tra công thức của bảo hiểm.
- validate_enterprise_formulas: kiểm tra công thức doanh nghiệp.
- summarize_formula_checks: đếm số công thức đạt, hỏng hoặc bị bỏ qua.
- validate_bank_formulas: kiểm tra công thức ngân hàng.

Validator không đọc lại Markdown. Nó kiểm tra kết quả mapper đã tạo.

---

## 7. B03: báo cáo lưu chuyển tiền tệ

B03 khó hơn B02 ở chỗ cùng một dòng tiền có thể được trình bày theo phương
pháp trực tiếp hoặc gián tiếp. Ngoài ra một báo cáo có thể được xuất theo bố
cục bảng ngang, bảng dọc, hoặc bị tách thành các khối cột do chuyển từ PDF
sang Markdown.

### 7.1. src/b03_cashflow/extractor.py

File extractor nhận văn bản B03 và tạo các dòng quan sát. Nó chưa quyết định
hoàn toàn dòng đó thuộc trường chuẩn nào; việc đó thuộc về mapper.

#### CashFlowObservation và các hàm dữ liệu cơ bản

- CashFlowObservation: cấu trúc trung gian chứa nhãn, giá trị kỳ hiện tại và
  kỳ trước, nhóm dòng, phương pháp, mã dòng, ghi chú, số dòng nguồn, mẫu bố
  cục và văn bản gốc.
- __post_init__: làm sạch các giá trị sau khi object được tạo.
- to_dict: chuyển observation thành dictionary để ghi JSON hoặc truyền sang
  bước sau.
- strip_md: bỏ ký hiệu Markdown khỏi chuỗi.
- fold: chuẩn hóa chữ hoa, khoảng trắng và dấu để so sánh nhãn.
- parse_number: đổi chuỗi số Việt Nam thành số; xử lý dấu âm, dấu phân cách
  hàng nghìn và dấu thập phân.
- _line_indent: đo mức thụt đầu dòng, dùng để nhận ra quan hệ cha-con.
- _clean_bullet: bỏ dấu bullet và số thứ tự đầu dòng.
- _split_statement_code_prefix: tách mã biểu mẫu khỏi phần nhãn.
- _looks_metadata_line: nhận ra dòng chỉ có thông tin phụ, không phải dòng số
  liệu.
- _has_inline_metadata_reference: nhận ra mã tham chiếu hoặc chú thích nằm
  ngay trong nhãn.
- _section_from_label: suy ra nhóm hoạt động từ nhãn, ví dụ hoạt động kinh
  doanh, đầu tư hoặc tài chính.
- _candidate_scope: tính đoạn có thể là B03 bắt đầu từ một dòng ứng viên đến
  trước ứng viên tiếp theo.
- _is_valid_heading_candidate: lọc các tiêu đề giống tiêu đề B03 thật.
- choose_cashflow_scope: chọn vùng B03 có bằng chứng tốt nhất trong toàn bộ
  file. Kết quả gồm số dòng bắt đầu, kết thúc và lý do chọn.
- detect_method: đọc tiêu đề và nhãn để xác định direct hoặc indirect, tức
  phương pháp trực tiếp hoặc gián tiếp. Nếu không đủ bằng chứng, trả trạng
  thái unknown thay vì tự đoán chắc chắn.
- detect_sector: đoán nhóm ngành của báo cáo từ nhãn và mã biểu mẫu.
- _extract_inline_periods: lấy các cặp kỳ-giá trị nằm trên cùng một dòng.
- _join_raw_text: ghép các mảnh văn bản nhưng tránh tạo khoảng trắng thừa.
- _emit: tạo một CashFlowObservation với metadata đầy đủ rồi thêm vào danh
  sách kết quả.

#### Các hàm đọc những hình dạng bảng khác nhau

- _major_column_token: nhận diện token chỉ dẫn cột lớn, chẳng hạn nhãn kỳ.
- _short_statement_token: xác định token ngắn có thể là mã hoặc nhãn bị
  xuống dòng.
- _column_label_line: làm sạch dòng nhãn trong bảng cột.
- _is_column_section_heading: nhận diện tiêu đề của một nhóm cột.
- _looks_wrapped_column_label: kiểm tra nhãn có bị bọc thành hai dòng không.
- _is_report_noise_label: loại nhãn là số trang, tiêu đề lặp hoặc rác OCR.
- _pipe_cells: tách các ô của dòng bảng dùng dấu |.
- _period_header_columns: đọc hàng tiêu đề để biết cột nào là năm nào.
- _find_section_anchor: tìm dòng bắt đầu của một nhóm hoạt động.
- _collect_column_label_slots: thu thập vị trí các nhãn trước khi đọc giá trị
  ở những dòng sau.
- _extract_detached_period_table_rows: đọc bảng trong đó nhãn và giá trị kỳ
  bị tách khỏi nhau.
- _extract_column_major_cashflow_rows: đọc bố cục column-major, nghĩa là
  nhiều nhãn đi trước rồi các giá trị của từng kỳ xuất hiện thành khối cột.
- _period_value_line: nhận diện dòng có kỳ và giá trị.
- _next_value_before_label: khi PDF đảo thứ tự, tìm giá trị đứng trước nhãn
  tương ứng.
- _extract_value_before_label_rows: khôi phục các dòng có dạng giá trị trước,
  nhãn sau.

#### extract_cashflow_fallback

Đầu vào là:

- markdown_text: toàn bộ nội dung Markdown.
- current_year, previous_year: hai năm cần đọc.
- locator_result: vùng B03 do StatementLocator đề xuất, nếu có.
- statement_unit: đơn vị tiền đã nhận diện.
- các tham số sector, method hoặc options khác nếu caller truyền vào.

Đầu ra là dictionary chứa rows, scope, method, sector, unit, locator và
metadata phục vụ audit.

Cách hoạt động:

1. Chọn vùng từ locator; nếu locator không đủ tin cậy thì gọi cách chọn vùng
   dự phòng.
2. Đọc cả bố cục bảng ngang, dòng kỳ-giá trị, dòng giá trị-trước-nhãn và các
   dòng có mã biểu mẫu.
3. Giữ lại section, method, code, note, raw_text và line_no để mapper và
   audit còn biết dữ liệu đến từ đâu.
4. Dùng emit để tạo observation đồng nhất.
5. Loại dòng trùng nhưng ưu tiên dòng có giá trị, mã và vị trí nguồn tốt hơn.
6. Trả kết quả ngay cả khi một số dòng chưa map được; dòng chưa map vẫn là
   bằng chứng để báo cáo chất lượng.

Bên trong hàm có các hàm cục bộ emit và flush_pending. emit tạo observation
như hàm _emit. flush_pending hoàn tất một nhãn đang chờ khi gặp giá trị hoặc
nhãn tiếp theo. Hai hàm này cần thiết vì dữ liệu chuyển đổi từ PDF thường
không nằm trọn trên một dòng.

### 7.2. src/b03_cashflow/mapper.py

#### CFRow và hàm chuyển đổi

- _find_root: tìm thư mục gốc để các đường dẫn resources hoạt động dù chạy
  từ thư mục nào.
- strip_md: bỏ Markdown trong nhãn.
- clean_trailing_parens: loại phần ngoặc cuối nếu đó chỉ là mã hoặc ghi chú
  không dùng để định danh trường.
- fold: chuẩn hóa nhãn.
- _form_code_key: chuẩn hóa mã biểu mẫu để so sánh.
- semantic_label_similarity: tính mức giống nhau giữa nhãn nguồn và nhãn
  chuẩn.
- CFRow: bản ghi B03 trung gian có nhãn, hai giá trị, mã, phương pháp, nhóm,
  ghi chú và metadata nguồn.
- __post_init__: làm sạch dữ liệu trong CFRow.
- adapt_cashflow_row: chuyển dictionary hoặc observation từ extractor thành
  CFRow.

#### CashFlowMapper

- __init__: đọc cashflow schema và alias catalog, lọc node đúng sector và
  method, lập chỉ mục node_id, form_code và các nhãn thay thế.
- _compatible: kiểm tra một node có dùng được cho dòng B03 hiện tại không,
  nhất là điều kiện ngành và phương pháp.
- map_one: gán một CFRow vào node. Thứ tự là nhãn chính xác, mã biểu mẫu
  như tín hiệu phụ, so sánh gần đúng và so sánh ngữ nghĩa. Mã không được tự
  quyết định khi còn nhiều node cùng mã.
- map_rows: gọi map_one cho toàn bộ dòng.
- canonical: gom các dòng đã map theo node, điền giá trị kỳ hiện tại và kỳ
  trước, lưu occurrence, conflict, section, method, source và đơn vị.
- _formula_checks: kiểm tra các tổng và quan hệ cơ bản của B03, trả danh sách
  kết quả để quality gate và audit sử dụng.

### 7.3. Quan hệ giữa method, sector và mapping

method là cách lập báo cáo lưu chuyển tiền tệ, không phải một trường tài
chính. sector là nhóm ngành. Hai thông tin này được dùng để thu hẹp catalog:

~~~text
source
  -> detect_method + detect_sector
  -> chỉ cho phép các node phù hợp
  -> map_one
  -> canonical B03
~~~

Nếu detect_method trả unknown, run_cashflow có thể dùng quy tắc khôi phục từ
nhãn và bố cục. Nếu sau đó vẫn không xác định được hoặc không có node hợp lệ,
chương trình không bịa canonical; nó giữ observations và ghi lý do trong
metrics.

---

## 8. B01: bảng cân đối kế toán

B01 được xử lý bởi flat_parser vì đây là phần có nhiều quan hệ cây nhất. Ví dụ
nhãn Nguyên giá chỉ có ý nghĩa khi biết nó nằm dưới Tài sản cố định hay một
nhóm khác. Vì vậy B01 không thể chỉ tìm một chuỗi rồi gán ngay.

### 8.1. src/b01_financial_position/extractor.py

- _attach_source_provenance: thêm file nguồn, số dòng, vùng statement và cách
  phát hiện vào canonical.
- _set_statement_unit: gắn đơn vị tiền vào tất cả phần phù hợp của canonical.
- summarize_canonical: tạo tóm tắt số trường, số dòng map được, số xung đột
  và các kiểm tra tổng.
- FinancialPositionSourceParser.__init__: nạp FlatParserPipeline một lần
  với schema, alias, guide và các tùy chọn B01.
- FinancialPositionSourceParser.parse_text: nhận Markdown, gọi pipeline để
  dựng cây và map trường, sau đó thêm provenance, unit và summary.

parse_text trả về kết quả B01 nội bộ gồm canonical, nodes, observations,
context, metrics, scope và các lỗi hoặc cảnh báo. Nó không trực tiếp ghi file.

### 8.2. flat_parser/models.py

Đây là các kiểu dữ liệu dùng xuyên suốt B01:

- SourceLine: một dòng nguồn có số dòng, văn bản nguyên bản và văn bản đã
  chuẩn hóa.
- TableContext: vị trí và hình dạng của một bảng.
- PrimitiveValue: một số đã tách khỏi văn bản, giữ raw text, numeric value và
  vị trí.
- PrimitivePeriod: một kỳ báo cáo như năm 2025 hoặc 2024.
- StructuralNode: một nút trong cây cấu trúc. Nó giữ parent, children,
  indentation, bảng, nhãn và các giá trị cục bộ.
- CanonicalNodeSpec: mô tả một node chuẩn lấy từ schema.
- AliasCandidate: một khả năng ghép nhãn nguồn vào node chuẩn, kèm điểm và
  bằng chứng.
- FieldObservation: quan sát của một trường trước khi quyết định cuối.
- ResolvedValue: giá trị đã chọn cho một kỳ.
- ResolvedField: trường đã ghép với một hoặc nhiều giá trị.
- StatementContext: ngữ cảnh chung gồm vùng B01, năm, đơn vị và ngành.
- jsonable: đổi các dataclass, Decimal và kiểu đặc biệt thành dữ liệu JSON.

Các class trên là dữ liệu, không tự đọc file. Cách tách dữ liệu khỏi thuật
toán giúp từng bước có thể giữ lại bằng chứng để điều tra lỗi.

### 8.3. Chuẩn hóa và tiền xử lý

File flat_parser/textnorm.py:

- fold: chuyển chữ về dạng so sánh ổn định, thường bỏ khác biệt hoa thường,
  dấu và khoảng trắng.
- strip_inline_markdown: bỏ ký hiệu Markdown nhưng giữ nội dung.
- strip_numbering: bỏ số thứ tự hoặc bullet đầu dòng.
- normalize_lines: chia raw text thành SourceLine, đánh số dòng và giữ cả
  raw_text lẫn normalized text.
- strip_inline_financial_metadata: bỏ metadata tài chính nằm kèm nhãn.
- strip_financial_prefix: bỏ tiền tố mã hoặc số thứ tự trước nhãn.

File flat_parser/preprocess.py:

- is_noise_line: xác định dòng chỉ là số trang, đường kẻ hoặc rác.
- split_pipe_cells: chia dòng bảng theo dấu | mà không làm hỏng ô rỗng.
- is_table_separator: nhận diện dòng --- của Markdown table.
- filter_noise: loại dòng rác trước khi dựng cấu trúc.

File flat_parser/tables.py:

- detect_tables: tìm đoạn bảng và trả cả danh sách TableContext lẫn bản đồ
  line_no -> TableContext để các bước sau tra nhanh.

### 8.4. Guide và classifier

File flat_parser/guide.py:

- UniversalGuide.__init__: đọc một hoặc nhiều guide JSON/YAML và tạo bộ quy
  tắc trình bày.
- UniversalGuide._compile_regexes: biên dịch các mẫu văn bản thành regex để
  nhận diện nhanh.

Guide là “sổ tay hình dạng”, không phải catalog trường. Catalog trả lời nhãn
nào tương ứng node nào; guide trả lời dòng được trình bày như thế nào.

File flat_parser/structural_classifier.py:

- StructuralClassifier.__init__: nhận UniversalGuide.
- classify_all: phân loại toàn bộ node.
- _set: gán loại node, điểm và bằng chứng.
- _classify_local: nhìn chính node để phân biệt heading, label, value,
  period, wrapper hoặc noise.
- _upgrade_parent_pattern: dùng mẫu của node cha để nâng độ tin cậy của node.
- _inherit_context: truyền ngữ cảnh cha xuống node con khi bản thân node con
  quá ngắn.

File flat_parser/document.py:

- _parse_code_note_period_inline_row: đọc dòng chứa mã, chú thích, kỳ và giá
  trị cùng lúc.
- raw, is_code, looks_financial: các hàm cục bộ hỗ trợ nhận diện token trong
  dòng dạng đặc biệt.
- _split_top_level_colon: tách dấu : ở cấp ngoài, không tách dấu : nằm trong
  ngoặc hoặc nội dung con.
- _table_label_and_metadata: lấy nhãn và metadata khỏi một ô bảng.
- hfold, clean_cell: hàm cục bộ chuẩn hóa nhãn và ô.
- build_nodes: biến SourceLine thành cây StructuralNode, nhận biết quan hệ
  cha-con bằng heading, indentation, table và thứ tự dòng.
- descendants: lấy các node con trong giới hạn độ sâu.
- ancestors: lấy các node cha của một node.
- hydrate_keyed_record_wrappers: đưa giá trị từ wrapper dạng key-value vào
  node thực tế.
- hydrate_column_major_statement_blocks: ghép các block nhãn và block giá trị
  khi bảng bị chuyển thành bố cục theo cột.

File flat_parser/primitives.py:

- extract_unit: tìm đơn vị tiền từ tiêu đề hoặc dòng chú thích.
- _normalize_number: chuyển một token số thành Decimal, xử lý ngoặc âm và dấu
  phân cách.
- _mask_spans: che những đoạn đã nhận diện để lần quét kế tiếp không bắt lại.
- extract_periods: tìm năm hoặc kỳ báo cáo trong một dòng.
- whole_text_period: nhận cả dòng là một kỳ nếu không có cấu trúc phức tạp.
- extract_values: tìm các số và trả PrimitiveValue.
- explicit_note: lấy mã chú thích như Note 4 hoặc Thuyết minh 12.

### 8.5. Tìm vùng B01 và định danh statement

File flat_parser/statement_scanner.py:

- StatementCandidate: một tiêu đề có thể là B01, B02 hoặc B03.
- StatementRange: vùng đã chọn, có start/end, loại statement, điểm và lý do.
- StatementRange.as_dict: đổi kết quả thành JSON.
- detect_document_sector: đoán ngành toàn tài liệu.
- add: hàm cục bộ cộng điểm và ghi lý do bằng chứng.
- _nearby: lấy các dòng gần một vị trí.
- _title_type: phân loại tiêu đề.
- _toc_penalty: trừ điểm nếu tiêu đề nằm trong mục lục.
- _numeric_shape_score: đo xem sau tiêu đề có hình dạng số liệu không.
- _anchor_score: đếm các từ neo của statement.
- _form_code_hint: lấy gợi ý ngành từ mã biểu mẫu.
- _looks_like_toc_entry: nhận diện dòng mục lục.
- _looks_like_statement_reference_entry: nhận diện dòng chỉ tham chiếu đến
  statement ở phần khác.
- _score_title_candidate: tính điểm cho một tiêu đề ứng viên.
- _off_balance_fallback: tạo vùng dự phòng khi B01 không có tiêu đề chuẩn.
- scan_statements: trả các vùng ứng viên và vùng được chọn.

File flat_parser/context.py:

- HeadingCandidate: cấu trúc ứng viên tiêu đề có điểm và evidence.
- _nearby, _contains_any, _statement_heading_text, _is_heading_like,
  _semantic_root_text: nhóm hàm làm sạch và nhận diện heading.
- _score_fp_candidate: chấm điểm ứng viên B01.
- _next_fp_heading_line: tìm heading B01 tiếp theo để giới hạn vùng.
- _financial_payload_evidence: kiểm tra phía sau heading có số liệu tài chính.
- _candidate_with_payload: bổ sung điểm payload vào candidate.
- _signature_score_window: chấm một cửa sổ dòng theo chữ ký B01.
- find_financial_position_signature_start: tìm vị trí bắt đầu dựa trên nhiều
  nhãn chữ ký.
- _is_statement_title_shape: kiểm tra hình dạng tiêu đề.
- find_validated_financial_position_start: chọn start sau khi kiểm tra payload.
- _validated_stop: kiểm tra dòng có phải điểm kết thúc hợp lệ.
- find_validated_financial_position_end: chọn end.
- financial_position_scope: trả vùng B01 đã xác nhận.
- _reporting_year_from_heading_neighborhood: lấy năm quanh tiêu đề.
- _column_period_labels: đọc nhãn kỳ của các cột.
- detect_context: ghép scope, năm, đơn vị, ngành và các gợi ý ngữ cảnh.

### 8.6. SemanticCatalog và alias

File flat_parser/semantic_catalog.py:

- SemanticCatalog.__init__: đọc schema và alias JSON, kiểm tra hai file có
  cùng node_id, rồi tạo CanonicalNodeSpec cho từng node.
- clone_schema: sao chép schema để bước xử lý có thể làm việc trên bản riêng.
- ancestor_ids: lấy danh sách node cha của một node.

Ở đây catalog nghĩa là “bộ danh mục tra cứu”. Nó gồm hai nguồn:

~~~text
schema  -> node nào tồn tại, tên chuẩn, cha, ngành, form code
aliases -> nhãn nguồn nào có thể chỉ vào node đó
catalog -> cấu trúc tra cứu đã nạp vào bộ nhớ
~~~

Vì vậy catalog không phải file báo cáo, không phải database và không phải
cache. Nó là dữ liệu cấu hình được đọc vào để thuật toán tra cứu.

File flat_parser/alias_matcher.py:

- normalize_label: chuẩn hóa nhãn trước khi so sánh.
- _base_match: thử exact, contains và fuzzy match cơ bản.
- _nearest_semantic_ancestor_texts: lấy nhãn các node cha gần nhất để dùng
  làm ngữ cảnh.
- _source_context_score: chấm điểm khi nhãn nguồn và ngữ cảnh cha khớp.
- match_candidates: trả nhiều AliasCandidate thay vì chọn sớm một node.
- choose_candidate: chọn ứng viên tốt nhất nếu chênh lệch đủ an toàn; nếu mơ
  hồ thì giữ trạng thái chưa quyết định.

File flat_parser/regex_matcher.py:

- _phrase_regex: tạo regex an toàn cho một cụm nhãn.
- _matches_phrase: kiểm tra một cụm có xuất hiện đúng ranh giới hay không.
- _sector_allowed: kiểm tra node có thuộc ngành đang đọc không.
- regex_match_candidates: tạo ứng viên từ regex alias và sector.

File flat_parser/mapping_strategy.py:

- _regex_fallback_candidates: dùng regex khi exact alias không đủ.
- match_candidates_for_strategy: chọn chiến lược match theo loại node,
  ngữ cảnh và chất lượng nhãn.

### 8.7. Thu thập, giải quyết và tạo canonical

File flat_parser/collector.py:

- _period_value_pairs: ghép danh sách kỳ với danh sách giá trị.
- _parse_pipe_inline: lấy dữ liệu từ một dòng bảng có nhãn và số.
- _bounded_descendants: lấy con trong phạm vi để tránh nuốt sang statement
  kế bên.
- _sequential_local_attributes: đọc các thuộc tính xuất hiện nối tiếp sau
  một nhãn.
- _recover_detached_total_payload: khôi phục giá trị tổng bị rời khỏi node.
- is_noise: hàm cục bộ lọc node nhiễu.
- collect_observation: tạo FieldObservation từ StructuralNode và các ứng
  viên alias.

File flat_parser/resolver.py:

- _period_key: chuyển PrimitivePeriod thành khóa current hoặc previous.
- _financial_unit: chọn đơn vị ưu tiên từ value, observation hoặc context.
- resolve_observation: từ nhiều candidate và primitive value tạo ResolvedField,
  giữ điểm, kỳ, đơn vị và evidence.

File flat_parser/consolidator.py:

- _compatible_occurrences: kiểm tra hai occurrence có thể thuộc cùng trường
  hay là hai trường khác nhau.
- consolidate_resolved_fields: gom các ResolvedField tương thích, xử lý
  trùng và conflict.

File flat_parser/canonical_mapper.py:

- _value_signature: tạo chữ ký để nhận biết cùng một giá trị bị đọc hai lần.
- map_first_value_per_period: map mỗi node thành giá trị đầu tiên hợp lệ cho
  từng kỳ, nhưng vẫn giữ occurrence để audit.

File flat_parser/dual_role.py:

- _has_local_total_payload: kiểm tra node có giá trị tổng ngay tại node.
- expand_dual_role_rows: xử lý node vừa là heading vừa có giá trị riêng; không
  được bỏ giá trị local chỉ vì node có con.

File flat_parser/validator.py:

- _num: chuyển giá trị canonical thành số kiểm tra được.
- _value: lấy giá trị của node theo kỳ.
- validate_financial_position: kiểm tra các tổng B01 như tổng tài sản và tổng
  nguồn vốn; trả checks thay vì tự sửa số liệu.
- explicit_total: hàm cục bộ lấy tổng được báo cáo rõ trong canonical.

File flat_parser/qa.py:

- _clean_financial_label: làm sạch nhãn phục vụ QA.
- detect_sector: phát hiện ngành từ các node hoặc nhãn.
- _node_has_local_payload: kiểm tra node có số tại chỗ hay chỉ là wrapper.
- _looks_like_inline_serialized_row: nhận dạng một dòng đã bị nối thành chuỗi.
- classify_unknown_financial_label: gán loại lý do cho nhãn chưa map.
- analyze_semantic_coverage: tính coverage của quá trình map và phân loại
  unresolved.
- detect_explicit_totals: tìm các tổng có ghi rõ trong source.
- canonical_completeness: đo mức đủ của canonical so với tổng và trường quan
  trọng.

File flat_parser/source_context.py:

- _label: lấy nhãn sạch của StructuralNode.
- source_context_for_node: tạo dictionary ngữ cảnh cha, heading, section, line
  và table để provenance giải thích vì sao node được map.

### 8.8. FlatParserPipeline và thứ tự xử lý B01

FlatParserPipeline.__init__ nạp SemanticCatalog, UniversalGuide,
StructuralClassifier và StatementLocator.

_accept_locator_scope nhận vùng do locator đề xuất và kiểm tra lại bằng
financial_position_scope. Đây là safety gate: locator nhanh nhưng không được
phép kéo vùng sai vào parser cấu trúc.

parse_text thực hiện các pass sau:

1. normalize_lines và filter_noise.
2. locate statement và tạo baseline B01.
3. kiểm tra vùng bằng _accept_locator_scope.
4. detect_context và detect_tables.
5. build_nodes, hydrate wrapper và hydrate column-major.
6. classify_all.
7. detect sector.
8. pass 1 chọn các anchor có cấu trúc chắc.
9. pass 2 collect observation và resolve value.
10. classify các node còn lại, consolidate occurrence và xử lý dual role.
11. map_first_value_per_period.
12. validate_financial_position và tạo metrics.

Các hàm cục bộ như _has_financial_payload_descendant dùng để kiểm tra một
heading có con mang số liệu hay không. Nó giúp parser không coi tiêu đề rỗng
hoặc mục lục là B01.

parse_file đọc file UTF-8 rồi gọi parse_text. Nó là cửa vào dùng khi caller
muốn xử lý đường dẫn thay vì chuỗi văn bản.

---

## 9. StatementLocator và các phần còn lại của flat_parser

### 9.1. flat_parser/statement_locator.py

StatementLocator là bộ định vị vùng statement. Statement ở đây nghĩa là một
phần báo cáo tài chính, không phải câu lệnh trong ngôn ngữ lập trình. Locator
chỉ tìm đoạn dòng có khả năng là B01, B02 hoặc B03; nó không quyết định ý
nghĩa cuối cùng của từng giá trị.

Các cấu trúc dữ liệu:

- StatementProfile: tên statement, mẫu tiêu đề, từ neo và mẫu kết thúc.
- AliasEntry: nhãn tra cứu gồm node_id, alias, dạng khớp và độ đặc hiệu.
- AliasHit: alias xuất hiện tại dòng/trang nào và có payload số hay không.
- CandidateRow: dòng có thể là một row trong vùng ứng viên.
- ScopeCandidate: vùng ứng viên cùng score, confidence, evidence, số node,
  số dòng số, số kỳ và ranh giới.
- as_dict: các phương thức chuyển cấu trúc trên thành dictionary cho metrics
  và audit.

Các hàm ngoài class:

- _clean_for_match: chuẩn hóa text để tìm alias.
- _numeric_payload: chỉ kiểm tra dòng có hình dạng số liệu; không parse số.
- _is_period_signal: nhận diện năm hoặc kỳ.
- _is_noise_line: loại dòng rác.
- _toc_line_numbers: tìm các dòng mục lục để không dùng tiêu đề lặp làm vùng
  thật.
- _profile_for: kiểm tra profile và trả StatementProfile.
- _schema_names: đọc tên chuẩn theo node_id.
- _alias_entries: đọc nhiều dạng alias của B01, B02 và B03 thành AliasEntry.
- locator_for_profile: kiểm tra profile và tạo locator, chưa quét source.

StatementLocator.__init__ nhận schema_path, aliases_path và các ngưỡng. Nó đọc
catalog một lần, tạo self.entries và chưa tìm vùng cho đến khi locate được gọi.

Các phương thức:

- _hits: quét dòng, bỏ mục lục/rác và tạo AliasHit.
- _primary_lines: bỏ phần Notes khi tìm B01/B02/B03 vì Notes lặp lại nhãn.
- _title, _stop: nhận diện tiêu đề và điểm kết thúc.
- _candidate_starts: ưu tiên tiêu đề; chỉ dùng cụm alias khi thiếu tiêu đề.
- _end_for: tìm điểm dừng trước statement tiếp theo.
- _score: cộng bằng chứng tiêu đề, alias, node, số dòng, kỳ và bảng.
- evaluate_scope: so sánh vùng locator với baseline của parser cấu trúc; nếu
  không đủ chồng lấn hoặc confidence thì giữ baseline.
- locate: chuẩn hóa source, tìm hit, tạo/chấm ứng viên và trả scope được chọn,
  candidates, candidate_rows, fallback cùng metrics.

Locator là router, không phải semantic mapper. Semantic nghĩa là gán ý nghĩa
nghiệp vụ cho nhãn; locator chỉ tìm vùng để mapper đọc đúng đoạn.

---
 
### 9.2. Cache instance trong app/pipeline.py

Cache instance nghĩa là giữ lại chính object StatementLocator đã khởi tạo,
không phải chỉ giữ một dictionary kết quả. Khóa cache là cặp:

~~~text
(schema_path, aliases_path)
~~~

Gọi hai lần trong cùng process với cùng hai chuỗi sẽ trả cùng object. maxsize=3
giữ tối đa ba cặp đường dẫn; cặp ít dùng có thể bị loại khi có cặp mới.

Cache này chỉ sống trong một process, không ghi xuống đĩa, không cache kết quả
locate của source và không làm mất line_no/raw_text của source. Nếu file alias
đổi trong lúc process còn chạy, object cũ vẫn được dùng cho đến khi cache bị
xóa hoặc process kết thúc. B02 và B03 gọi helper này trực tiếp. B01 dùng một
FinancialPositionSourceParser tạo trong main và tái sử dụng pipeline của nó,
nhưng không đi qua helper cache này.

### 9.3. Các module hỗ trợ

flat_parser/guide_compiler.py:

- _append_unique: thêm phần tử nếu chưa có.
- _merge_field_patterns: gộp quy tắc field từ hai guide.
- compile_guides: đọc các guide nguồn và tạo guide hợp nhất.
- write_compiled_guide: ghi guide đã biên dịch.

flat_parser/coverage_reporter.py:

- _dump_json: ghi JSON.
- _review_priority: xếp ưu tiên xem xét dựa trên metrics.
- build_coverage_report: gom coverage của nhiều report.

Các module models, textnorm, preprocess, primitives, tables, document,
context, statement_scanner, alias_matcher, resolver, consolidator,
canonical_mapper, dual_role, validator và qa tạo chuỗi:

~~~text
text -> SourceLine -> StructuralNode -> PrimitiveValue/PrimitivePeriod
     -> AliasCandidate -> FieldObservation -> ResolvedField
     -> canonical -> validation/metrics
~~~


## 10. Các module dùng chung trong src/common
 
common là phần dùng lại bởi B01, B02, B03, Notes và output. Đọc các file này
sau khi hiểu một statement, vì chúng giải quyết các vấn đề cắt ngang nhiều
statement.
 
### 10.1. Đơn vị và giá trị: value_semantics.py
 
- UnitContext: object giữ tên đơn vị chuẩn, hệ số quy đổi, nguồn phát hiện và
  confidence.
- clean_text: làm sạch text.
- fold_text: chuẩn hóa text để so sánh.
- is_note_reference: phân biệt số chú thích với số liệu.
- detect_unit: tìm đơn vị trong một đoạn text và trả UnitContext.
- detect_document_unit: tìm đơn vị ưu tiên trong toàn tài liệu.
- detect_statement_unit: tìm đơn vị trong riêng một statement, có fallback.
- row_unit_override: cho phép một dòng có đơn vị riêng ghi đè đơn vị thừa kế.
- arithmetic_value: chuyển số về kiểu dùng được cho phép tính.
- units_compatible: kiểm tra các đơn vị có thể so sánh hay không.
 
Đơn vị không chỉ là chuỗi “triệu đồng”. Nó quyết định số 1 trong source được
hiểu là 1 đồng, 1 nghìn đồng hay 1 triệu đồng. Vì vậy parser giữ unit trong
canonical và provenance.
 
### 10.2. Năm và kỳ: report_period.py, period_resolver.py
 
report_period.py:
 
- _fold: chuẩn hóa text năm và ngày.
- _score_text_years: chấm điểm các năm xuất hiện trong text.
- _safe_date: tạo date an toàn.
- _date_from_match: đổi regex match thành date.
- _date_candidates: thu thập các ngày có thể là ngày báo cáo.
- _best_date: chọn ngày có bằng chứng tốt nhất.
- _date_year_back: tính ngày lùi một năm.
- _period_type: nhận biết năm, quý, kỳ hoặc ngày.
- infer_report_period_context: tạo ngữ cảnh kỳ từ text.
- _infer_year_pair_by_scores: chọn current_year và previous_year bằng điểm.
- infer_report_year_pair: suy ra hai năm từ toàn file.
- resolve_report_years: ghép năm tường minh, năm suy ra và default; trả cặp
  năm cuối cùng cùng lý do.
 
period_resolver.py:
 
- period_role_for_date: đổi một ngày thành current hoặc previous theo cặp năm.
 
current_year là năm báo cáo hiện tại; previous_year là năm so sánh. Đây là vai
trò của kỳ, không đơn giản là lấy hai số lớn nhất trong tài liệu, vì mục lục,
ngày ký và ngày thành lập cũng có thể chứa số năm.
 
### 10.3. Khôi phục từ source: source_recovery.py
 
source_recovery đọc lại chính Markdown để cứu dữ liệu bị extractor chính bỏ
sót. Nó không đọc output cũ và không lấy ground truth làm dữ liệu đầu vào.
 
- clean, fold: chuẩn hóa nhãn.
- _structural_context_key: tạo khóa ngữ cảnh cha.
- parse_number: đọc số.
- RecoveredRow: dòng được khôi phục, gồm label, hai kỳ, code, note, section,
  line_no, pattern và raw text.
- RecoveredRow.__post_init__: làm sạch row.
- _is_fp_heading_line, _is_next_statement_line: tìm ranh giới B01.
- choose_financial_position_scope: chọn vùng B01 để recovery.
- _explicit_fp_period_value: đọc cặp kỳ-giá trị rõ ràng.
- _inline_end_begin_values: đọc kiểu đầu kỳ/cuối kỳ.
- _inline_year_values: đọc hai năm trên cùng dòng.
- _inline_row_label: lấy nhãn inline.
- _normalize_row_label: chuẩn hóa nhãn.
- _split_code_label: tách mã và nhãn.
- _extract_trailing_form_code: lấy mã nằm cuối nhãn.
- _extract_suffix_meta: lấy metadata cuối dòng.
- _valid_label: loại nhãn không hợp lệ.
- _is_period_value_line: kiểm tra dòng kỳ-giá trị.
- _markdown_indent_and_label: lấy mức thụt và nhãn.
- _hierarchy_context: dựng ngữ cảnh cha trong vùng.
- _extract_explicit_inline_year_pair: đọc cặp năm inline.
- _looks_like_form_code_token, _looks_like_note_token: nhận dạng mã và note.
- _positional_numeric_children: ghép các số con theo vị trí khi nhãn và số
  tách thành dòng.
- _period_header_role: xác định vai trò kỳ của header.
- _is_period_column_year_header: kiểm tra header cột năm.
- previous_nonempty, next_nonempty: hàm cục bộ tìm dòng lân cận.
- _inline_form_code_child_rows: khôi phục row con có mã.
- _cashflow_section_by_line: gán section B03 theo dòng.
- extract_generic_statement_rows: khôi phục row dùng chung cho statement.
- _split_page_blocks: tách các block theo trang.
- _cross_page_fp_rows: ghép row B01 vắt qua trang.
- extract_financial_position_source_rows: cửa vào recovery B01.
- _is_securities_customer_cashflow_heading, _is_next_securities_statement:
  tìm vùng phụ của B03 chứng khoán.
- extract_securities_supplemental_cashflow_rows: khôi phục dòng tiền bổ sung
  đặc thù chứng khoán.
 
Recovery được dùng sau extractor chính vì nó rộng và dễ tạo ứng viên thừa.
Các row khôi phục đi qua hydrate, reconcile và quality check trước khi được
đưa vào output.
 
### 10.4. Hydration và observation
 
source_canonical_hydrator.py:
 
- _normalized_value_key, _values_equal: so sánh số sau khi chuẩn hóa.
- _context_label_key: tạo khóa ngữ cảnh.
- _source_id: tạo định danh occurrence từ source.
- extract_code_period_table: đọc bảng mã-dòng-kỳ để làm bằng chứng.
- _form_code_key: chuẩn hóa mã biểu mẫu.
- hydrate_canonical_by_form_code: bổ sung giá trị vào canonical khi mã và kỳ
  khớp đủ an toàn.
- augment_canonical_with_recovered_rows: thêm row recovery nếu section,
  source identity và context phù hợp.
- section_matches, source_identity_matches, _node_context_keys,
  _node_source_labels: các hàm cục bộ kiểm tra tương thích.
- _find_representation_equivalent: tìm node đã đại diện cho cùng một row dưới
  tên trình bày khác.
- _record_representation_equivalent: ghi bằng chứng tương đương thay vì tạo
  node trùng.
 
source_observation.py:
 
- _clean, _fold, _number: làm sạch dữ liệu.
- _row_raw_text: chọn raw text tốt nhất.
- _source_id: tạo id ổn định cho dòng nguồn.
- _existing_labels: lấy các nhãn đã có.
- augment_from_rows: thêm các row chưa có vào canonical dưới dạng source
  observations.
 
Observation là bằng chứng nguồn chưa chắc chắn. Việc giữ observation giúp
người kiểm tra thấy parser đã đọc gì, ngay cả khi semantic mapping chưa đủ
an toàn.
 
### 10.5. Đối chiếu: source_reconciler.py
 
- _value_key: chuẩn hóa giá trị để so sánh.
- _source_line: lấy số dòng.
- _group_id: nhóm node theo statement, section, label và context.
- _period_votes: đếm phiếu của các occurrence cho một kỳ.
- _resolve_period: chọn giá trị kỳ từ các phiếu.
- _preferred_node: chọn node ưu tiên theo độ tin cậy, nguồn và metadata.
- score: hàm cục bộ chấm một node.
- _semantic_candidates: tìm các node semantic cùng nhóm.
- _node_occurrences: lấy occurrence của node.
- _record_value, _record_label: lấy giá trị và nhãn của occurrence.
- _period_values_match: kiểm tra source và semantic có cùng giá trị theo kỳ.
- _context_matches: kiểm tra cùng context.
- _link_source_observations: liên kết observation nguồn với node semantic.
- reconcile_source_observations: chạy đối chiếu cho một canonical và ghi
  links, conflicts, resolution và lý do.
 
reconcile không sửa mù giá trị. Nó tạo quyết định có bằng chứng để output và
audit có thể giải thích.
 
### 10.6. Metrics và output: pipeline_metrics.py, output_contract.py
 
pipeline_metrics.py:
 
- _scope_text: cắt source theo scope.
- detect_sector_from_scope: phát hiện ngành bằng scope và rows.
- _is_source_observation_node: phân biệt node semantic với observation.
- _value_nodes: chia node có giá trị và node không có giá trị.
- build_metrics: tạo metrics B01 hoặc B02 gồm coverage, unresolved, mapping,
  duplicates, quality và provenance.
- build_cashflow_metrics: tạo metrics B03, thêm method và confidence của
  method.
 
output_contract.py:
 
- stable_report_id: tạo id ổn định từ SHA256 source.
- report_filename: tạo tên file output an toàn.
- _json_value, _number, _nullable: chuẩn hóa kiểu JSON.
- _value: đóng gói một giá trị theo kỳ.
- _evidence: lọc evidence công khai.
- _mapping: đóng gói thông tin map.
- _attributes: đóng gói thuộc tính bổ sung.
- _record: tạo bản ghi chuẩn cho một node.
- _statement_summary: tạo summary một statement.
- _quality_gate: quyết định cờ chất lượng dựa trên metrics và checks.
- clean_statement: làm sạch canonical statement thành contract ổn định.
- _native_row: chuyển một row Notes nội bộ thành row output.
- _note_value: làm sạch giá trị Notes.
- _note_section: làm sạch section Notes.
- _note_row: làm sạch một row Notes.
- clean_notes: biến Note IR và rows thành cấu trúc Notes output.
- build_periods: tạo danh sách kỳ với current/previous.
- build_production_report: ghép metadata, B01, B02, B03, Notes và quality
  thành report JSON chính.
- manifest_entry: rút một report thành dòng ngắn trong manifest.
 
output contract là “hợp đồng đầu ra”: tên field, kiểu dữ liệu và quan hệ mà
consumer bên ngoài có thể tin cậy. Vì vậy raw debug và audit không trộn vào
production report nếu không được contract cho phép.
 
### 10.7. Các module dùng chung còn lại
 
structural_identity.py:
 
- clean_identity_text, normalize_identity_label: chuẩn hóa nhãn để tạo identity.
- structural_identity: tạo định danh dựa trên statement, section, context,
  label và code.
- occurrence_rank: xếp hạng các lần xuất hiện của cùng một identity.
 
error_taxonomy.py:
 
- _fold, _field, _is_structural_noise, _looks_column_collapsed: nhận diện
  dạng lỗi của row chưa map.
- classify_unmapped_row: phân loại row thành structural noise, collapsed
  column, ambiguous, missing payload hoặc nguyên nhân khác.
- build_error_taxonomy: gom toàn bộ row lỗi thành thống kê.
- empty_error_taxonomy: tạo cấu trúc rỗng ban đầu.
 
ground_truth_quality.py dùng khi đánh giá dữ liệu chuẩn:
 
- fold_text, normalize_label, parse_number: chuẩn hóa.
- infer_year_pair cùng explicit_period_pair, is_metadata_label,
  add_period_years và visit_statement: suy ra cặp năm bằng evidence.
- period_role: đổi kỳ thành current/previous.
- observation_period: lấy kỳ của observation.
- period_evidence_conflict: phát hiện evidence kỳ mâu thuẫn.
- is_placeholder_label: nhận diện nhãn giả.
- source_period_hint: lấy gợi ý kỳ từ source.
- extract_inline_period_values và parse_inline_number: đọc cặp giá trị inline.
- ObservationDecision: kết quả đánh giá một observation.
- assess_observation: quyết định observation có đủ chất lượng.
- evidence_key: tạo khóa để so sánh evidence.
- iter_observations: duyệt mọi observation trong statement.
 
ground_truth ở đây là dữ liệu chuẩn dùng để đánh giá, không phải nguồn được
đọc trong pipeline production.
---
 
## 11. Notes: phần thuyết minh báo cáo tài chính
 
Notes là phần thuyết minh. Nó không phải một statement chính độc lập kiểu B01,
B02 hoặc B03; nó giải thích chi tiết cho các khoản mục, ví dụ chi tiết tài sản
cố định, hàng tồn kho, vay, doanh thu hoặc biến động đầu kỳ/cuối kỳ.
 
Trong code, Notes có một IR riêng. IR là intermediate representation, nghĩa là
“cấu trúc trung gian”: dữ liệu đã được đọc thành object có nghĩa nhưng chưa
đóng gói vào JSON production cuối cùng.
 
### 11.1. notes/note_ir.py
 
- NoteValue: một giá trị trong Notes, có số, kỳ, đơn vị, vai trò và raw text.
- NoteValue.to_dict: chuyển NoteValue thành dictionary.
- NoteRow: một dòng thuyết minh có label, các NoteValue, dimensions, line và
  raw text.
- NoteRow.to_dict: chuyển row thành dictionary.
- NoteBlock: một bảng hoặc block trong một note section.
- NoteBlock.to_dict: chuyển block thành dictionary.
- NoteLink: liên kết một row/block Notes với node của B01, B02 hoặc B03.
- NoteLink.to_dict: chuyển liên kết thành dictionary.
- ReconciliationResult: kết quả đối chiếu số liệu Notes với statement chính.
- ReconciliationResult.to_dict: chuyển kết quả đối chiếu thành dictionary.
- NoteSection: đề mục thuyết minh, có note_id, title, page, topic và blocks.
- NoteSection.ref: tạo mã tham chiếu ổn định cho section.
- NoteSection.to_dict: chuyển section thành dictionary.
- NoteDocument: tài liệu Notes gồm sections, links, reconciliations, scope,
  unit, sector và diagnostics.
- NoteDocument.to_dict: chuyển toàn bộ IR thành dictionary.
 
Các class này chủ yếu giữ dữ liệu và provenance. Chúng không tự quyết định
một số liệu Notes có đúng hay không.
 
### 11.2. Quét vùng Notes: notes/scanner.py
 
- NotesScope: start, end, confidence và evidence của vùng Notes.
- NotesScope.to_dict: chuyển scope thành dictionary.
- _TitleCandidate: một dòng có thể là tiêu đề Notes.
- _fold: chuẩn hóa text.
- _strip_inline_markdown: bỏ ký hiệu Markdown.
- _normalized_title_line: làm sạch một dòng tiêu đề.
- _is_notes_title: nhận diện “Thuyết minh báo cáo tài chính” hoặc biến thể.
- _is_notes_continuation: nhận diện tiêu đề Notes bị xuống dòng.
- _is_primary_title: nhận diện tiêu đề B01/B02/B03 để biết Notes đã kết thúc.
- _next_nonblank, _prev_nonblank: tìm dòng không rỗng gần vị trí.
- _near_toc: kiểm tra ứng viên có nằm gần mục lục không.
- _statement_list_reference: nhận diện dòng chỉ liệt kê tên statement.
- _numbered_toc_reference: nhận diện dòng mục lục đánh số.
- _looks_like_toc_candidate: trả cờ mục lục và lý do.
- _frontmatter_notes_ranges: tìm các đoạn Notes bị lặp ở phần đầu tài liệu.
- _title_candidates: thu thập các tiêu đề ứng viên.
- _scanner_notes_start: lấy start từ kết quả scanner cũ nếu có.
- detect_notes_scope: chọn vùng Notes thật, tránh mục lục và đoạn tham chiếu.
- primary_heading_decoys_in_scope: tìm tiêu đề B01/B02/B03 giả nằm trong Notes.
- explain_notes_scope_candidates: trả toàn bộ ứng viên và lý do để debug.
 
Đầu vào chính là toàn bộ text. Đầu ra là NotesScope, không phải các row.
 
### 11.3. Chia section: notes/sectionizer.py
 
- fold_text: chuẩn hóa tiêu đề.
- _strip_md: bỏ Markdown.
- normalize_note_id: đưa “4”, “4.1” hoặc “Note 4” về dạng id ổn định.
- _page_map: map số dòng sang số trang nếu source có marker trang.
- _candidate_from_line: tạo ứng viên section từ một dòng.
- sectionize_notes: cắt NotesScope thành danh sách NoteSection.
 
Một section là vùng có tiêu đề và nội dung của một note. Sectionizer chưa đọc
chi tiết từng số; nó chỉ xác định ranh giới để parser bảng và parser bullet làm
việc trong đúng note.
 
### 11.4. Đọc bảng và bullet
 
notes/table_parser.py:
 
- split_pipe_cells: tách các ô bảng Markdown.
- is_separator_row: nhận diện dòng phân cách.
- _strip_md: làm sạch ô.
- parse_number: đọc số trong ô.
- _row_role: phân biệt dòng tiêu đề, tổng, chi tiết hoặc ghi chú.
- _infer_period_role: đổi header thành current/previous.
- _infer_measure: nhận diện measure như cost, depreciation, closing hoặc amount.
- _is_data_row: kiểm tra dòng có payload hay chỉ là header.
- _compose_headers: ghép header nhiều dòng thành tên cột.
- parse_markdown_tables: đọc các bảng trong section và trả NoteBlock/NoteRow.
 
notes/structural_parser.py:
 
- _strip_md: bỏ Markdown.
- _indent_width: đo thụt đầu dòng.
- _split_numeric_unit: tách số và đơn vị.
- _period_role: nhận vai trò kỳ.
- _row_role: phân biệt heading, total, detail hoặc metadata.
- parse_bullet_structures: đọc Notes dạng bullet hoặc key-value thay vì bảng.
 
Các parser này có thể được gọi cho cùng một section vì một note có thể trộn
bảng và bullet. Chúng giữ line number và raw text để không mất dấu vết.
 
### 11.5. Phân loại block và suy ra ý nghĩa
 
notes/block_classifier.py:
 
- extract_blocks: nhận section và chọn parser phù hợp, tạo các NoteBlock.
 
notes/dimension_inference.py:
 
- infer_movement_role: nhận biết opening, addition, disposal, closing và các
  vai trò biến động khác từ label.
- infer_dimensions: bổ sung period, measure, movement role và dimension cho
  NoteBlock.
 
notes/unit_normalization.py:
 
- canonical_unit: đưa các cách viết đồng, nghìn đồng, triệu đồng về tên đơn vị
  chuẩn.
 
notes/sector_profile.py:
 
- TopicRule: quy tắc topic theo nhóm ngành.
- rules_for_sector: lấy bộ quy tắc cho enterprise, bank, securities hoặc
  insurance.
- classify_topic: gán topic cho tiêu đề note.
- possible_targets: trả những node statement mà topic có thể liên quan.
 
Topic là chủ đề của note, ví dụ fixed assets hoặc inventory. Nó không phải
node_id cuối cùng; linker mới quyết định liên kết cụ thể.
 
### 11.6. Liên kết và đối chiếu
 
notes/linker.py:
 
- _iter_primary_nodes: duyệt node của các statement chính.
- _node_note_ref: lấy mã note được ghi trong node chính.
- link_notes_to_primary: nối NoteSection/NoteBlock với node chính dựa trên
  note reference, topic, label, sector và context.
 
notes/reconciliation.py:
 
- _is_note_total_label: nhận diện dòng tổng của Notes.
- _sign_convention_match: kiểm tra khác biệt dấu do presentation.
- _baseline_row_node: lấy node nền từ row.
- _primary_node_index: lập chỉ mục node chính theo id, label, code và note.
- consume: hàm cục bộ nạp node vào index.
- _best_note_totals: tìm tổng Notes tốt nhất.
- _sections_for_source_ref: lọc section theo source reference.
- reconcile_notes: so sánh tổng hoặc giá trị Notes với statement chính và trả
  ReconciliationResult.
 
Đối chiếu Notes không có nghĩa Notes được ưu tiên hơn B01/B02/B03. Trong
process_one, primary statements đã được tạo trước; Notes chỉ bổ sung chi tiết,
liên kết và cảnh báo khác biệt.
 
### 11.7. Diagnostic và export
 
notes/diagnostics.py:
 
- build_diagnostics: gom scope, section, block, row, link và reconciliation
  thành chẩn đoán để biết mất dữ liệu ở bước nào.
 
notes/row_exporter.py:
 
- _json: serialize metadata thành JSON string an toàn.
- _as_list: đưa scalar hoặc list về list.
- _first_by_role: lấy giá trị đầu tiên theo role.
- flatten_note_rows: chuyển Note IR lồng nhau thành các row phẳng.
- write_rows_csv: ghi rows ra CSV.
- write_rows_json: ghi rows ra JSON.
- export_note_rows: gọi flatten và ghi các file row theo source.
- write_aggregate_rows: gom rows nhiều report thành các file aggregate.
 
### 11.8. NotesPipeline và parse_notes
 
NotesPipeline.__init__ nhận current_year và previous_year. Nó tạo các dependency
dùng chung cho Notes.
 
NotesPipeline.parse_text nhận:
 
- text Markdown;
- sector nếu caller đã biết;
- current_year, previous_year nếu có;
- primary canonical của B01/B02/B03 nếu muốn link và reconcile.
 
Nó trả NoteDocument hoặc dictionary tương đương. Thứ tự làm việc là:
 
1. detect_notes_scope.
2. sectionize_notes.
3. lấy unit và topic.
4. extract_blocks.
5. infer_dimensions và canonical_unit.
6. link_notes_to_primary.
7. reconcile_notes.
8. build_diagnostics.
 
NotesPipeline.parse_file đọc UTF-8 từ path rồi gọi parse_text.
 
parse_notes là hàm cửa vào cấp module: nhận text hoặc path cùng options, tạo
NotesPipeline và trả kết quả. process_one dùng kết quả này để gọi
flatten_note_rows, clean_notes và đặt Notes vào production report.
---
 
## 12. scripts: công cụ đánh giá, ground truth và bảo trì
 
scripts không phải đường chạy production bắt buộc. Chúng dùng để đo chất lượng,
tạo dữ liệu chuẩn, xem thay đổi giữa các phiên bản và trực quan hóa output.
 
### 12.1. scripts/visualize_output.py
 
- _value_by_period: lấy giá trị current và previous của một node.
- collect: đọc thư mục output, gom các node, summary và số liệu để hiển thị.
- main: đọc tham số dòng lệnh và ghi dữ liệu visualization.
 
### 12.2. scripts/evaluation
 
compare_main_statement_ground_truth.py:
 
- load_json: đọc JSON.
- fold_text, number: chuẩn hóa nhãn và số.
- period_role: xác định current/previous.
- collect_expected_evidence: lấy bằng chứng kỳ, nhãn, giá trị từ ground truth.
- expected_evidence: gom bằng chứng kỳ vọng.
- current_evidence: gom bằng chứng parser đã tạo.
- compare_statement: đối chiếu expected/current, tính missing, extra, matched.
- main: đọc thư mục và ghi summary.
 
compare_notes_ground_truth.py:
 
- load_json: đọc JSON.
- normalize_row: chuẩn hóa một row Notes.
- stable_json: serialize ổn định để hash hoặc so sánh.
- semantic_row, value_row: tạo khóa so sánh theo nhãn/ngữ nghĩa hoặc giá trị.
- sha256: tính hash file.
- compare_report: đối chiếu Notes output với ground truth.
- main: chạy so sánh cho nhiều report.
 
evaluate_notes_coverage.py:
 
- _files: chọn file input.
- _write_csv: ghi CSV.
- _scanner_for: tạo scanner Notes.
- _sector: lấy sector từ scanner.
- evaluate_file: chạy NotesPipeline và tính coverage một file.
- main: chạy batch và ghi báo cáo.
 
evaluate_notes_quality.py:
 
- _load_json: đọc JSON.
- _percent: tính phần trăm an toàn khi mẫu số bằng 0.
- _rows, _values: lấy rows và values từ output.
- evaluate: tính các chỉ số chất lượng Notes.
- main: đọc tham số và trả mã kết thúc.
 
export_per_report_comparison.py:
 
- load_json: đọc report.
- rate_percent: đổi tỷ lệ thành chuỗi phần trăm.
- pair_cell: tạo ô hiển thị cặp current/previous.
- row_from_report: tạo một dòng summary.
- markdown_table: render bảng Markdown.
- main: ghi bảng so sánh theo report.
 
Các script evaluation chỉ đánh giá. Chúng không được coi ground truth là nguồn
để sửa output production trong runtime.
 
### 12.3. scripts/ground_truth
 
audit_main_statement_baselines.py:
 
- _load, _line, _source_hash: đọc baseline, lấy dòng nguồn và hash.
- audit_file: kiểm tra baseline có còn khớp source không.
- main: chạy audit nhiều file.
 
build_notes_ground_truth.py:
 
- source_hash: hash source.
- native_rows: lấy row bản địa từ Note IR.
- parse_sector: đọc sector.
- build_document: tạo document ground truth cho Notes.
- main: chạy việc tạo ground truth.
 
build_notes_review_queue.py:
 
- bucket: phân nhóm row cần review.
- select_rows: lấy số row theo limit.
- selection_reason: giải thích vì sao row được chọn.
- main: ghi queue review.
 
prepare_main_statement_gold.py:
 
- load_json: đọc dữ liệu.
- source_lines: đọc source thành dòng.
- analyze_baseline: phân tích baseline và tạo các row review.
- main: chuẩn bị gold cho statement chính.
 
repair_main_statement_baselines.py:
 
- _strip, _number, _cells: làm sạch, đọc số, tách ô.
- _value_observation: tạo observation sửa chữa.
- _repair_inline: sửa row inline.
- _repair_table_row: sửa row bảng.
- repair_baseline: áp dụng các sửa chữa có bằng chứng.
- main: chạy repair.
- _load: đọc baseline.
 
review_notes_queue.py:
 
- _fold: chuẩn hóa nhãn.
- _line: lấy một dòng nguồn.
- _nearby: lấy vùng dòng quanh vị trí.
- _contains: kiểm tra text chứa token.
- review_item: tạo thông tin review cho một item.
- main: xuất queue kèm context.
 
triage_notes_reconciliation.py:
 
- _load: đọc file.
- _primary_rows: lập chỉ mục row statement chính.
- _note_sections: lập chỉ mục section Notes.
- _unit: lấy đơn vị.
- main: phân loại các mismatch cần điều tra.
 
Ground truth là dữ liệu chuẩn do con người hoặc quy trình kiểm duyệt tạo ra để
đo parser. Nó khác source: source là dữ liệu đầu vào thật; ground truth là
mốc so sánh.
 
### 12.4. scripts/maintenance
 
- build_coverage_report.main: gọi coverage reporter cho một batch.
- rebuild_universal_guide: biên dịch lại guide khi nguồn guide thay đổi.
 
---
 
## 13. Tests: đọc test để hiểu các quy tắc thật
 
Test là ví dụ thực thi cho các comment và quy tắc trong code. Nên đọc sau
pipeline, vì mỗi tên test trả lời một lỗi mà dự án từng gặp.
 
### 13.1. tests/b01
 
- test_mixed_hierarchy_context.py kiểm tra cùng nhãn Nguyên giá nhưng khác cây
  cha phải được map khác nhau; duplicate period phải đi vào audit.
- test_schema_alias_v16.py kiểm tra schema và alias có cùng node; off-balance
  không được dùng kiểu first-wins khi có conflict.
- test_statement_locator.py kiểm tra locator bỏ tiêu đề trong mục lục, trả
  candidate rows mà chưa mapping và dùng fallback khi thiếu evidence.
- test_structural_edge_cases_v22_3.py kiểm tra fragment dọc, quý cộng dồn,
  code child, end/begin period và vùng B04 của chứng khoán.
- test_structural_identity.py kiểm tra identity của code, note, context và
  detached table; code mơ hồ không được hydrate.
- test_validated_scope.py kiểm tra mục lục, heading thật và câu prose không bị
  coi là statement.
 
### 13.2. tests/b02 và tests/b03
 
- test_v22_4_semantics.py kiểm tra dash là null chứ không phải zero, note
  reference không phải số liệu, đơn vị không tự ý đổi và quý cộng dồn.
- test_v22_4_2_cashflow_fidelity.py kiểm tra vị trí dash, translation
  difference, dòng bullet, mã duy nhất, fuzzy mapping và không map nhầm
  payment thành receipts.
 
### 13.3. tests/notes
 
- test_notes_foundation.py kiểm tra note id, scope bám đến cuối tài liệu,
  bảng breakdown, movement table, đơn vị không scaling và link/reconcile không
  sửa primary.
- test_notes_rows_export_v23.py kiểm tra mỗi source row có một row export và
  tạo được CSV/JSON.
- test_notes_scope_v23.py kiểm tra tiêu đề Notes in đậm/thường, mục lục và
  statement reference giả.
- test_notes_structural_v23_1.py kiểm tra heading đánh số, bullet pair và
  header nhiều dòng không bị xuất thành data.
 
### 13.4. tests/integration và tests/quality
 
test_source_only_integrity.py kiểm tra pipeline chỉ đọc source, output cũ
không ảnh hưởng kết quả, provenance tồn tại, audit là tùy chọn, output contract
ổn định, Notes giữ year role và output không được nằm bên trong input.
 
test_ground_truth_quality.py kiểm tra suy ra năm bằng raw evidence, ngày đầu kỳ
là previous, quý cộng dồn, conflict kỳ, fiscal year không phải tháng 12 và
không nhầm ngày kiểm toán với năm báo cáo.
 
test_main_statement_baseline_repair.py kiểm tra sửa row inline, cashflow pair
và code-label table.
 
test_parser_upgrade_phases.py kiểm tra vector column, label normalization,
interleaved rows, hierarchical index, bank detail, cashflow block, source
observation, B01 date blocks và error taxonomy.
 
test_production_quality_gate.py kiểm tra numeric formatting không tạo conflict
giả, source reconciliation và trạng thái review-only khi unresolved.
 
### 13.5. tests/legacy
 
Thư mục legacy giữ các regression test của các lỗi cũ: scope nhỏ, scope qua
trang, detached total, coverage diagnostics, inline row, semantic context,
parent-child boundary, period consolidation, table alignment và column-major.
Không nên bỏ qua chúng: chúng cho biết tại sao code hiện tại có nhiều safety
gate thay vì một regex đơn giản.
 
---
 
## 14. Đọc ví dụ statement_locator từng bước
 
Với lời giải thích trong docstring:
 
~~~text
Tạo hoặc lấy lại locator cho một cặp schema/alias.
Đầu vào là hai đường dẫn catalog.
Xử lý cache instance để B01, B02 và B03 không nạp lại alias
trong cùng process.
Đầu ra là StatementLocator; nếu dependency không có thì trả None
để caller dùng fallback.
~~~
 
Có thể dịch chính xác như sau:
 
1. “Tạo hoặc lấy lại locator”: nếu cặp đường dẫn chưa có trong cache thì đọc
   schema/alias và tạo object; nếu đã có thì trả object cũ.
2. “Một cặp schema/alias”: schema nói node chuẩn nào tồn tại; alias nói nhãn
   trong Markdown có thể chỉ vào node nào.
3. “Đường dẫn catalog”: cách nói tắt cho đường dẫn đến các file cấu hình tạo
   bộ tra cứu. Hai file đó chưa phải catalog object; catalog object là cấu trúc
   đã được đọc vào bộ nhớ.
4. “Cache instance”: lưu object locator đã tạo theo cặp đường dẫn, trong RAM của
   process hiện tại.
5. “B01, B02 và B03 không nạp lại alias”: các bộ alias được tái sử dụng; source
   của từng report vẫn được quét riêng.
6. “Dependency không có”: import StatementLocator thất bại hoặc package phụ
   không được cài. Khi đó return None là chủ ý để caller không sập toàn pipeline.
7. “Caller dùng fallback”: hàm gọi sẽ dùng choose scope hoặc extractor dự phòng,
   chứ không dừng cả chương trình.
 
Đây là comment mô tả thiết kế, không phải lời khẳng định rằng locator đã map
được số liệu. Mapping xảy ra ở extractor/mapper sau khi scope đã được chọn.
 
---
 
## 15. Cách đọc và chạy dự án theo thứ tự
 
### 15.1. Thứ tự đọc file
 
1. README.md và tài liệu này.
2. app/pipeline.py: main, process_one, run_income, run_cashflow.
3. resources/schemas và resources/aliases để biết node chuẩn.
4. B02: scope, extractor, mapper, validator.
5. B03: extractor, mapper.
6. B01: extractor rồi flat_parser/pipeline.py.
7. common/output_contract.py và các file recovery/reconcile.
8. Notes/pipeline.py và các module Notes.
9. tests/b01, b02, b03, notes, integration, quality.
10. scripts khi cần đánh giá hoặc tạo ground truth.
 
### 15.2. Lệnh chạy tối thiểu
 
~~~powershell
python .\app\pipeline.py .\md_reports\ABB_BCTC_2025_hop_nhat_kiem_toan.md --output .\output\reading --notes --audit
~~~
 
Đầu vào là file Markdown; output production nằm dưới output/reading/reports;
audit nằm dưới output/reading/audit nếu bật --audit. Lệnh thật có thể thay đổi
tùy CLI options trong app/pipeline.py, nên xem argparse ở main trước khi chạy
batch.
 
### 15.3. Khi debug một dòng sai
 
1. Kiểm tra source line và scope trong audit.
2. Kiểm tra year/unit trong process_one.
3. Kiểm tra extractor đã tạo row chưa.
4. Nếu có row nhưng chưa map, đọc mapper và alias.
5. Nếu B01 bị map nhầm, đọc parent context, alias_matcher và resolver.
6. Nếu mất row, đọc source_recovery, hydrator và reconciler.
7. Nếu số đúng nhưng output sai hình dạng, đọc output_contract.
8. Nếu Notes sai, đọc scanner, sectionizer, table_parser rồi linker/reconcile.
 
Không nên bắt đầu bằng regex cuối cùng khi chưa biết row bị mất ở bước nào.
Mỗi tầng có metrics và provenance để khoanh vùng.
 
### 15.4. Kết luận
 
Dự án không chỉ là một hàm đọc bảng. Nó là pipeline nhiều tầng:
 
~~~text
source Markdown
 -> định vị vùng statement
 -> tách cấu trúc
 -> đọc số và kỳ
 -> map nhãn bằng schema/alias/context
 -> khôi phục và đối chiếu
 -> kiểm tra chất lượng
 -> đóng gói output contract
~~~
 
Nếu cần hiểu một hàm, hãy đọc comment cùng ba thứ xung quanh nó: kiểu dữ liệu
đầu vào, hàm gọi nó và hàm nhận kết quả của nó. Đó là cách biết comment đang
mô tả trách nhiệm thật nào trong toàn hệ thống.
---
 
## 16. Bổ sung: vai trò và ý nghĩa cụ thể của từng nhóm hàm
 
Phần này viết theo dạng “thẻ hàm”. Mỗi thẻ trả lời rõ:
 
- Vai trò: hàm đứng ở đâu trong hệ thống.
- Nội dung/ý nghĩa: hàm thực sự làm gì về nghiệp vụ.
- Đầu vào: dữ liệu hàm cần.
- Đầu ra: dữ liệu caller nhận được.
- Vì sao cần: lý do không gộp hàm này vào một hàm khác.
 
Tên hàm vẫn giữ nguyên như trong code để có thể tìm trực tiếp.
 
### 16.1. Nhóm điều phối: app/pipeline.py
 
#### main
 
- Vai trò: cửa vào cấp chương trình.
- Nội dung/ý nghĩa: nhận tham số dòng lệnh, chọn các file Markdown, khởi tạo
  parser dùng chung, chạy từng report và ghi output.
- Đầu vào: input path, output path, cờ Notes/audit, năm, ngành và các tùy chọn
  CLI.
- Đầu ra: reports/*.json, manifest.json và audit files tùy chọn.
- Vì sao cần: nếu không có main, các module parser chỉ chạy rời rạc và không
  tạo được batch output hoàn chỉnh.
 
#### select_md_files
 
- Vai trò: xác định tập source mà batch phải xử lý.
- Nội dung/ý nghĩa: kiểm tra một path là file hay thư mục, lọc Markdown,
  tìm đệ quy khi cần và gom các file thuộc cùng một report.
- Đầu vào: một file hoặc thư mục input.
- Đầu ra: danh sách Path đại diện cho các report.
- Vì sao cần: tránh đọc nhầm JSON output, file tạm hoặc nhiều bản trùng của
  cùng một báo cáo.
 
#### process_one
 
- Vai trò: điều phối toàn bộ vòng đời của một report.
- Nội dung/ý nghĩa: đọc source một lần, tính SHA256, xác định năm/đơn vị, lần
  lượt gọi B02, B03, B01, Notes, sau đó làm sạch và đóng gói kết quả.
- Đầu vào: Path của Markdown, parser B01, tùy chọn Notes/audit và context năm.
- Đầu ra: dictionary report gồm metadata, ba statement, Notes, metrics và
  production JSON.
- Vì sao cần: đây là điểm nối giữa các parser chuyên biệt; nó bảo đảm tất cả
  statement dùng cùng source identity, kỳ và provenance.
 
#### run_income
 
- Vai trò: cửa vào riêng cho B02.
- Nội dung/ý nghĩa: tìm scope B02, đọc các hình dạng row, chọn sector, map
  nhãn vào schema B02, recovery dữ liệu thiếu và tạo canonical.
- Đầu vào: source path/text, hai năm, sector tùy chọn, unit fallback.
- Đầu ra: rows, scope, canonical B02, metrics và trạng thái mapping.
- Vì sao cần: B02 có quy tắc kỳ, dấu và công thức riêng nên không thể dùng
  trực tiếp extractor B01 hoặc B03.
 
#### run_cashflow
 
- Vai trò: cửa vào riêng cho B03.
- Nội dung/ý nghĩa: tìm scope lưu chuyển tiền tệ, nhận diện sector và method
  direct/indirect, đọc bảng bị tách cột, map và kiểm tra công thức.
- Đầu vào: source path/text, hai năm và unit fallback.
- Đầu ra: rows, scope, method, sector, canonical B03 và metrics.
- Vì sao cần: cùng một label B03 có thể mang ý nghĩa khác theo method hoặc
  sector.
 
#### statement_locator
 
- Vai trò: tạo hoặc lấy lại bộ định vị statement.
- Nội dung/ý nghĩa: nạp schema/alias thành bảng tra cứu và giữ StatementLocator
  trong cache theo cặp đường dẫn.
- Đầu vào: schema_path và aliases_path.
- Đầu ra: StatementLocator hoặc None nếu dependency không sẵn sàng.
- Vì sao cần: tránh đọc lại alias nhiều lần trong cùng process; nó chỉ định vị
  vùng, không map giá trị.
 
#### scan_statement_context
 
- Vai trò: tạo bản đồ sơ bộ của toàn tài liệu.
- Nội dung/ý nghĩa: tìm vị trí B01, B02, B03, Notes và gợi ý ngành để Notes
  biết các statement chính nằm ở đâu.
- Đầu vào: toàn bộ Markdown.
- Đầu ra: dictionary context hoặc None.
- Vì sao cần: nhiều parser cần biết ranh giới lớn trước khi đọc chi tiết.
 
#### attach_source_provenance
 
- Vai trò: gắn nguồn gốc vào kết quả.
- Nội dung/ý nghĩa: ghi source name, SHA256, line/scope và vai trò kỳ vào
  canonical.
- Đầu vào: canonical, tên file, hash, năm và thông tin suy luận.
- Đầu ra: canonical đã gắn provenance hoặc None.
- Vì sao cần: một số liệu không có dòng nguồn thì không thể audit đáng tin.
 
#### write_json
 
- Vai trò: bộ ghi JSON dùng chung.
- Nội dung/ý nghĩa: tạo thư mục, serialize object, giữ Unicode tiếng Việt và
  ghi file có format dễ đọc.
- Đầu vào: path và object.
- Đầu ra: file JSON trên đĩa.
- Vì sao cần: gom quy tắc ghi file vào một chỗ để production và audit nhất quán.
 
### 16.2. Nhóm B02: src/b02_income
 
#### choose_income_scope
 
- Vai trò: chọn ranh giới B02 trước khi đọc row.
- Nội dung/ý nghĩa: chấm các tiêu đề ứng viên, kiểm tra phía sau có dữ liệu
  kỳ/số và dừng trước Notes hoặc statement kế tiếp.
- Đầu vào: toàn bộ text, current_year và previous_year.
- Đầu ra: start, end, score và evidence.
- Vì sao cần: nếu scope sai, extractor có thể đọc mục lục hoặc ăn sang Notes;
  mapper dù đúng cũng sẽ nhận dữ liệu sai.
 
#### extract_income_fallback
 
- Vai trò: bộ đọc B02 chịu lỗi trình bày.
- Nội dung/ý nghĩa: gọi các collector cho bảng pipe, row inline, row con theo
  kỳ, vector cột, code-led row, year section và formula pair; sau đó dedupe.
- Đầu vào: Markdown, scope/locator, hai năm, unit và sector.
- Đầu ra: danh sách IncomeRow/dictionary, scope, locator và metadata.
- Vì sao cần: file chuyển từ PDF không có một hình dạng cố định; “fallback” ở
  đây là nhiều cách đọc dự phòng, không có nghĩa kết quả kém hơn mặc định.
 
#### _extract_rows_for_scope
 
- Vai trò: bộ phối hợp các collector B02.
- Nội dung/ý nghĩa: chạy từng chiến lược đọc trên cùng một scope, gom tất cả
  row và loại bản sao.
- Đầu vào: các dòng trong scope, hai năm.
- Đầu ra: danh sách row thô.
- Vì sao cần: tách orchestration khỏi từng parser layout giúp thêm layout mới
  mà không phá collector cũ.
 
#### IncomeRow
 
- Vai trò: mô hình dữ liệu cho một dòng B02.
- Nội dung/ý nghĩa: giữ label, current, previous, code, note, unit, line_no,
  pattern, raw text và trạng thái map.
- Đầu vào: dictionary row từ extractor.
- Đầu ra: object IncomeRow.
- Vì sao cần: mapper cần một hình dạng dữ liệu ổn định dù extractor đọc từ
  bảng, bullet hay vector.
 
#### IncomeMapper.__init__
 
- Vai trò: chuẩn bị bảng ánh xạ B02.
- Nội dung/ý nghĩa: đọc schema/alias, lọc node theo sector, chuẩn hóa alias và
  tạo index label -> node_id.
- Đầu vào: đường dẫn schema, alias và sector.
- Đầu ra: object mapper có các index trong bộ nhớ.
- Vì sao cần: thao tác map từng row phải nhanh và phải ngăn alias của ngành
  khác lọt vào.
 
#### IncomeMapper.map_row
 
- Vai trò: gán một row nguồn vào node chuẩn.
- Nội dung/ý nghĩa: thử exact alias, context cha, regex/fallback và similarity;
  chỉ nhận nếu điểm đủ cao và ứng viên đứng đầu không mơ hồ.
- Đầu vào: IncomeRow chưa map.
- Đầu ra: IncomeRow có node_id/canonical_name hoặc trạng thái unresolved.
- Vì sao cần: đây là nơi chuyển câu chữ của doanh nghiệp thành trường chuẩn.
 
#### IncomeMapper.canonical
 
- Vai trò: tạo kết quả B02 chuẩn.
- Nội dung/ý nghĩa: gom nhiều row vào một node, điền current/previous, lưu
  occurrence, conflict, công thức và provenance.
- Đầu vào: IncomeRow đã map, source name, hai năm và unit.
- Đầu ra: dictionary canonical B02.
- Vì sao cần: output không thể dùng trực tiếp danh sách row trùng lặp.
 
#### Các hàm validator B02
 
- normalize_bank_semantic_signs: Vai trò chuẩn hóa dấu theo cách trình bày
  ngân hàng; đầu vào là map node; đầu ra là danh sách thay đổi có evidence.
- normalize_enterprise_formula_signs: Vai trò áp quy ước dấu doanh nghiệp;
  không tự tạo giá trị khi thiếu component.
- normalize_securities_semantic_signs: Vai trò xử lý dấu đặc thù chứng khoán.
- validate_enterprise_formulas, validate_bank_formulas,
  validate_securities_formulas, validate_insurance_formulas: Vai trò kiểm tra
  tổng theo từng sector; đầu vào là node map, đầu ra là check pass/fail/skip.
- summarize_formula_checks: Vai trò rút danh sách check thành số lượng đạt,
  hỏng và bỏ qua.
 
### 16.3. Nhóm B03: src/b03_cashflow
 
#### choose_cashflow_scope
 
- Vai trò: chọn đoạn B03 thật.
- Nội dung/ý nghĩa: chấm heading, anchor, mã và hình dạng số, đồng thời tránh
  mục lục và B04.
- Đầu vào: toàn bộ text.
- Đầu ra: start, end và evidence.
- Vì sao cần: B03 thường có thêm phụ lục hoặc phần chứng khoán dễ gây scope
  quá rộng.
 
#### detect_method
 
- Vai trò: xác định cách lập B03.
- Nội dung/ý nghĩa: tìm bằng chứng direct hoặc indirect từ title và label.
- Đầu vào: text của scope B03.
- Đầu ra: method và lý do/confidence.
- Vì sao cần: cùng node_id có thể hợp lệ ở method này nhưng không hợp lệ ở
  method kia.
 
#### detect_sector
 
- Vai trò: xác định nhóm ngành B03.
- Nội dung/ý nghĩa: dùng label, code và dấu hiệu report để nhận biết
  enterprise, bank, securities hoặc insurance.
- Đầu vào: scope text.
- Đầu ra: sector và evidence.
- Vì sao cần: catalog B03 có node dùng riêng theo ngành.
 
#### extract_cashflow_fallback
 
- Vai trò: đọc row B03 từ nhiều bố cục.
- Nội dung/ý nghĩa: xử lý bảng pipe, column-major, value-before-label,
  detached period table, mã dòng và các section dòng tiền.
- Đầu vào: Markdown, scope/locator, hai năm, method, sector, unit.
- Đầu ra: CashFlowObservation/dictionary rows và metadata.
- Vì sao cần: dữ liệu PDF thường làm nhãn và số bị đảo thứ tự hoặc tách block.
 
#### CashFlowMapper.map_one
 
- Vai trò: gán một dòng tiền vào node B03.
- Nội dung/ý nghĩa: dùng exact label trước, sau đó similarity; form code chỉ
  là tín hiệu phụ để phá hòa khi duy nhất.
- Đầu vào: CFRow.
- Đầu ra: CFRow có node_id hoặc unresolved.
- Vì sao cần: nếu dùng code làm identity duy nhất, hai dòng cùng mã sẽ bị
  gán nhầm.
 
#### CashFlowMapper.canonical
 
- Vai trò: tạo canonical B03 theo node và kỳ.
- Nội dung/ý nghĩa: gom occurrence, giữ section/method/code/note, tạo
  conflict và chạy formula checks.
- Đầu vào: rows đã map, source, hai năm, unit.
- Đầu ra: canonical B03 và checks.
- Vì sao cần: downstream cần một cấu trúc ổn định không phụ thuộc layout nguồn.
 
### 16.4. Nhóm B01: src/b01_financial_position và flat_parser
 
#### FinancialPositionSourceParser.parse_text
 
- Vai trò: cửa vào B01 cấp source.
- Nội dung/ý nghĩa: gọi FlatParserPipeline, nhận canonical cây, gắn unit,
  provenance, metrics và tóm tắt.
- Đầu vào: Markdown, current/previous year, option.
- Đầu ra: canonical B01, nodes, observations, scope, context và metrics.
- Vì sao cần: B01 cần giữ cả cây cấu trúc và dữ liệu semantic; parser này đóng
  gói chúng thành kết quả dùng được.
 
#### normalize_lines
 
- Vai trò: biến text thô thành dòng có địa chỉ.
- Nội dung/ý nghĩa: tách dòng, lưu raw text, text chuẩn hóa và số dòng.
- Đầu vào: raw Markdown.
- Đầu ra: list SourceLine.
- Vì sao cần: mọi provenance và debug đều cần biết giá trị nằm ở dòng nào.
 
#### build_nodes
 
- Vai trò: dựng cây cấu trúc của B01.
- Nội dung/ý nghĩa: dùng heading, indentation, bảng và thứ tự dòng để quyết
  định parent/child; đồng thời giữ giá trị cục bộ.
- Đầu vào: SourceLine, table context và guide.
- Đầu ra: list StructuralNode có quan hệ cây.
- Vì sao cần: cùng một nhãn chỉ có nghĩa khi biết nó nằm dưới node cha nào.
 
#### extract_values và extract_periods
 
- Vai trò: tách dữ liệu nguyên thủy.
- Nội dung/ý nghĩa: extract_values tìm số; extract_periods tìm năm/ngày/kỳ.
  Hai hàm không tự map nhãn.
- Đầu vào: text của node, line number, guide.
- Đầu ra: PrimitiveValue và PrimitivePeriod.
- Vì sao cần: tách số/kỳ thành object riêng giúp resolver ghép đúng hai cột.
 
#### StructuralClassifier.classify_all
 
- Vai trò: hiểu hình dạng từng node.
- Nội dung/ý nghĩa: phân biệt heading, label, period, value, wrapper và noise,
  rồi truyền ngữ cảnh cha-con.
- Đầu vào: list StructuralNode.
- Đầu ra: chính list node đã có loại, score và evidence.
- Vì sao cần: collector cần biết node là nhãn hay số trước khi semantic mapping.
 
#### StatementLocator.locate
 
- Vai trò: định vị vùng B01/B02/B03 theo profile.
- Nội dung/ý nghĩa: tìm alias hit, tạo candidate start/end, chấm evidence và
  chọn scope có confidence đủ cao.
- Đầu vào: raw source và profile.
- Đầu ra: dictionary selected_scope, candidates, rows và metrics.
- Vì sao cần: giảm phạm vi quét và ngăn mục lục/Notes làm nhiễu parser.
 
#### StatementLocator.evaluate_scope
 
- Vai trò: cổng an toàn giữa locator nhanh và parser cấu trúc.
- Nội dung/ý nghĩa: so sánh scope locator với baseline độc lập; nếu chênh lệch
  quá lớn thì từ chối scope locator.
- Đầu vào: scope locator và baseline scope.
- Đầu ra: accepted boolean và reason.
- Vì sao cần: không để một cụm alias dày nhưng sai vùng điều khiển toàn parser.
 
#### collect_observation
 
- Vai trò: ghi lại điều parser quan sát ở node.
- Nội dung/ý nghĩa: ghép node, primitive value, candidate alias và context
  thành FieldObservation trước khi quyết định.
- Đầu vào: StructuralNode, catalog, candidates và context.
- Đầu ra: FieldObservation hoặc danh sách observation.
- Vì sao cần: giữ bằng chứng nguồn ngay cả khi chưa map được chắc chắn.
 
#### resolve_observation
 
- Vai trò: biến observation thành field đã giải quyết.
- Nội dung/ý nghĩa: chọn candidate, gắn kỳ, đơn vị, giá trị và điểm tin cậy.
- Đầu vào: FieldObservation và StatementContext.
- Đầu ra: ResolvedField/ResolvedValue.
- Vì sao cần: tách “có khả năng là node này” khỏi “đã quyết định dùng node này”.
 
#### consolidate_resolved_fields
 
- Vai trò: gom các kết quả giải quyết trùng hoặc tương thích.
- Nội dung/ý nghĩa: nhóm occurrence cùng identity, ghi conflict và tránh tạo
  hai node canonical cho cùng một nguồn.
- Đầu vào: list ResolvedField.
- Đầu ra: list field đã hợp nhất.
- Vì sao cần: một dòng có thể bị nhiều collector đọc lại.
 
#### map_first_value_per_period
 
- Vai trò: tạo giá trị canonical cuối cho từng kỳ.
- Nội dung/ý nghĩa: lấy occurrence hợp lệ đầu tiên theo current/previous
  nhưng vẫn giữ các occurrence khác để audit.
- Đầu vào: resolved fields.
- Đầu ra: canonical node map.
- Vì sao cần: chính sách first value per period được kiểm soát, không bị ghi đè
  ngẫu nhiên bởi lần đọc sau.
 
#### validate_financial_position
 
- Vai trò: kiểm tra logic B01.
- Nội dung/ý nghĩa: so sánh các tổng như tổng tài sản với tổng nguồn vốn và
  các tổng con; chỉ ghi check, không tự sửa source.
- Đầu vào: canonical B01.
- Đầu ra: danh sách checks và trạng thái.
- Vì sao cần: một parser có thể map được nhiều label nhưng vẫn ghép sai kỳ;
  phép tổng là bằng chứng độc lập để phát hiện.
 
### 16.5. Nhóm định vị và cache
 
#### _alias_entries
 
- Vai trò: chuyển file alias thành dữ liệu tra cứu.
- Nội dung/ý nghĩa: đọc exact, aliases, contains, parent_context và canonical
  name; loại metadata hoặc alias nhiễu.
- Đầu vào: alias JSON và schema JSON.
- Đầu ra: list AliasEntry.
- Vì sao cần: locator và mapper không nên phải hiểu từng dạng JSON mỗi lần scan.
 
#### _hits
 
- Vai trò: tìm vị trí alias trong source.
- Nội dung/ý nghĩa: chuẩn hóa dòng, tìm alias theo token đầu, bỏ mục lục/rác
  và tạo bằng chứng line/page.
- Đầu vào: list SourceLine.
- Đầu ra: list AliasHit.
- Vì sao cần: score scope cần biết alias xuất hiện dày ở đâu.
 
#### _score
 
- Vai trò: lượng hóa chất lượng scope.
- Nội dung/ý nghĩa: cộng điểm title, node đa dạng, signature, numeric payload,
  period và table; tách score xếp hạng khỏi confidence routing.
- Đầu vào: candidate scope và hit.
- Đầu ra: ScopeCandidate có score/confidence/evidence.
- Vì sao cần: chọn vùng phải dựa trên nhiều bằng chứng, không dựa một từ khóa.
 
### 16.6. Nhóm common: khôi phục, đối chiếu, output
 
#### infer_report_year_pair
 
- Vai trò: xác định hai năm mà report đang trình bày.
- Nội dung/ý nghĩa: chấm năm trong title, period header, date và row; bỏ qua
  ngày ký, mục lục hoặc tham chiếu pháp lý khi không phải kỳ báo cáo.
- Đầu vào: text hoặc metadata report.
- Đầu ra: current_year, previous_year và evidence.
- Vì sao cần: gán nhầm năm sẽ làm mọi giá trị chuyển sang sai cột.
 
#### detect_document_unit
 
- Vai trò: xác định đơn vị chung của report.
- Nội dung/ý nghĩa: tìm “đồng”, “nghìn đồng”, “triệu đồng” và giữ nguồn cùng
  confidence.
- Đầu vào: toàn bộ text.
- Đầu ra: UnitContext.
- Vì sao cần: cùng số 1000 có ý nghĩa khác nhau theo đơn vị.
 
#### extract_generic_statement_rows
 
- Vai trò: recovery dùng chung.
- Nội dung/ý nghĩa: đọc các row mà extractor chuyên biệt bỏ sót, nhất là
  label/value tách dòng hoặc bảng qua trang.
- Đầu vào: text, start/end, hai năm, statement.
- Đầu ra: RecoveredRow.
- Vì sao cần: cứu dữ liệu từ source nhưng vẫn cần provenance và bước kiểm tra
  trước khi nhập canonical.
 
#### hydrate_canonical_by_form_code
 
- Vai trò: bổ sung giá trị vào node đã biết bằng mã biểu mẫu.
- Nội dung/ý nghĩa: chỉ hydrate khi code, kỳ, sector, method và context đủ
  duy nhất; code mơ hồ thì giữ review.
- Đầu vào: canonical, evidence code-period, sector, method.
- Đầu ra: canonical bổ sung hoặc không đổi kèm reason.
- Vì sao cần: code có thể giúp nối hai block bị tách nhưng không được thay thế
  ngữ cảnh semantic.
 
#### reconcile_source_observations
 
- Vai trò: đối chiếu semantic node với row nguồn.
- Nội dung/ý nghĩa: nhóm theo identity, bỏ khác biệt format số, chọn node ưu
  tiên và ghi link/conflict/resolution.
- Đầu vào: canonical có semantic và source observations.
- Đầu ra: canonical đã có reconciliation metadata.
- Vì sao cần: parser cần biết hai representation có cùng một nguồn hay là hai
  dòng thật sự khác nhau.
 
#### build_metrics và build_cashflow_metrics
 
- Vai trò: đo sức khỏe của pipeline.
- Nội dung/ý nghĩa: tính coverage, unresolved, duplicates, conflicts,
  confidence, sector/method và quality flags.
- Đầu vào: canonical, rows, scope và context.
- Đầu ra: metrics dictionary.
- Vì sao cần: output không nên chỉ có số; cần biết số được đọc chắc đến mức nào.
 
#### clean_statement
 
- Vai trò: chuyển canonical nội bộ thành statement theo output contract.
- Nội dung/ý nghĩa: giữ field được phép, chuẩn hóa value/mapping/evidence,
  loại dữ liệu debug không thuộc production.
- Đầu vào: canonical và metrics.
- Đầu ra: dictionary B01/B02/B03 ổn định.
- Vì sao cần: cấu trúc nội bộ có thể đổi nhưng consumer bên ngoài cần contract
  ổn định.
 
#### build_production_report
 
- Vai trò: tạo JSON cuối cùng cho một report.
- Nội dung/ý nghĩa: ghép metadata, periods, ba statement, Notes và quality
  gate.
- Đầu vào: các statement đã clean, Notes đã clean và metadata.
- Đầu ra: production report dictionary.
- Vì sao cần: đây là nơi thống nhất schema đầu ra giữa các parser khác nhau.
 
### 16.7. Nhóm Notes
 
#### detect_notes_scope
 
- Vai trò: tìm ranh giới phần thuyết minh.
- Nội dung/ý nghĩa: nhận diện title Notes, bỏ mục lục và decoy, dừng khi phù
  hợp; không đọc row chi tiết.
- Đầu vào: toàn bộ Markdown.
- Đầu ra: NotesScope.
- Vì sao cần: Notes có thể xuất hiện cả trong mục lục và trong nội dung thật.
 
#### sectionize_notes
 
- Vai trò: chia Notes thành các đề mục.
- Nội dung/ý nghĩa: nhận diện note id, title, page và start/end của từng
  NoteSection.
- Đầu vào: text và NotesScope.
- Đầu ra: list NoteSection.
- Vì sao cần: table parser cần biết nó đang đọc Note 4 hay Note 12.
 
#### extract_blocks
 
- Vai trò: đọc nội dung bên trong một section.
- Nội dung/ý nghĩa: chọn table parser hoặc structural parser, tạo NoteBlock,
  NoteRow và NoteValue.
- Đầu vào: NoteSection, text, năm và unit.
- Đầu ra: các block/row Notes.
- Vì sao cần: Notes không chỉ có Markdown table; bullet và key-value cũng là
  dữ liệu thật.
 
#### link_notes_to_primary
 
- Vai trò: liên kết chi tiết Notes với B01/B02/B03.
- Nội dung/ý nghĩa: dùng note reference, topic, label, sector và context để
  tạo NoteLink.
- Đầu vào: NoteDocument và primary canonical.
- Đầu ra: list NoteLink.
- Vì sao cần: chi tiết Notes chỉ có giá trị sử dụng khi biết nó giải thích node
  chính nào.
 
#### reconcile_notes
 
- Vai trò: kiểm tra Notes có phù hợp statement chính không.
- Nội dung/ý nghĩa: so sánh total/value theo kỳ, cho phép khác biệt dấu do
  presentation nhưng không tự sửa primary.
- Đầu vào: NoteDocument và primary canonical.
- Đầu ra: list ReconciliationResult.
- Vì sao cần: phát hiện mismatch hoặc thiếu liên kết mà không làm mất số liệu
  chính đã có provenance.
 
#### flatten_note_rows
 
- Vai trò: chuyển IR Notes lồng nhau thành rows dễ tiêu thụ.
- Nội dung/ý nghĩa: mỗi row giữ note id, section, label, values, dimensions,
  source line và link.
- Đầu vào: note_ir dictionary.
- Đầu ra: list row phẳng.
- Vì sao cần: CSV/JSON aggregate không nên phụ thuộc cây object nội bộ.
 
#### NotesPipeline.parse_text
 
- Vai trò: điều phối toàn bộ Notes.
- Nội dung/ý nghĩa: scanner -> sectionizer -> block parser -> dimension/unit
  -> linker -> reconciliation -> diagnostics.
- Đầu vào: Markdown, năm, sector và primary tùy chọn.
- Đầu ra: NoteDocument hoặc dictionary Notes IR.
- Vì sao cần: gom các bước Notes thành một cửa vào giống B01/B02/B03.
 
### 16.8. Cách đọc một hàm cụ thể trong code
 
Khi mở một hàm, hãy đọc theo thứ tự:
 
1. Chữ ký hàm: biết input thực sự là str, Path, list, dict hay object.
2. Docstring/comment: biết ý định tác giả.
3. Hàm được gọi bên trong: biết nó biến đổi dữ liệu theo các bước nào.
4. Giá trị return: biết caller sẽ dùng kết quả ra sao.
5. Hàm gọi nó: biết output có được ghi file, map tiếp hay chỉ dùng làm evidence.
6. Test tương ứng: biết trường hợp biên nào đã được bảo vệ.
 
Ví dụ với IncomeMapper.map_row:
 
~~~text
IncomeRow
  -> làm sạch label/code
  -> thử exact alias
  -> thử parent context
  -> thử regex/similarity
  -> kiểm tra điểm và độ mơ hồ
  -> trả IncomeRow đã map hoặc unresolved
~~~
 
Như vậy “map_row” không có nghĩa chung chung là “ánh xạ”. Vai trò chính xác
của nó là biến một dòng văn bản nguồn thành một dòng có node chuẩn, nhưng chỉ
khi bằng chứng đủ an toàn.
