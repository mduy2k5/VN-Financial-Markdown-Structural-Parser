# Restructure Financial Statement LLM Result — Financial Statement Parser

Hệ thống bóc tách, chuẩn hóa ngữ nghĩa và hợp nhất toàn diện 3 Báo cáo Tài chính: **Bảng Cân đối Kế toán (Financial Position)**, **Báo cáo Kết quả Hoạt động Kinh doanh (Income Statement)** và **Báo cáo Lưu chuyển Tiền tệ (Cash Flow Statement)** từ các tệp BCTC định dạng Markdown của các công ty niêm yết tại Việt Nam.

Phiên bản hiện tại: **Release v22.2** — Đạt độ chính xác tuyệt đối **171 / 171 Báo cáo (100.0% Pass Rate)** trên toàn bộ tập dữ liệu 57 doanh nghiệp.

## 1. Tuân Thủ Chuẩn Mực Kế Toán Pháp Định

Hệ thống được thiết kế hoàn toàn dựa trên các thông tư chuẩn hóa quốc gia của Bộ Tài chính và Ngân hàng Nhà nước Việt Nam, **tuyệt đối không áp dụng cơ chế hardcode/ghi đè riêng lẻ** cho từng tệp dữ liệu:

- **Thông tư 200/2014/TT-BTC:** Dành cho Khối Doanh nghiệp sản xuất, xây dựng, thương mại và dịch vụ (`enterprise`).
- **Thông tư 49/2014/TT-NHNN:** Dành cho Khối Ngân hàng thương mại và Tổ chức tín dụng (`bank`).
- **Thông tư 334/2016/TT-BTC:** Dành cho Khối Công ty Chứng khoán (`securities`).
- **Thông tư 199/2014/TT-BTC:** Dành cho Khối Doanh nghiệp / Tập đoàn Bảo hiểm (`insurance`).

## 2. Kết Quả Thực Nghiệm So Với Ground Truth (Release v22.2)

Hệ thống được kiểm định và đối soát chéo độc lập với 57 tệp baseline Ground Truth (`ground_truth/*.baseline.json`):

| Báo Cáo Tài Chính | Trạng Thái Pass Rate | Số Dòng Chuẩn Hóa | Tỷ Lệ Khớp Dòng |
| :--- | :---: | :---: | :---: |
| **Bảng Cân Đối Kế Toán (Financial Position)** | **57 / 57 OK (100.0%)** | 100% Statutory Nodes | **100.00%** |
| **Báo Cáo Kết Quả KD (Income Statement)** | **57 / 57 OK (100.0%)** | 1.626 / 1.629 dòng | **99.82%** |
| **Báo Cáo Lưu Chuyển Tiền Tệ (Cash Flow)** | **57 / 57 OK (100.0%)** | 1.853 / 1.861 dòng | **99.57%** |
| **TỔNG CỘNG TOÀN BỘ HỆ THỐNG** | **171 / 171 OK (100.0%)** | **3.479 / 3.490 dòng** | **99.79%** |

### Phân Bố Độ Chính Xác theo Nhóm Ngành

| Nhóm ngành | Số tệp | Cân đối KT (FP) | Kết quả KD (Income) | Lưu chuyển tiền tệ (CF) | ĐTB Toàn bộ |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Ngân hàng (Bank)** | 27 tệp | **27/27 OK (100%)** | **27/27 OK** *(99.68%)* | **27/27 OK** *(99.26%)* | **99.64%** |
| **Doanh nghiệp (Enterprise)** | 27 tệp | **27/27 OK (100%)** | **27/27 OK** *(99.88%)* | **27/27 OK** *(99.87%)* | **99.91%** |
| **Chứng khoán (Securities)** | 2 tệp | **2/2 OK (100%)** | **2/2 OK** *(100.0%)* | **2/2 OK** *(100.0%)* | **100.00%** |
| **Bảo hiểm (Insurance)** | 1 tệp | **1/1 OK (100%)** | **1/1 OK** *(100.0%)* | **1/1 OK** *(100.0%)* | **100.00%** |

> **100% (57 / 57 doanh nghiệp)** đều đạt xếp hạng **Xuất sắc ($\ge 98.0\%$)**.

## 3. Cài Đặt & Yêu Cầu Môi Trường

- **Python 3.10 trở lên** (khuyến nghị Python 3.11 hoặc 3.12).
- Cài đặt các thư viện bổ trợ (nếu chạy test suite):

```powershell
python -m pip install -r .\requirements.txt
```

## 4. Hướng Dẫn Sử Dụng (Pipeline Execution)

### 4.1. Chạy Toàn Diện Cả 3 Báo Cáo Tài Chính (Recommended)

Sử dụng `run_income_comparison.py` để tự động nhận diện phạm vi, phân loại ngành (`auto-detect sector`), bóc tách fallback, đối soát và chuẩn hóa cả 3 báo cáo:

