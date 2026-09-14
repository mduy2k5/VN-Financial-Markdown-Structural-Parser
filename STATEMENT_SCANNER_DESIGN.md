# Statement Scanner / Router v0.5.0

## Mục tiêu

Không dùng alias business để mở scope. Scanner quyết định trước:

```text
Markdown
  -> lexical/noise normalization
  -> document sector detector
  -> statement scanner
  -> statement ranges
       FINANCIAL_POSITION
       OFF_BALANCE
       INCOME_STATEMENT
       CASH_FLOW
       NOTES
  -> resource router
       FINANCIAL_POSITION -> B02/B01 universal resources
       OFF_BALANCE(bank) -> OFF_BALANCE Alias Pack v1.3
  -> existing structural engine
```

## Vì sao không dựa vào mã mẫu đơn lẻ

Mã biểu mẫu phụ thuộc sector/chế độ kế toán. Vì vậy form code chỉ là một tín hiệu hỗ trợ.
Scanner kết hợp:

1. tiêu đề bảng;
2. sector/issuer identity;
3. sector-specific form code;
4. statement signature;
5. period/value shape;
6. TOC/reference negative evidence;
7. vị trí tương đối giữa các statement.

## Sector detector

Ưu tiên bằng chứng mạnh ở front matter:

- TCTD: B02/B03/B04/B05-TCTD, tên ngân hàng/TCTD;
- CTCK: B01-CTCK và issuer identity là công ty chứng khoán;
- insurance: issuer identity + vocabulary đặc thù;
- nếu chỉ có từ "ngân hàng" hay "VSDC" trong thuyết minh thì không đủ đổi sector.

Điều này tránh doanh nghiệp thường bị nhận nhầm là bank vì có khoản vay ngân hàng, hoặc ngân hàng bị nhận nhầm là securities vì có nghiệp vụ lưu ký.

## Statement signatures

### FINANCIAL_POSITION

- Tài sản / Tài sản Có
- Nợ phải trả
- Vốn chủ sở hữu
- Tổng tài sản / Tổng nguồn vốn
- kỳ tại một thời điểm

Start detector kế thừa `v0.4.14` vì đã có regression TOC/continuation/signature recovery.

### OFF_BALANCE

- heading ngoại bảng;
- cluster các anchor bảo lãnh/cam kết/hối đoái/L/C/nợ khó đòi;
- point-in-time period shape;
- bank resource chỉ được route khi document sector = bank.

### INCOME_STATEMENT

- Báo cáo kết quả hoạt động (kinh doanh)
- doanh thu/lợi nhuận hoặc thu nhập lãi/chi phí lãi
- period-flow columns

### CASH_FLOW

- Báo cáo lưu chuyển tiền tệ
- lưu chuyển tiền thuần theo hoạt động
- tiền và tương đương tiền đầu/cuối kỳ

### NOTES

- Thuyết minh báo cáo tài chính
- scanner chỉ dùng để đóng range, chưa parse ở v0.5.0.

## Routing policy

v0.5.0 parse hai sub-statements:

```text
FINANCIAL_POSITION -> universal_financial_position_schema_v1_6
OFF_BALANCE(bank)  -> universal_off_balance_bank_schema_v1_3
```

Income/Cash Flow được detect nhưng trả `detected_not_enabled` cho tới khi có schema/aliases riêng.

OFF_BALANCE không tham gia balance identity.

## Failure separation

```text
statement not detected
  -> scanner/scope problem

statement detected, alias unknown
  -> alias/schema problem

alias matched, no payload
  -> structural/collector problem

multiple payload for same period
  -> source ambiguity / collector boundary review
```
