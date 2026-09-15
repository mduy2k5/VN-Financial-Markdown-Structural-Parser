# VN-Financial-Markdown-Structural-Parser

Hệ thống bóc tách, chuẩn hóa ngữ nghĩa và hợp nhất toàn diện 3 Báo cáo Tài chính: **Bảng Cân đối Kế toán (Financial Position)**, **Báo cáo Kết quả Hoạt động Kinh doanh (Income Statement)** và **Báo cáo Lưu chuyển Tiền tệ (Cash Flow Statement)** từ dữ liệu BCTC định dạng Markdown do các mô hình LLM/OCR quét từ tài liệu PDF của các công ty niêm yết tại Việt Nam.

Phiên bản phát hành: **Release v23.0.0** — **Notes Scope & Coverage Patch**: Đạt tỷ lệ phát hiện phạm vi Thuyết minh BCTC **57/57 tệp (100.0%)** trên toàn bộ corpus tham chiếu chính thức. Giữ vững **171 / 171 primary statements đạt tiêu chuẩn release** (B01, B02, B03), nguyên tắc `PRIMARY > NOTES` bảo toàn $100\%$ không gây hồi quy (Zero Regression), độ chính xác khớp dòng đạt **99.80%** (3.398/3.408 dòng) và **100.0%** (406/406 dòng trên bộ 3 tệp kiểm thử mở rộng BID, FPT, VNM).

## 1. Bản Chất Input Đầu Vào & Thách Thức Xử Lý Dữ Liệu LLM-OCR

### 1.1. Nguồn Gốc & Bối Cảnh Đầu Vào (Input Origin)

Trong các hệ thống phân tích tài chính hiện đại (FinTech, RAG Pipeline, Quantitative Modeling), việc số hóa hàng triệu trang tài liệu Báo cáo Tài chính (BCTC) kiểm toán định dạng PDF là bước khởi đầu bắt buộc. Dữ liệu đầu vào của dự án (`md_reports/*.md`) xuất phát từ quy trình:

```text
[BCTC PDF Gốc (Scan/Vector)]
         │
         ▼
[Mô hình Vision-LLM / Document AI (Gemini Vision, GPT-4o, MinerU, Nougat, Docling)]
         │
         ▼
[Tệp Markdown Thô (.md) lưu trữ tại S3 Data Lake (raw-data/du-lieu-co-phieu-production/...)]
```

Mỗi tệp Markdown đầu vào mang theo metadata từng trang (`page`, `s3_key`, `year`, `symbol`, `page_ocr_status`) cùng phần nội dung text Markdown (`## Content`) được mô hình AI tái tạo lại từ hình ảnh trang sách.

### 1.2. Các Dị Tật Cấu Trúc Của Dữ Liệu Markdown Thô

Mặc dù các mô hình Vision-LLM thế hệ mới có năng lực nhận dạng chữ rất cao, nhưng khi đối mặt với bảng biểu tài chính nhiều cột, nhiều cấp chỉ tiêu và ngắt trang liên tục, dữ liệu Markdown đầu ra thường xuyên gặp các lỗi cấu trúc nghiêm trọng:

1. **Thoái hóa cấu trúc bảng (Table Degeneration into Bullet Points):**
   Rất nhiều trang BCTC bị mô hình LLM phân rã hoàn toàn khỏi định dạng bảng (`| col1 | col2 |`) thành danh sách gạch đầu dòng lồng nhau sâu 3-5 cấp (điển hình tại ACB, HPG). Ví dụ:
   ```markdown
   *   **I. Tiền mặt, vàng bạc, đá quý**
       *   Thuyết minh: 4
       *   Tại ngày 31.12.2025: 8.624.548 triệu VND
       *   Tại ngày 31.12.2024: 5.696.449 triệu VND
   ```

2. **Đứt gãy liên kết Nhãn - Số liệu (Label & Value Decoupling):**
   Khi một bảng biểu trải dài qua nhiều cột hoặc bị ngắt trang, LLM thường xuất toàn bộ tên chỉ tiêu ra dạng văn bản tự do ở phía trên, sau đó kẻ một bảng Markdown riêng biệt ở phía dưới chỉ gồm `Mã số` và các con số tiền mà không có nhãn. Parser thông thường hoàn toàn bất lực trước hiện tượng này.

3. **Gãy dòng văn bản do OCR (Line-Wrapping & Text Splits):**
   Do độ rộng trang in giới hạn, tên chỉ tiêu kế toán dài bị ngắt đôi xuống dòng, khiến các công cụ bóc tách nhầm lẫn dòng thứ hai là một mục mới hoặc làm thất lạc mã số chỉ tiêu.