```powershell
python .\run_income_comparison.py .\output\md_reports `
  --financial-position-dir .\output\comparisons\comparison_v11 `
  --comparison-dir .\output\comparisons\comparison_v22_2 `
  --output .\output\comparisons\comparison_v22_2 `
  --current-year 2025 `
  --previous-year 2024
```

Kết quả xuất ra gồm:
- Tệp so sánh hợp nhất: `<ticker>.comparison.json`
- Tệp canonical chuẩn hóa từng báo cáo: `<ticker>.financial_position.canonical.json`, `<ticker>.income.canonical.json`, `<ticker>.cashflow.canonical.json`
- Bảng tổng hợp đối soát: `comparison_summary.json` và `comparison_summary.csv`

### 4.2. Chạy Riêng Bảng Cân Đối Kế Toán (B01/B02)

Sử dụng `run.py` để trích xuất Báo cáo Tình hình Tài chính:

```powershell
python .\run.py .\output\md_reports --mode v05 --output .\output\v05
python .\run.py .\output\md_reports --mode flow --output .\output\flow
python .\run.py .\output\md_reports --mode hybrid --output .\output\hybrid
python .\run.py .\output\md_reports --mode compare --output .\output\compare
```

### 4.3. Chạy Độc Lập Bộ Ánh Xạ Kết Quả Kinh Doanh (Standalone Income Mapper)

Khi đầu vào là các dòng đã trích xuất sẵn dạng JSON/CSV:

```powershell
python .\run_income_map.py .\rows `
  --sector auto `
  --output .\output\income_map `
  --current-year 2025 `
  --previous-year 2024
```

## 5. Cấu Trúc Mã Nguồn (Repository Layout)

Kho mã nguồn đã được tinh giản và tái cấu trúc sạch sẽ:

```text
Flatten/
├── flat_parser/               # Engine trích xuất cấu trúc Bảng CĐKT (v0.5, flow, hybrid)
├── ground_truth/              # Bộ dữ liệu 57 tệp baseline Ground Truth độc lập
├── output/                    # Kết quả chạy và dữ liệu nguồn (đã được cấu hình trong .gitignore)
│   ├── md_reports/            # 57 tệp BCTC gốc định dạng Markdown
│   ├── comparisons/
│   │   ├── comparison_v11/    # Bridge dữ liệu cho Financial Position
│   │   └── comparison_v22_2/  # Kết quả phát hành chính thức mới nhất
│   └── evaluations/           # Nhật ký đánh giá lịch sử
├── resources/                 # Nguồn sự thật duy nhất (Single Source of Truth) cho Schemas & Aliases
│   ├── cash_flow_schema.json & cash_flow_aliases.json
│   ├── financial_position_schema.json & financial_position_aliases.json
│   ├── income_statement_schema.json & income_statement_aliases.json
│   └── guides/                # Hướng dẫn nhận diện cấu trúc theo từng nhóm doanh nghiệp
├── samples/                   # Mẫu dữ liệu test an toàn
├── scripts/                   # Script tiện ích xây dựng guide và báo cáo độ phủ
├── tests/                     # Bộ kiểm thử đơn vị hồi quy (20 test suites)
├── src/                       # [Core Business Logic] Thư mục chứa các module con & tiện ích
│   ├── income_mapper.py           # Engine ánh xạ Kết quả Hoạt động Kinh doanh
│   ├── income_observation_patch.py# Bộ trích xuất & làm sạch fallback Kết quả KD
│   ├── cashflow_mapper.py         # Engine ánh xạ Lưu chuyển Tiền tệ
│   ├── cashflow_observation_patch.py # Bộ trích xuất & nhận diện phương pháp LCTT (Trực tiếp / Gián tiếp)
│   ├── financial_position_bridge.py # Cầu nối tích hợp dữ liệu Bảng CĐKT
│   ├── period_identity_repair.py  # Sửa lỗi nhận diện niên độ và cột thời gian
│   ├── source_observation_layer.py# Tầng quan sát dữ liệu gốc
│   ├── source_reconciliation.py   # Cơ chế đối soát và bảo toàn giá trị gốc
│   ├── source_statement_recovery.py # Khôi phục dòng chỉ tiêu bị sót từ bảng biểu
│   └── analyze_income_summary.py  # Công cụ phân tích phân loại lỗi từ summary
├── run_income_comparison.py   # [Main Runner] Entry point chính chạy hợp nhất cả 3 BCTC
├── run_income_map.py          # Standalone runner cho mapper KQKD
├── run.py & run_ab.py         # Shortcut CLI cho flat_parser
├── run_parser.ps1 & run_integrated.ps1 # PowerShell runners tiện ích
├── VERSION.txt                # Phiên bản hiện tại (v22.2)
└── README.md                  # Tài liệu hướng dẫn chính của dự án
```

## 6. Kiểm Thử & Xác Minh (Testing)

Kiểm tra cú pháp và tính toàn vẹn của toàn bộ repository (không cần cài thêm thư viện ngoài):

```powershell
python -m compileall -q .
```

Chạy bộ kiểm thử đơn vị với pytest:

```powershell
python -m pytest -q
```
