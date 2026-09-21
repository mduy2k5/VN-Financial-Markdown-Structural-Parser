# Bằng chứng structural recovery và source context

## Kết luận ngắn

Đúng: lỗi cốt lõi của nhóm báo cáo sai trước đây là B02/B03 chưa giữ được cây cha–con như B01. Khi dữ liệu bị làm phẳng thành các dòng độc lập, parser không biết một nhãn lặp là:

- tổng của nhóm cha;
- dòng con có cùng tên hoặc gần giống tên;
- hay một dòng cùng nhãn nhưng thuộc phạm vi kỳ báo cáo khác.

Vì vậy, cùng một nhãn có thể bị gán nhầm vào cùng một canonical node, hoặc một giá trị của dòng cha bị gán cho dòng con trước đó.

Tuy nhiên, không phải mọi `review_required` đều là lỗi parser. Sau khi bổ sung structural recovery, các trường hợp còn lại được tách thành ba loại:

1. **Lỗi parser**: thiếu hoặc gán sai quan hệ cha–con, sai provenance, sai form code.
2. **Nguồn không đủ thông tin**: nguồn có nhiều giá trị nhưng không có nhãn con hoặc không có ranh giới kỳ rõ ràng.
3. **Giới hạn schema/độ phủ**: nguồn có dòng hợp lệ nhưng canonical schema hiện tại không có node tương ứng.

## Bằng chứng theo file

### VCB

Nguồn: `md_reports/VCB_BCTC_2025_hop_nhat_kiem_toan.md`

#### 1. Nhãn cha và nhãn con cùng tên

Ở phần tài sản:

```text
line 289  X. Tài sản Có khác
line 291  31/12/2025: 33.993.212
...
line 304  Tài sản Có khác
line 306  31/12/2025: 5.951.104
```

Đây là bằng chứng trực tiếp rằng nhãn `Tài sản Có khác` xuất hiện ở hai cấp khác nhau. Nếu chỉ parse theo nhãn/dòng thì hai giá trị đều có thể bị map vào `ASSET.OTHER`. Sau khi sửa structural context, kết quả là:

- cha `ASSET.OTHER`: `33.993.212`;
- con `ASSET.OTHER.OTHER`: `5.951.104`;
- hai occurrence được phân biệt bằng `source_context` và `hierarchy_path`.

#### 2. Nguồn không đặt nhãn cho giá trị con

Ở phần nợ phải trả:

```text
line 364  2. Vay các tổ chức tín dụng khác
line 365  31/12/2025: 305.903.589
line 367  31/12/2025: 15.255.255
```

Giá trị thứ hai không có nhãn con rõ ràng. Parser không được phép tự đoán tên con; trường hợp này được giữ lại để `review_required`/source review. Đây là **giới hạn của dữ liệu gốc**, không phải lỗi tách cây còn sót.

#### 3. B02 có nhiều phạm vi kỳ trong cùng một nhãn

Ở B02, các dòng `Chi phí thuế TNDN hiện hành`, `Chi phí thuế TNDN` và `Lợi nhuận sau thuế` xuất hiện ở cả phạm vi quý và lũy kế trong cùng vùng nguồn, khoảng lines 728–758. Các cặp giá trị khác nhau là hợp lệ theo nguồn nhưng thiếu marker phạm vi đủ mạnh ở lớp dòng đã làm phẳng.

Sau sửa, parser không còn báo đây là semantic conflict; nó ghi nhận rõ `source_period_scope_ambiguities = 3` và giữ canonical theo phạm vi statement đã chọn. Đây là **mơ hồ phạm vi kỳ của nguồn**, không phải parser tự gán nhầm.

### BSI

Nguồn: `md_reports/BSI_BCTC_2025_hop_nhat_kiem_toan.md`

#### 1. Cùng tên cha/con trong B01

```text
line 719  III. Tài sản dài hạn khác
line 734  4. Tài sản dài hạn khác
```

Hai dòng cùng nhãn nhưng khác cấp. Trước đây source recovery có thể coi đây là conflict. Sau sửa, nếu không có đủ child schema để chứng minh mapping thì nó được ghi là `source_recovery_structural_ambiguity`, không bịa canonical value và không tính là recovery conflict.

#### 2. Alias khác nhau nhưng cùng canonical node

```text
line 833  1.1. Vốn đầu tư của chủ sở hữu
line 836  1.1. Vốn góp của chủ sở hữu
```

Hai nhãn này cùng hội tụ về `EQUITY.OWNER_CAPITAL`. Đây không phải hai giá trị độc lập nếu source context cho thấy một dòng là parent và một dòng là child. Parser mới ghi nhận `structural_context_collision` thay vì semantic conflict.

Kết quả direct audit BSI B01:

- semantic conflicts: `0`;
- source recovery conflicts: `0`;
- structural context collisions: `2`;
- canonical value của parent được giữ ổn định;
- occurrence của child được lưu lại kèm source context để audit.

