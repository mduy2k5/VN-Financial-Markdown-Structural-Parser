# Báo cáo tác động của cấu trúc Markdown nguồn đến kết quả

## 1. Phạm vi và kết luận

Báo cáo này tách riêng phần kết quả bị ảnh hưởng bởi cách Markdown được tạo ra từ OCR/LLM khỏi lỗi parser. Phạm vi gồm 57 file báo cáo, chạy bằng batch production v19 với audit đầy đủ.

Kết luận chính: Markdown không chỉ làm mất một vài dòng. Trong nhiều file, Markdown đã làm mất thông tin định danh của một observation: nó thuộc kỳ nào, thuộc dòng cha hay dòng con nào, mã số nào, hoặc thuộc bảng chính hay bảng phụ nào. Khi thông tin này không còn trong nguồn, parser không thể suy luận an toàn mà không có nguy cơ gán nhầm số.

Vì vậy parser hiện giữ giá trị ở dạng `source-only`, đánh dấu `ambiguous` hoặc giữ conflict thay vì tự ghi đè. Các trạng thái này làm giảm độ phủ và tỷ lệ khớp tên, nhưng đó là ảnh hưởng của cấu trúc Markdown/schema, không phải bằng chứng parser đọc sai số.

## 2. Bằng chứng tổng hợp

### 2.1. Dòng quan sát không nối được vào schema

| Statement | Số output audit | Dòng quan sát nguồn | Nối được schema | Chỉ giữ theo nguồn | Tỷ lệ source-only | File có source-only |
|---|---:|---:|---:|---:|---:|---:|
| B01 - Bảng cân đối | 57 | 2.191 | 1.418 | 773 | 35,28% | 57/57 |
| B02 - Kết quả kinh doanh | 57 | 998 | 847 | 151 | 15,13% | 30/57 |
| B03 - Lưu chuyển tiền | 56* | 2.144 | 1.818 | 326 | 15,21% | 47/56 |
| **Tổng** | **170** | **5.333** | **4.083** | **1.250** | **23,44%** | — |

`source-only` nghĩa là parser đã giữ được bằng chứng nguồn và giá trị, nhưng không có đủ định danh để nối chắc chắn vào một node chuẩn. Đây là vùng ảnh hưởng đến kết quả; không nên đồng nhất toàn bộ source-only với lỗi parser.

`*` Một file không có vùng B03 có cấu trúc nên không tạo canonical B03.

### 2.2. Các cảnh báo trực tiếp do cấu trúc nguồn tạo ra

| Dấu hiệu trong audit | B01 | B02 | B03 | Ý nghĩa đối với kết quả |
|---|---:|---:|---:|---|
| Conflict khi khôi phục từ nguồn | 38 | 6 | 5 | Nguồn và node hiện có đưa ra hai cặp giá trị khác nhau; parser không tự ghi đè |
| Vị trí mơ hồ cha-con | 13 | 0 | 0 | Nhãn lặp hoặc thiếu cấp cha-con, không xác định được node đích |
| Mơ hồ phạm vi kỳ | 0 | 10 | 0 | Cùng nhãn chứa kỳ quý/lũy kế hoặc kỳ chính nhưng không có dấu phân cách đủ rõ |
| Node semantic có conflict | 44 node | 0 | 0 | Cùng một mã chuẩn nhận nhiều bằng chứng khác nhau |
| Va chạm parent/child trên cùng mã | 21 | 0 | 0 | Dòng cha và dòng con bị ép vào cùng một node schema |

## 3. Markdown ảnh hưởng thế nào đến các tỷ lệ

| Statement | Khớp số theo kỳ + giá trị | Khớp riêng giá trị | Khớp tên + kỳ + giá trị | Cặp số thiếu |
|---|---:|---:|---:|---:|
| B01 | 96,93% | 98,13% | 91,22% | 167 |
| B02 | 99,55% | 99,59% | 95,12% | 10 |
| B03 | 93,03% | 94,63% | 89,83% | 184 |

Diễn giải:

- Khi “khớp riêng giá trị” cao nhưng “khớp tên + kỳ + giá trị” thấp, số thường đã được đọc đúng nhưng không gắn được đúng tên/cây/kỳ. Đây là dấu hiệu đặc trưng của Markdown mất context.
- Khi độ phủ thấp, Markdown thường chỉ ghi một kỳ, ghi dấu `-`, hoặc chỉ có số ở dòng con mà không có số tổng ở dòng cha. Parser không được phép lấy số dòng con thay cho số dòng cha.
- Khi khớp số thấp thật sự, cần phân biệt hai trường hợp: nguồn bị đảo thứ tự cột hoặc baseline không hiểu thứ tự cột; và nguồn thực sự thiếu/nhập nhằng giá trị. Báo cáo này không quy nhầm hai trường hợp đó thành lỗi parser.

## 4. Các dạng lỗi Markdown gây ảnh hưởng

### 4.1. Mất cây cha-con hoặc lặp nhãn không có định danh