4. **Hỗn loạn định dạng số học và quy ước kế toán:**
   - Số âm kế toán viết trong ngoặc đơn: `(163.476)` hoặc `(7.624.729)`.
   - Giá trị rỗng hoặc bằng 0 thể hiện bằng dấu gạch ngang: `-` hoặc `—`.
   - Đơn vị tiền tệ bị ghép trực tiếp vào số: `8.624.548 triệu VND`.

5. **Xung đột mã số biểu mẫu và thuật ngữ đồng nghĩa:**
   Các ngân hàng thương mại tái sử dụng cùng mã số (như mã `01`, `02`) qua từng bảng biểu nghiệp vụ khác nhau; các doanh nghiệp sử dụng các cách diễn đạt tương đương đa dạng.

### 1.3. Yêu Cầu Đặt Ra Cho Hệ Thống Chuẩn Hóa

Để dữ liệu này có thể sử dụng được cho phân tích định lượng, thuật toán hoặc lưu trữ cơ sở dữ liệu quan hệ, hệ thống bóc tách phải đáp ứng:
- **Chuẩn hóa cấu trúc (Canonical Schema):** Chuyển đổi mọi định dạng (bảng, bullet, text) về một cấu trúc phẳng hoặc cây chuẩn mực thống nhất.
- **Làm sạch số học (Numeric Standardization):** Chuyển đổi toàn bộ chuỗi số về giá trị thực (`float`), phục hồi đúng dấu âm cho các chỉ tiêu trong ngoặc đơn, chuẩn hóa đơn vị về đồng bộ.
- **Nhận diện niên độ thông minh:** Tự động phát hiện niên độ báo cáo (`current_year`, `previous_year`) dựa trên tiêu đề cột biến thiên theo thời gian.
- **Bảo tồn tính vẹn toàn kiểm toán (Auditability & Provenance):** Lưu giữ nguồn gốc truy vết (`source_line`, `raw_text`), bảo đảm giá trị số không bị "bịa đặt" hay làm sai lệch (`canonical_mutated: false`).

## 2. Tại Sao Dự Án Của Chúng Ta Là Giải Pháp Tối Ưu?

### 2.1. Giới Hạn Của Việc Tiếp Tục Dùng Prompt LLM Trực Tiếp

Nhiều giải pháp tiếp cận bằng cách gửi tiếp toàn bộ Markdown thô cho một mô hình LLM với prompt yêu cầu "hãy xuất ra JSON chuẩn". Cách làm này gặp phải các tử huyệt trong môi trường tài chính chuyên nghiệp:
- **Ảo giác số liệu (Hallucination):** LLM sinh chữ theo xác suất nên có thể tự ý làm tròn, làm rớt dấu trừ hoặc bịa số khi dòng biểu bị mờ/khuyết.
- **Chi phí đắt đỏ & Độ trễ cao:** Một bộ BCTC đầy đủ dài từ 50 đến 100 trang. Việc gọi LLM API qua hàng trăm trang tiêu tốn chi phí token rất lớn.
- **Thiếu tính tất định (Non-deterministic):** Cùng một tệp BCTC, hai lần gọi LLM khác nhau có thể trả về hai cấu trúc JSON khác nhau, không thể đưa vào quy trình kiểm toán tự động.

### 2.2. Kiến Trúc Hybrid Của Tool: Rule-Based Deterministic + Semantic Layer

Công cụ của chúng ta giải quyết triệt để bài toán này bằng kiến trúc kết hợp:
1. **Multi-Strategy Parser Engine:** Vừa hỗ trợ trích xuất bảng kẻ viền (Table Mode), vừa xử lý danh sách bullet phân cấp (Bullet Hierarchy Mode), vừa có bộ quét dòng tự do dựa trên biểu thức chính quy (Regex Fallback Mode).
2. **Observation & Patch Layer:** Tự động nhận diện cấu trúc, phát hiện bảng bị phân mảnh và tự động hàn gắn dòng chữ bị ngắt đôi.
3. **Single Source of Truth (Schemas & Aliases):** Bộ quy chuẩn ngữ nghĩa bao phủ 4 thông tư kế toán pháp định của Việt Nam với hơn 1.000 alias thực tế.
4. **Bảo tồn nguyên bản & Kiểm toán được (Audit-ready):** Mọi con số đều được ánh xạ trực tiếp từ dòng text gốc kèm số dòng (`source_line`), tuyệt đối không nội suy số liệu.

## 3. Bằng Chứng Thực Nghiệm & Kết Quả Đối Soát (Ground Truth Benchmark)

### 3.1. Bảng Tổng Hợp Độ Phủ Toàn Hệ Thống (Release v22.4.2)