#### 3. B03: lỗi gán giá trị cha vào dòng con đã được tái hiện và sửa

Vùng nguồn quanh lines 1368–1385 có cấu trúc:

```text
02 Điều chỉnh cho các khoản
  06 Chi phí lãi vay
  07 Lãi từ hoạt động đầu tư
  08 Dự thu tiền lãi
    Năm nay  -8.972.897.043
    Năm trước -8.355.631.386
  Năm nay  -233.662.533.028
  Năm trước -106.577.700.028
```

Nếu parser chỉ giữ trạng thái `pending` mà không kiểm tra indent, cặp giá trị của dòng cha có thể bị gán cho dòng `08 Dự thu tiền lãi`. Sau khi thêm điều kiện indent:

- dòng `08 Dự thu tiền lãi` nhận `-8.972.897.043` và `-8.355.631.386`;
- cặp `-233.662.533.028` và `-106.577.700.028` được giữ cho dòng cha;
- provenance được hiệu chỉnh về đúng source line.

Đây là **lỗi parser thực sự**, đã được sửa và có test hồi quy.

#### 4. Mã 103 không có node tương ứng trong schema

BSI B03 có dòng `103 Tiền và các khoản tương đương tiền cuối năm`, trong khi schema hiện tại không có canonical node cho form code `103`. Parser mới không fuzzy-map dòng này vào node `101.2`; nó giữ là source-only/unmapped.

Đây là **schema coverage gap**, không phải lỗi structural recovery.

### VIB

Nguồn: `md_reports/VIB_BCTC_2025_hop_nhat_kiem_toan.md`

VIB là bằng chứng cho trường hợp parser đã giữ đúng cây cha–con:

```text
line 372  Tiền gửi và cho vay các tổ chức tín dụng...
line 374  tổng: 104.411.120
line 375    Tiền gửi tại các TCTD khác: 59.469.540
line 377  tổng năm trước: 105.588.516
line 378    Tiền gửi tại các TCTD khác: 49.847.544

line 384  Cho vay khách hàng
line 386  tổng: 377.113.195
line 387    Cho vay khách hàng: 381.972.016
line 389  tổng năm trước: 318.316.079
line 390    Cho vay khách hàng: 324.009.713
```

Các giá trị cha/con được giữ riêng, không phát sinh semantic conflict. Direct production evaluation của VIB:

- B02: pair match `1.0`;
- B03: pair match `1.0`;
- tổng issue: `0`;
- `review_required` còn lại ở B01 chỉ do current coverage `93.10%`, không do nhầm giá trị.

## Kết quả sau khi sửa

### Kiểm thử

```text
119 passed
```

Các test bao phủ:

- kế thừa period/unit qua wrapper;
- repeated label parent/child;
- structural context collision;
- B02 period-scope ambiguity;
- B03 indent guard;
- form-code disambiguation;
- source-line provenance correction.

### Production audit v9

```text
57/57 files processed
source hash matches: 57/57
```

Numeric pair match theo statement:

| Statement | Matched / expected | Tỷ lệ |
|---|---:|---:|
| B01 | 5308 / 5450 | 97.3945% |
| B02 | 2308 / 2318 | 99.5686% |
| B03 | 2592 / 2774 | 93.4391% |

`review_required` vẫn được giữ ở các file có missing coverage, formula failure, nguồn mơ hồ hoặc schema gap. Đây là chủ ý của production gate: không biến dữ liệu thiếu thông tin thành kết quả có vẻ hợp lệ.

## Phân loại để báo cáo

| Nhóm | Ví dụ | Kết luận |
|---|---|---|
| Parser bug đã sửa | BSI B03, giá trị cha bị gán cho dòng `08 Dự thu tiền lãi` | Lỗi parser; đã sửa bằng hierarchy/indent context và regression test |
| Parser bug đã sửa | VCB/BSI repeated label parent-child | Lỗi thiếu structural context; đã tách bằng hierarchy path/source context |
| Source ambiguity | VCB B02 quý và lũy kế cùng nhãn | Không kết luận sai; ghi `period_scope_ambiguity` để review |
| Source thiếu nhãn | VCB dòng con không có child label | Không được đoán; giữ review/source-only |
| Schema gap | BSI B03 form code `103` | Không fuzzy-map; giữ unmapped/source-only |
| Coverage gate | VIB B01 coverage 93.10% | Không có conflict; cần bổ sung mapping/ground-truth hoặc chấp nhận review |

## Vị trí triển khai chính

- `src/common/source_recovery.py`: dựng và gắn `parent_context`, `hierarchy_path`, sửa provenance.
- `src/common/source_canonical_hydrator.py`: phân loại source ambiguity và sign-equivalent.
- `flat_parser/alias_matcher.py`: dùng parent/ancestor context để phân biệt repeated label.
- `flat_parser/canonical_mapper.py`: phân biệt semantic conflict thật với structural context collision.
- `src/b03_cashflow/extractor.py`: guard indent/pending state và form-code-safe extraction.

