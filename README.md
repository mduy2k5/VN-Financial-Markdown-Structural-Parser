# VN-Financial-Markdown-Structural-Parser

> Parser deterministic, source-first để đọc báo cáo tài chính tiếng Việt ở dạng Markdown và xuất dữ liệu chuẩn hóa thành JSON có provenance.

## Mục tiêu

Pipeline hiện tại xử lý độc lập bốn lớp dữ liệu:

- **B01 — Financial Position:** bảng cân đối kế toán.
- **B02 — Income Statement:** báo cáo kết quả hoạt động kinh doanh.
- **B03 — Cash Flow:** báo cáo lưu chuyển tiền tệ.
- **Notes:** thuyết minh, xuất Notes IR và các dòng phẳng để review.

Runtime chỉ đọc Markdown nguồn. Nó không đọc output, ground truth hoặc artifact của lần chạy trước để bổ sung dữ liệu. Không có nhánh xử lý theo tên báo cáo, ticker, giá trị biết trước hay một layout riêng của một file.

## Trạng thái đã kiểm chứng

Snapshot local gần nhất được tạo từ entrypoint hiện tại:

| Hạng mục | Kết quả | Diễn giải |
|---|---:|---|
| Discovery | 57/57 | Tất cả Markdown trong input được chọn để xử lý |
| B01 | 57/57 `ok` | Structural parser và source recovery hoàn tất |
| B02 | 32 `ok`, 25 `partial_mapping` | Một số dòng đọc được nhưng chưa map đủ vào semantic schema |
| B03 | 55 `ok`, 1 `partial_mapping`, 1 `partial_source_coverage` | Còn một số khác biệt về section/layout/phương pháp |
| Notes | 57/57 `parsed` | Lớp bổ sung, không ghi đè primary statements |
| Regression suite | **75 passed** | Kiểm thử tự động hiện hành |

Các số liệu trên là snapshot của một lần chạy, không phải cam kết accuracy tuyệt đối. `partial_mapping` và `partial_source_coverage` là tín hiệu cần review; chúng không có nghĩa toàn bộ báo cáo bị loại bỏ.

## Nguyên tắc thiết kế

### Source-first

Mỗi báo cáo có context riêng gồm cặp kỳ, sector, phạm vi bảng và provenance. Output lưu lại khi có thể:

- `source_name`, `source_sha256`;
- dòng nguồn và `raw_text`;
- phương pháp mapping, confidence và conflict;
- thông tin suy luận `current_year`/`previous_year`.

### Suy luận niên độ theo từng file

Resolver ưu tiên ngày kết thúc kỳ, tiêu đề/cột kỳ và câu dẫn của báo cáo. Năm trong tên file chỉ là bằng chứng phụ trợ. Ngày kiểm toán, ngày phát hành và ngày hành chính được giảm trọng số. Khi có xung đột, parser giữ lại evidence và confidence thay vì tự động ghi đè.

### Không dùng mã làm khóa identity

Mã biểu mẫu và số Thuyết minh chỉ là metadata/provenance. Chúng không được dùng làm khóa join, dedupe, identity hoặc reconciliation. Identity được xác định từ cấu trúc, nhãn, section, period và semantic context.

### Primary statements là nguồn chính

B01, B02 và B03 được parse trực tiếp từ Markdown. Notes có thể link/reconcile với primary khi đủ bằng chứng nhưng không được tự ý thay thế giá trị primary.

## Flow xử lý

```text
Markdown input
    │
    ▼
Discovery + SHA-256 + chuẩn hóa dòng
    │
    ▼
Resolver kỳ/năm và statement scope theo từng báo cáo
    │
    ├── B01: structural recovery → hierarchy → canonical nodes
    ├── B02: scope/sector → row extraction → semantic mapping → validation
    ├── B03: section/method → row extraction → cash-flow mapping
    └── Notes: scope → section/block/table/bullet → Notes IR → row export
    │
    ▼
Source recovery + hydration + reconciliation + provenance
    │
    ▼
Canonical JSON + comparison summary + Notes row export
```

## Các engine

### B01 — Financial Position

B01 xử lý bảng Markdown, dòng bị tách cột và cấu trúc bullet/OCR. Structural core phục hồi section, parent/child, nhãn và hai slot kỳ trước khi ánh xạ sang canonical schema. Source recovery chỉ bổ sung observation có bằng chứng và luôn giữ provenance.