Markdown có thể giữ lại nhãn và số nhưng làm mất indentation, mã số, hoặc nhãn cấp trung gian. Khi đó cùng một nhãn nhìn giống nhau nhưng thực tế có thể là tổng, dòng con, kỳ hạn ngắn hoặc kỳ hạn dài.

Ảnh hưởng:

- giảm tỷ lệ khớp tên;
- tạo source-only;
- tạo semantic conflict nếu ép các dòng vào cùng canonical node;
- parser phải giữ conflict thay vì chọn một số không có bằng chứng.

Ví dụ CII:

- Dòng 381: `Đầu tư nắm giữ đến ngày đáo hạn` dưới cây **Tài sản ngắn hạn > Đầu tư tài chính ngắn hạn**.
- Dòng 540: cùng nhãn dưới cây **Tài sản dài hạn > Đầu tư tài chính dài hạn**.

Schema hiện chỉ có một node `ASSET.FIN_INV.HTM`, nên hai cặp số không thể tách chắc chắn. Đây là nguyên nhân trực tiếp làm B01 CII chỉ đạt 67,16% khớp kỳ + giá trị dù khớp riêng giá trị đạt 96,97%.

Ví dụ VCB:

```text
2. Vay các tổ chức tín dụng khác
31/12/2025: 305.903.589
31/12/2024: 223.171.381
31/12/2025: 15.255.255
31/12/2024: 11.362.577
```

Sau cặp số đầu tiên không có nhãn con mới. Markdown không cho biết cặp số thứ hai là một dòng con, một phần chi tiết hay một lần lặp. Kết quả là VCB còn một source-recovery conflict tại dòng 364; parser không tự chọn một cặp.

### 4.2. Cột kỳ bị tách khỏi dòng dữ liệu hoặc bị đảo thứ tự

Một số Markdown ghi header thành các dòng độc lập:

```text
Số đầu năm
(Trình bày lại)
Số cuối năm
Mã Thuyết minh
số mình
300
27.563.291.053.672
25.567.783.329.754
```

Trong mẫu này, số đầu tiên là kỳ trước và số thứ hai là kỳ hiện tại. CII có dạng này ở phần nguồn vốn, bắt đầu quanh dòng 593. Nếu baseline đọc mọi chuỗi hai số theo thứ tự hiện tại-trước đây, tỷ lệ đối chiếu bị giảm dù parser bám đúng thứ tự header trong Markdown.

Đây là lý do CII có tỷ lệ số thấp hơn các file khác sau khi parser được sửa đúng theo nguồn. Phần giảm này phản ánh sự khác nhau giữa kiến trúc Markdown và baseline plain-sequential, không phải parser đảo số.

### 4.3. Dòng cha chỉ có một kỳ, còn kỳ kia chỉ xuất hiện ở dòng con

Một số file ghi giá trị tổng ở một kỳ nhưng không ghi giá trị tổng ở kỳ còn lại; các giá trị kỳ kia chỉ xuất hiện ở các dòng chi tiết.

Ví dụ VCB:

- `Đầu tư tài chính dài hạn` - dòng 251;
- `Tài sản cố định` - dòng 270;
- `Tài sản khác` - dòng 289.

Các block này có giá trị ở dòng con hoặc ở kỳ hiện tại, nhưng không có giá trị của chính dòng cha ở kỳ trước. Vì vậy B01 VCB có độ phủ `98,96%/94,79%`, trong khi khớp kỳ + giá trị vẫn là `100%`. Độ phủ thấp phản ánh nguồn không cung cấp đủ số ở đúng node, không phải parser làm mất số.

### 4.4. Mã số, thuyết minh hoặc công thức bị tách thành dòng số độc lập

Markdown/LLM có thể serialize một dòng bảng thành:

```text
10. Quỹ khen thưởng, phúc lợi
322
37.315.781.858
45.639.872.404
```

Hoặc chèn công thức giữa hai giá trị:

```text
TỔNG CỘNG NGUỒN VỐN
440
36.722.431.033.992
(440 = 300 + 400)
37.524.891.642.819
```

Nếu không có quy tắc cấu trúc, parser có thể đọc `322`, `440` hoặc số trong công thức như một giá trị tài chính. Mẫu này đã được sửa trong parser và có test hồi quy; nó được ghi ở đây để chỉ ra nguồn Markdown đã tạo ra rủi ro gì.

### 4.5. Dấu `-` hoặc chỉ có một block kỳ

Dấu `-` trong Markdown là bằng chứng “không báo số”, không phải số 0. Một số block chỉ có một kỳ hoặc chỉ có một heading kỳ, nên kỳ còn lại không có giá trị ở đúng nhãn.

Ảnh hưởng là giảm coverage, không phải sai số số học. Ví dụ CTG B03 chỉ có `9/29` nhóm dòng có giá trị ở kỳ trước, coverage kỳ trước còn `31,03%`. Nguồn quanh các dòng 996-1003 thể hiện một block 2025 nhưng không gắn đủ giá trị 2024 cho từng chỉ tiêu. Parser giữ thiếu kỳ thay vì sao chép số hoặc đổi `-` thành 0.