| Báo Cáo Tài Chính | Số Báo Cáo Đạt Chuẩn | Tỷ Lệ Pass Rate | Số Dòng Khớp Thực Tế | Tỷ Lệ Khớp Dòng |
| :--- | :---: | :---: | :---: | :---: |
| **Bảng Cân Đối Kế Toán (Financial Position)** | **57 / 57 Báo cáo** | **100.0%** | 100% Statutory Nodes | **100.00%** |
| **Báo Cáo Kết Quả KD (Income Statement)** | **57 / 57 Báo cáo** | **100.0%** | 1.607 / 1.610 dòng | **99.81%** |
| **Báo Cáo Lưu Chuyển Tiền Tệ (Cash Flow)** | **57 / 57 Báo cáo** | **100.0%** | 1.791 / 1.798 dòng | **99.61%** |
| **TỔNG CỘNG TOÀN BỘ HỆ THỐNG** | **171 / 171 Báo cáo** | **100.0%** | **3.398 / 3.408 dòng** | **99.80%** |

### 3.2. Phân Bố Theo Khối Ngành & Chuẩn Mực Kế Toán

| Khối Ngành | Chế Độ Kế Toán | Số Tệp | Cân Đối KT | Kết Quả KD | Lưu Chuyển TT |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Doanh nghiệp** | Thông tư 200/2014/TT-BTC | 27 | 27/27 OK | 27/27 OK | 27/27 OK |
| **Ngân hàng** | TT 49/2014 & TT 27/2021 | 27 | 27/27 OK | 27/27 OK | 27/27 OK |
| **Chứng khoán** | Thông tư 334/2016/TT-BTC | 2 | 2/2 OK | 2/2 OK | 2/2 OK |
| **Bảo hiểm** | Thông tư 199/2014/TT-BTC | 1 | 1/1 OK | 1/1 OK | 1/1 OK |

## 4. Cấu Trúc Mã Nguồn (Repository Layout)

```text
Flatten/
├── pipeline.py                        # [Entry Point] Pipeline thống nhất 3 BCTC + Thuyết minh (Notes IR)
├── run_debug.py                       # [Debug Tool] CLI cho flat_parser (FP only, A/B compare)
├── run_notes.py                       # [Notes Tool] CLI độc lập cho subsystem Thuyết minh BCTC
│
├── src/                               # [Core Business Logic]
│   ├── notes/                         # [Subsystem] Trích xuất & cấu trúc Thuyết minh BCTC (Generic Note IR)
│   ├── value_semantics.py             # Nhận diện & kế thừa đơn vị tính toàn diện (Unit Propagation)
│   ├── income_mapper.py               # Engine ánh xạ Kết quả Hoạt động Kinh doanh
│   ├── income_formula_validation.py   # Kiểm toán dấu kế toán & công thức 4 ngành KQKD
│   ├── income_observation_patch.py    # Fallback & hàn gắn ngắt dòng KQKD
│   ├── income_scope_selector.py       # Định vị phạm vi & xếp hạng ứng viên BCTC KQKD
│   ├── cashflow_mapper.py             # Engine ánh xạ Lưu chuyển Tiền tệ
│   ├── cashflow_observation_patch.py  # Phân loại LCTT (Trực tiếp / Gián tiếp)
│   ├── financial_position_bridge.py   # Cầu nối tích hợp Bảng CĐKT
│   ├── pipeline_metrics.py            # Tính toán metrics, tỷ lệ phủ & chất lượng bóc tách
│   ├── period_identity_repair.py      # Sửa lỗi nhận diện niên độ
│   ├── source_observation_layer.py    # Tầng quan sát dữ liệu gốc
│   ├── source_reconciliation.py       # Đối soát và bảo toàn giá trị gốc
│   ├── source_statement_recovery.py   # Khôi phục dòng bị phân mảnh
│   ├── source_canonical_hydrator.py   # Đối soát, bù đắp mã số biểu mẫu & hợp nhất canonical
│   └── analyze_income_summary.py      # Phân tích và phân loại điểm sai lệch
│
├── flat_parser/                       # Engine trích xuất cấu trúc Bảng CĐKT
│   ├── runner_cli.py                  # Unified CLI (v05 / flow / hybrid / compare modes)
│   ├── bullet_flow.py                 # P1-P34 structural patterns (BulletDebugFlow)
│   ├── integrated_pipeline.py         # Engine v05 (2-pass semantic tree)
│   ├── flow_mapped_pipeline.py        # Engine flow (pure P1-P34)
│   ├── bullet_mapped_pipeline.py      # Engine hybrid (v05 + flow fill)
│   └── ...                            # Các module hỗ trợ (alias_matcher, pipeline, qa, ...)
│
├── resources/                         # Single Source of Truth — Schema & Aliases
│   ├── universal_financial_position_schema_v1_6.json
│   ├── universal_financial_position_aliases_v1_6_1.json
│   ├── universal_off_balance_bank_schema_v1_3.json
│   ├── universal_off_balance_bank_aliases_v1_3.json
│   ├── income_statement_schema.json
│   ├── income_statement_aliases.json
│   ├── cash_flow_schema.json
│   ├── cash_flow_aliases.json
│   └── universal_structural_guide_a1_a5.json
│
├── md_reports/                        # [Input] 57 tệp BCTC Markdown từ Vision-LLM
├── output/                            # [Output] Kết quả chuẩn hóa và đối soát
├── ground_truth/                      # 57 tệp baseline Ground Truth
├── evaluation_57/                     # Báo cáo đánh giá phạm vi & độ phủ Thuyết minh 57 BCTC
├── tests/                             # Unit tests hiện hành
│   └── legacy/                        # Tests v0.4.x (archived)
├── samples/                           # Dữ liệu mẫu kiểm thử
├── scripts/                           # Script tiện ích
│   ├── rebuild_universal_guide.py
│   ├── rebuild_guide.ps1
│   ├── build_coverage_report.py
│   └── evaluate_notes_coverage.py     # Đánh giá inventory & độ phủ Thuyết minh trên 57 BCTC
│
├── README.md
├── VERSION.txt
└── requirements.txt
```