Mã chính nằm trong `src/b01_financial_position/` và `flat_parser/`.

### B02 — Income Statement

B02 xác định scope và sector (`bank`, `enterprise`, `securities`, `insurance`) từ source. Extractor thu dòng từ bảng, bullet hoặc plain OCR; mapper chuẩn hóa nhãn bằng alias và semantic matching có ngưỡng/margin; validator kiểm tra coverage và công thức khi đủ dữ liệu.

`form_code` chỉ được giữ để truy vết, không quyết định identity của dòng.

Mã chính nằm trong `src/b02_income/`.

### B03 — Cash Flow

B03 phát hiện scope, sector và direct/indirect method từ chính phần LCTT. Parser phân biệt statutory section với supplemental/customer/broker section, ghép hai vector kỳ và giữ riêng các dòng có cùng mã nhưng khác ngữ nghĩa.

Mã chính nằm trong `src/b03_cashflow/`.

### Notes

Notes pipeline gồm:

1. `scanner` tìm phạm vi thuyết minh;
2. `sectionizer` chia theo đề mục;
3. `block_classifier` nhận diện bảng, bullet, plain OCR và movement block;
4. `table_parser`/`structural_parser` tách nhãn, hierarchy, unit và period slots;
5. `linker`/`reconciliation` tạo liên kết có provenance;
6. `row_exporter` xuất CSV/JSON để review.

Bullet được đọc như cây: thụt đầu dòng tạo context parent/child, dòng metadata được gắn với node gần nhất, còn dòng kỳ được tách thành giá trị theo period. Parser chỉ ghép các cụm cột khi section, cấu trúc và số lượng slot nhất quán.

Mã chính nằm trong `src/notes/`.

## Cấu trúc repository

```text
Flatten/
├── app/
│   ├── pipeline.py                 # Entry point B01 + B02 + B03 + Notes
│   └── run_notes.py                # CLI riêng cho Notes
├── src/
│   ├── b01_financial_position/
│   ├── b02_income/
│   ├── b03_cashflow/
│   ├── common/                     # Period, recovery, identity, reconciliation
│   └── notes/                      # Notes IR, linking, export
├── flat_parser/                   # Structural core và scanner dùng chung
├── resources/
│   ├── schemas/                    # Schema, aliases và manifest
│   └── guides/                     # Guide nguồn và guide đã biên dịch
├── md_reports/                    # Markdown input cục bộ
├── ground_truth/                  # Baseline, gold/review và reconciliation artifacts
├── output/                        # Output cục bộ; bị Git bỏ qua
├── scripts/
│   ├── ground_truth/              # Build, repair, audit, review
│   ├── evaluation/                # Compare và coverage/quality evaluation
│   └── maintenance/               # Rebuild guide và diagnostics
├── tests/
│   ├── b01/  ├── b02/  ├── b03/
│   ├── notes/  ├── integration/  ├── quality/
│   └── legacy/
├── VERSION.txt
└── requirements.txt
```

## Cài đặt

Yêu cầu Python 3.10 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
```

Runtime parser dùng thư viện chuẩn Python; `requirements.txt` hiện phục vụ test suite.

## Chạy pipeline

Chạy toàn bộ Markdown trong thư mục input và bật Notes:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --notes
```

Tùy chọn thường dùng:

```powershell
# Chỉ chạy ba bảng chính
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --no-notes

# Ép cặp năm cho một lần kiểm thử có kiểm soát
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --current-year 2025 `
  --previous-year 2024 `
  --notes

# Override sector cho B02; B03 vẫn tự phát hiện scope độc lập
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --sector bank `
  --notes
```

Nếu không truyền năm, resolver tự suy luận riêng cho từng file. Nếu input là một file Markdown, pipeline chỉ xử lý file đó.

### Chạy Notes riêng

```powershell
python .\app\run_notes.py .\md_reports `
  --output .\output\notes_current `
  --write-ir
```

## Output

Một lần chạy pipeline tạo cấu trúc tương tự:

```text
output/current/
├── run_metadata.json
├── comparison_summary.json
├── comparison_summary.csv
├── <report>.comparison.json
├── <report>.financial_position.canonical.json
├── <report>.income.canonical.json
├── <report>.cashflow.canonical.json
├── <report>.notes.ir.json
└── notes_rows/
    ├── <report>.notes_rows.csv
    └── <report>.notes_rows.json