### 4.6. Trộn bảng chính, bảng phụ, quý và lũy kế

Một số Markdown đặt các bảng quý, lũy kế, thuyết minh hoặc bảng bổ sung liền nhau nhưng không có boundary rõ. Khi cùng một nhãn xuất hiện trong nhiều phạm vi, parser có thể đọc được số nhưng không biết số đó thuộc B02 chính, kỳ quý hay phần lũy kế.

Audit ghi nhận 10 mơ hồ phạm vi kỳ ở B02 trên 4 file. Các trường hợp này làm giảm khớp tên/kỳ và có thể làm công thức tổng không khớp nếu lấy nhầm observation kỳ phụ.

### 4.7. Dòng quan sát có giá trị nhưng không có tên schema tương ứng

BSI là ví dụ rõ nhất:

- B01 có 98 dòng quan sát nguồn;
- chỉ 12 dòng nối được vào schema;
- 86 dòng chỉ giữ theo nguồn;
- 1 dòng còn mơ hồ về node tương ứng;
- khớp riêng giá trị đạt 99,41%, nhưng khớp tên + kỳ + giá trị chỉ đạt 71,96%.

Điều này cho thấy phần thấp chủ yếu nằm ở tên/quan hệ schema và cấu trúc Markdown, không nằm ở việc đọc sai số.

FRT cũng có khớp số `100%` nhưng khớp tên chỉ `53,12%`: 16 dòng quan sát nguồn, 11 dòng nối schema, 5 dòng source-only và 3 vị trí mơ hồ cha-con.

## 5. Phân loại ảnh hưởng

### Ảnh hưởng chắc chắn do Markdown/nguồn

- thiếu hoặc sai indentation làm mất cây cha-con;
- cùng nhãn lặp nhưng không có mã/nhãn con;
- cột kỳ nằm riêng, không nằm trên cùng dòng với dữ liệu;
- dòng cha không có giá trị nhưng dòng con có giá trị;
- dấu `-` hoặc block kỳ bị thiếu;
- bảng quý/lũy kế/bảng phụ không có boundary rõ;
- mã số và công thức bị tách thành dòng số độc lập.

### Ảnh hưởng cần xem đồng thời với schema

`source-only` không tự chứng minh Markdown sai. Nó có thể là:

- Markdown mất nhãn/cây;
- schema chưa có node tương ứng;
- alias chưa bao phủ cách viết của nguồn;
- bảng nguồn chứa observation ngoài phạm vi statement chính.

Do đó production không tự gán source-only vào schema chỉ để tăng coverage. Làm vậy sẽ tăng điểm giả nhưng có thể làm sai dữ liệu.

### Không còn xem là lỗi parser sau đợt sửa

- đảo kỳ do header `Số đầu năm`/`Số cuối năm`;
- đọc mã số đứng riêng thành giá trị;
- đọc công thức chen giữa hai giá trị;
- nhầm context parent/child ở các mẫu VCB;
- báo giả ở VIB/FRT do alias hoặc nhãn lặp;
- đọc đơn vị tiền tệ như một semantic role.

## 6. Tác động đến quyết định production

51/57 file vẫn có trạng thái `review_required`, nhưng con số này không đồng nghĩa 51 file đều có lỗi parser. Phần lớn review flag đến từ một trong ba nguyên nhân:

1. Markdown không cung cấp đủ định danh để map an toàn;
2. baseline đối chiếu không biểu diễn đúng thứ tự/cấu trúc của Markdown;
3. nguồn có conflict thật giữa dòng cha, dòng con, kỳ chính hoặc kỳ phụ.

Vì vậy production gate cần tiếp tục bảo thủ:

- không tự điền giá trị thiếu của dòng cha từ dòng con;
- không đổi dấu `-` thành 0;
- không tự chọn một trong hai cặp số khi nhãn lặp;
- giữ source-only và conflict trong audit;
- chỉ coi là lỗi parser khi nguồn có nhãn, kỳ, giá trị và context đủ rõ nhưng canonical vẫn gắn sai.

## 7. Kết luận

Markdown hiện là nguồn gây giảm kết quả lớn nhất ở phần identity/context, đặc biệt với B01. Bằng chứng tổng hợp là 1.250/5.333 dòng quan sát chỉ có thể giữ theo nguồn, 49 conflict khôi phục và 10 mơ hồ phạm vi kỳ B02.

Các giá trị số vẫn được đọc khá tốt: B01 `96,93%`, B02 `99,55%`, B03 `93,03%` khớp đồng thời kỳ + giá trị. Phần thấp hơn ở tên, độ phủ hoặc một số file không nên được diễn giải đơn giản là parser kém; nguyên nhân chính là Markdown đã làm mất cấu trúc cần thiết để xác định observation thuộc node nào.

Audit nguồn đầy đủ: `C:\Users\maing\AppData\Local\Temp\flatten-production-v19\audit`.
