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
| Regression suite | **77 passed** | Kiểm thử tự động hiện hành |

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
Production report JSON + batch manifest
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

Mặc định, pipeline chỉ sinh output dành cho downstream consumer:

```text
output/current/
├── manifest.json
└── reports/
    ├── <source-stem>__<sha256-prefix>.json
    └── ...
```

`manifest.json` là chỉ mục batch, chứa schema version, số lượng báo cáo, source hash, kỳ báo cáo và đường dẫn tương đối tới từng report. Tên report lấy từ tên file Markdown đã chuẩn hóa, kèm hậu tố hash để tránh trùng; không cần mở manifest vẫn có thể nhận diện nguồn. Mỗi report JSON có cùng contract gồm `report`, `periods`, `statements`, `notes` và `quality`. Các mảng lồng nhau được lưu dưới dạng JSON native; giá trị số được chuẩn hóa thành number hoặc `null`.

Các parser diagnostics, mapping score, raw IR và bảng so sánh không nằm trong output production. Khi cần đánh giá hoặc điều tra, bật profile audit:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --notes `
  --audit
```

Khi đó artifact giàu thông tin được đặt riêng dưới `output/current/audit/` (`*.canonical.json`, `*.comparison.json`, `notes_rows/`, `comparison_summary.*`, `run_metadata.json`). Đây là lớp phục vụ review/evaluation, không phải contract dữ liệu chính.

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
  --current .\output\current\audit `
  --ground-truth-mode eligible `
  --sources .\md_reports `
  --report .\output\main_statement_comparison.json
```

`raw` giữ mọi observation trong baseline; `eligible` loại observation mơ hồ hoặc cần review khỏi chỉ số chính. Comparator so sánh evidence chuẩn hóa `label + period + value`, tách `missing` và `unexpected`, đồng thời kiểm tra source hash.

Ground truth là công cụ đánh giá, không phải input runtime. Baseline chưa được human-review không nên được diễn giải như gold standard tuyệt đối.

## Production schema và provenance

Ví dụ rút gọn:

```json
{
  "output_schema": {"name": "vn_financial_report_output", "version": "1.0.0"},
  "report": {"id": "r_<sha256-prefix>", "source_name": "<report>.md", "source_sha256": "<sha256>"},
  "periods": {
    "current": {"year": 2025, "start_date": null, "end_date": "2025-12-31"},
    "previous": {"year": 2024, "start_date": null, "end_date": "2024-12-31"}
  },
  "statements": {
    "income_statement": {
      "nodes": [
        {
          "node_id": "INCOME.ENTERPRISE.NET_REVENUE",
          "canonical_name": "Doanh thu thuần",
          "value": {"current": 1000, "previous": 900, "additional": null, "note": null, "unit": null},
          "evidence": [{"source_line": 42, "confidence": 1.0}]
        }
      ],
      "observations": []
    }
  },
  "quality": {"status": "ok", "issues": []}
}
```

`observations` giữ bằng chứng nguồn chưa đủ điều kiện map vào semantic node; chúng có identity riêng và không được dùng như khóa nghiệp vụ. `source_name`, `source_sha256`, `source_line`, `source_label` và `confidence` là provenance gọn để truy ngược Markdown. Parser không đọc output hoặc ground truth của lần chạy trước để bổ sung dữ liệu.

Để xem đầy đủ trường nội bộ phục vụ đánh giá, đọc các artifact trong `audit/`; không dùng chúng làm interface downstream ổn định.

Ví dụ giá trị trong report production:

```json
{
  "node_id": "INCOME.ENTERPRISE.NET_REVENUE",
  "canonical_name": "Doanh thu thuần",
  "value": {"current": 1000, "previous": 900},
  "evidence": [{"source_line": 42, "confidence": 1.0}]
}
```

Parser chuẩn hóa dấu âm, dấu phân cách và unit nhưng không nội suy số liệu. Khi kỳ/năm có xung đột, `quality.status` là `review_required` và evidence được giữ lại thay vì ghi đè.

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
2. Kiểm tra `manifest.json` và report tương ứng trong `reports/`.
3. Nếu cần đối chiếu baseline, chạy lại với `--audit` và dùng artifact dưới `audit/`.
4. Đối chiếu ở chế độ `eligible` để phát hiện `missing`/`unexpected`.
5. Mở review queue, kiểm tra `raw_text`, `source_line`, period và conflict.
6. Chỉ dùng production output cho kết luận nghiệp vụ sau khi các conflict trọng yếu được xác nhận.

Các báo cáo có `partial_mapping`, `partial_source_coverage`, confidence thấp hoặc conflict niên độ cần được đánh dấu review.

## Phiên bản

Phiên bản parser được ghi trong `VERSION.txt`. Repository này lưu code, schema, guide, test và script đánh giá; dữ liệu nguồn và output cục bộ không thuộc release artifact.