```

`run_metadata.json` mô tả input policy và phạm vi batch. `comparison_summary.*` là chỉ mục kết quả theo từng file. Mỗi canonical JSON chứa giá trị, kỳ, source hash và metadata truy vết.

`output/`, `ground_truth/` và `md_reports/` là dữ liệu cục bộ, bị Git bỏ qua để tránh đưa artifact lớn hoặc dữ liệu nguồn lên repository. Có thể tái tạo output từ Markdown bằng entrypoint ở trên.

## Ground truth và đối chiếu

Build Notes ground truth:

```powershell
python .\scripts\ground_truth\build_notes_ground_truth.py `
  .\md_reports `
  --output .\ground_truth\notes
```

Chuẩn bị gold-candidate/review queue cho ba bảng chính:

```powershell
python .\scripts\ground_truth\prepare_main_statement_gold.py `
  --baselines .\ground_truth\main_statements `
  --source-dir .\md_reports `
  --output .\output\main_statement_gold_queue
```

Đối chiếu canonical hiện tại với baseline:

```powershell
python .\scripts\evaluation\compare_main_statement_ground_truth.py `
  --ground-truth .\ground_truth\main_statements `
  --current .\output\current `
  --ground-truth-mode eligible `
  --sources .\md_reports `
  --report .\output\main_statement_comparison.json
```

`raw` giữ mọi observation trong baseline; `eligible` loại observation mơ hồ hoặc cần review khỏi chỉ số chính. Comparator so sánh evidence chuẩn hóa `label + period + value`, tách `missing` và `unexpected`, đồng thời kiểm tra source hash.

Ground truth là công cụ đánh giá, không phải input runtime. Baseline chưa được human-review không nên được diễn giải như gold standard tuyệt đối.

## Canonical schema và provenance

Ví dụ rút gọn:

```json
{
  "statement_type": "INCOME_STATEMENT",
  "periods": {"current": 2025, "previous": 2024},
  "nodes": [
    {
      "node_id": "INCOME.ENTERPRISE.NET_REVENUE",
      "canonical_name": "Doanh thu thuần",
      "value": {"current": 1000, "previous": 900},
      "extraction_meta": {
        "source_line": 42,
        "mapping_method": "exact_alias"
      }
    }
  ],
  "source_name": "<report>.md",
  "source_sha256": "<sha256>"
}
```

Parser chuẩn hóa dấu âm, dấu phân cách và unit nhưng không nội suy số liệu. `source_line`, `raw_text`, occurrence và mapping metadata cho phép quay lại Markdown nguồn.

## Kiểm thử và phát triển

```powershell
python -m pytest -q
python -m compileall -q .
git diff --check
```

Test suite bao phủ structural edge cases, period/year inference, source-only integrity, B01 recovery, B02 semantics, B03 cash-flow fidelity, Notes structural parsing và ground-truth quality.

Khi thêm một parser rule mới:

1. thêm test tái hiện layout/hiện tượng;
2. chứng minh rule dựa trên cấu trúc hoặc semantic context, không dựa trên tên file;
3. kiểm tra provenance và period pairing;
4. chạy toàn bộ regression suite;
5. cập nhật schema/guide nếu thay đổi là tổng quát.

## Quy trình review trước khi dùng nghiệp vụ

1. Chạy pipeline source-first trên Markdown mới.
2. Kiểm tra `run_metadata.json` và `comparison_summary.*`.
3. Đối chiếu ở chế độ `eligible` để phát hiện `missing`/`unexpected`.
4. Mở review queue, kiểm tra `raw_text`, `source_line`, period và conflict.
5. Chỉ dùng canonical output cho kết luận nghiệp vụ sau khi các conflict trọng yếu được xác nhận.

Các báo cáo có `partial_mapping`, `partial_source_coverage`, confidence thấp hoặc conflict niên độ cần được đánh dấu review.

## Phiên bản

Phiên bản parser được ghi trong `VERSION.txt`. Repository này lưu code, schema, guide, test và script đánh giá; dữ liệu nguồn và output cục bộ không thuộc release artifact.