## 5. Cài Đặt & Môi Trường

- **Yêu cầu Python:** Python 3.10 trở lên (khuyến nghị Python 3.11 hoặc 3.12).
- **Hệ điều hành:** Độc lập nền tảng (Windows, macOS, Linux).

```powershell
python -m pip install -r .\requirements.txt
```

## 6. Hướng Dẫn Sử Dụng

### 6.1. Pipeline Thống Nhất Cả 3 Báo Cáo (Production)

```powershell
python .\pipeline.py .\md_reports `
  --financial-position-dir .\output\comparisons\comparison_v11 `
  --comparison-dir .\output\comparisons\comparison_v22_2 `
  --output .\output\comparisons\comparison_v22_2 `
  --current-year 2025 `
  --previous-year 2024
```

Kết quả xuất ra gồm:
- `<ticker>.comparison.json` — Hợp nhất cả 3 BCTC
- `<ticker>.financial_position.canonical.json`
- `<ticker>.income.canonical.json`
- `<ticker>.cashflow.canonical.json`
- `comparison_summary.json` + `comparison_summary.csv`

### 6.2. Debug / Phân Tích Riêng Bảng CĐKT

```powershell
# Chạy engine hybrid (mặc định, Production)
python .\run_debug.py .\md_reports --mode hybrid --output .\output\hybrid

# So sánh 3 engine (debug)
python .\run_debug.py .\md_reports --mode compare --output .\output\compare

# Chạy từng engine độc lập
python .\run_debug.py .\md_reports --mode v05 --output .\output\v05
python .\run_debug.py .\md_reports --mode flow --output .\output\flow
```

Các tùy chọn nâng cao:
```powershell
# Bật regex fallback cho alias matching
python .\run_debug.py .\md_reports --mode hybrid --regex-fallback --output .\output

# So sánh mapping strategy: legacy vs regex
python .\run_debug.py .\md_reports --mode mapping-compare --output .\output\mapping_compare

# So sánh legacy vs alias+regex-fallback
python .\run_debug.py .\md_reports --mode fallback-compare --output .\output\fallback
```

### 6.3. Build lại Universal Guide

```powershell
.\scripts\rebuild_guide.ps1
```

## 7. Cấu Trúc Dữ Liệu Đầu Ra (Canonical Output)

Mỗi chỉ tiêu trong tệp `.canonical.json` tuân thủ cấu trúc minh bạch, sẵn sàng phục vụ kiểm toán:

```json
{
  "code": "IS_01",
  "name_vi": "Doanh thu bán hàng và cung cấp dịch vụ",
  "value_current": 140558000000.0,
  "value_previous": 120412000000.0,
  "unit": "VND",
  "source_line": 352,
  "raw_text": "1. Doanh thu bán hàng và cung cấp dịch vụ: 140.558 (2025) / 120.412 (2024)",
  "canonical_mutated": false
}
```

- `source_line`: Vị trí dòng chính xác trong tệp Markdown nguồn — cho phép kiểm toán đối chiếu trực tiếp.
- `canonical_mutated: false`: Giá trị nguyên bản 100% từ tài liệu gốc, không nội suy.

## 8. Kiểm Thử & Đảm Bảo Chất Lượng

```powershell
# Kiểm tra cú pháp toàn bộ repo
python -m compileall -q .

# Chạy unit tests
python -m pytest tests/ -q
```