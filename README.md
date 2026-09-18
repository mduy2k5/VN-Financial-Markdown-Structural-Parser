# VN-Financial-Markdown-Structural-Parser

Parser đọc báo cáo tài chính tiếng Việt từ Markdown và xuất JSON có cấu trúc.

## Mục tiêu

Pipeline xử lý bốn nhóm dữ liệu:

- **B01**: bảng cân đối kế toán.
- **B02**: báo cáo kết quả hoạt động kinh doanh.
- **B03**: báo cáo lưu chuyển tiền tệ.
- **Notes**: phần thuyết minh.

Runtime chỉ đọc Markdown nguồn. Runtime không đọc output, ground truth hoặc dữ liệu của lần chạy trước. Code không chọn logic theo tên file, mã báo cáo, ticker hay giá trị đã biết.

## Kết quả kiểm tra gần nhất

| Hạng mục | Kết quả | Ghi chú |
|---|---:|---|
| Discovery | 57/57 | Pipeline nhận đủ file Markdown trong input. |
| B01 | 57/57 đã chạy | Không có lỗi runtime. Một số conflict vẫn cần review. |
| B02 | 57/57 `ok` | Tỷ lệ map theo dòng: 100%. |
| B03 | 57/57 `ok` | Tỷ lệ map theo dòng: 100%. |
| Notes | 57/57 `parsed` | Notes không ghi đè B01, B02 hoặc B03. |
| Locator | B01: 41/57; B02: 46/57; B03: 44/57 | Chỉ bật khi đủ bằng chứng. File còn lại dùng fallback. |
| Chất lượng batch | 14 `ok`; 43 `review_required` | `review_required` yêu cầu kiểm tra thêm. Đây không phải lỗi runtime. |
| Regression suite | **102 passed** | Kết quả của `python -m pytest -q`. |

Các số liệu trên mô tả một lần chạy. Chúng không phải cam kết accuracy cho mọi nguồn mới.

## Nguyên tắc

### Đọc từ nguồn

Mỗi file có context riêng. Context gồm:

- kỳ hiện tại và kỳ trước;
- sector;
- phạm vi bảng;
- dòng nguồn và provenance.

Parser giữ `raw_text`, `source_line`, confidence và conflict khi có thể.

### Suy luận kỳ và năm

Resolver dùng ngày kết thúc kỳ, tiêu đề, cột kỳ và câu dẫn trong báo cáo. Năm trong tên file chỉ là bằng chứng phụ. Ngày kiểm toán và ngày phát hành có trọng số thấp hơn.

Khi evidence xung đột, parser giữ cả evidence và đặt trạng thái `review_required`. Parser không tự ghi đè dữ liệu.

### Không dùng mã làm khóa

Mã biểu mẫu và số thuyết minh chỉ là metadata. Parser không dùng chúng làm khóa join, identity, dedupe hoặc reconciliation.

Parser dùng cấu trúc, nhãn, section, period và semantic context để xác định một dòng.

### Primary statement là nguồn chính

B01, B02 và B03 đọc trực tiếp từ Markdown. Notes có thể link với primary statement khi có đủ evidence. Notes không thay thế giá trị primary.

## Flow

```text
Markdown
  -> discovery, hash, normalize
  -> resolve period/year
  -> locate candidate statement scope
  -> parse structure and rows
  -> map semantic nodes
  -> validate, reconcile, keep provenance
  -> production JSON and batch manifest
```

### Alias-assisted locator

`StatementLocator` chạy trước parser. Nó dùng alias của B01, B02 và B03 để tìm:

- title hoặc signature của bảng;
- cột kỳ;
- mật độ số;
- các dòng có thể thuộc bảng.

Locator bỏ qua mục lục và vùng thuyết minh không liên quan. Nó trả về `selected_scope` và `candidate_rows`.

Parser chỉ dùng locator khi có đủ ba điều kiện:

1. scope có title evidence;
2. scope mới trùng một phần với scope hiện có;
3. confidence đạt ngưỡng.

Nếu thiếu evidence, pipeline dùng scope cũ và chạy fallback. `candidate_rows` chỉ giúp định tuyến. Parser không dùng chúng để map trực tiếp canonical node.

Audit có thể ghi các trường:

`locator_enabled`, `locator_activated`, `locator_reason`, `locator_confidence`, `locator_alias_hits`, `locator_candidate_rows`.

Các trường này chỉ phục vụ audit. Chúng không nằm trong production contract.

## Các engine

### B01 — Financial Position

B01 xử lý bảng Markdown, dòng tách cột và bullet/OCR.

Engine phục hồi:

- section;
- parent và child;
- label;
- hai slot kỳ.

Sau đó engine map node vào schema. Source recovery chỉ thêm observation có evidence và giữ provenance.

Code chính nằm trong `src/b01_financial_position/` và `flat_parser/`.

### B02 — Income Statement

B02 tìm scope và sector từ source. Extractor đọc bảng, bullet và plain OCR. Mapper dùng alias và semantic matching có threshold và margin. Validator kiểm tra coverage và công thức khi có đủ dữ liệu.

B02 hỗ trợ các sector `bank`, `enterprise`, `securities` và `insurance`.

`form_code` chỉ phục vụ truy vết. Nó không quyết định identity của dòng.

Code chính nằm trong `src/b02_income/`.

### B03 — Cash Flow

B03 tìm scope, sector và phương pháp direct hoặc indirect từ phần lưu chuyển tiền tệ.

Parser tách statutory section khỏi supplemental, customer hoặc broker section. Parser giữ riêng các dòng có cùng mã nhưng khác ngữ nghĩa. Parser ghép hai vector kỳ sau khi kiểm tra cấu trúc.

Code chính nằm trong `src/b03_cashflow/`.

### Notes

Notes pipeline gồm các bước:

1. `scanner` tìm vùng thuyết minh.
2. `sectionizer` chia vùng theo đề mục.
3. `block_classifier` phân loại bảng, bullet, OCR và movement block.
4. `table_parser` và `structural_parser` tách label, hierarchy, unit và period.
5. `linker` và `reconciliation` tạo link có provenance.
6. `row_exporter` xuất CSV hoặc JSON để review.

Parser đọc bullet như cây. Thụt đầu dòng tạo parent và child. Metadata gắn với node gần nhất. Giá trị kỳ được tách theo period. Parser chỉ ghép các cụm cột khi section, cấu trúc và số slot phù hợp.

Code chính nằm trong `src/notes/`.

## Cấu trúc repository

```text
Flatten/
├── app/                         # CLI pipeline
├── src/
│   ├── b01_financial_position/  # B01
│   ├── b02_income/              # B02
│   ├── b03_cashflow/            # B03
│   ├── common/                  # Context, recovery, output, reconciliation
│   └── notes/                   # Notes IR, link và export
├── flat_parser/                 # Structural parser và locator dùng chung
├── resources/
│   ├── schemas/                 # Schema và alias
│   └── guides/                  # Guide
├── scripts/
│   ├── ground_truth/            # Build và audit baseline
│   ├── evaluation/              # Compare và quality report
│   └── maintenance/             # Script bảo trì
├── tests/                       # Regression và integration tests
├── VERSION.txt
└── requirements.txt
```

`md_reports/`, `ground_truth/` và `output/` là thư mục cục bộ. Git bỏ qua các thư mục này.

## Cài đặt

Yêu cầu Python 3.10 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
```

Runtime dùng thư viện chuẩn Python. `requirements.txt` phục vụ test suite.

## Chạy pipeline

Chạy toàn bộ Markdown và bật Notes:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --notes
```

Chạy ba bảng chính:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --no-notes
```

Ép cặp năm cho một lần kiểm thử:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --current-year 2025 `
  --previous-year 2024 `
  --notes
```

Override sector cho B02:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --sector bank `
  --notes
```

Nếu không truyền năm, resolver suy luận năm riêng cho từng file. Nếu input là một file Markdown, pipeline chỉ xử lý file đó.

Chạy Notes riêng:

```powershell
python .\app\run_notes.py .\md_reports `
  --output .\output\notes_current `
  --write-ir
```

## Output

Output production có dạng:

```text
output/current/
├── manifest.json
└── reports/
    ├── <source-stem>__<sha256-prefix>.json
    └── ...
```

`manifest.json` chứa:

- contract version;
- số lượng report;
- source hash;
- kỳ báo cáo;
- đường dẫn tới từng report.

Mỗi report dùng contract `vn_financial_report_output@2.0.0` và có các phần:

`contract`, `report`, `periods`, `statements`, `notes`, `quality`.

Production output không chứa raw IR, mapping score hoặc bảng so sánh. Dùng `--audit` khi cần điều tra:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --notes `
  --audit
```

Audit được ghi trong `output/current/audit/`. Audit có thể chứa canonical JSON, comparison, Notes rows, summary và `error_taxonomy`.

Audit phục vụ review. Downstream không nên phụ thuộc vào các field nội bộ trong audit.

Tạo viewer để xem output:

```powershell
python .\scripts\visualize_output.py --open
```

Viewer được tạo tại `output/inspection/output_viewer.html`. Viewer cho phép lọc theo file, statement, label, value, mapping, raw text và source line.

## Ground truth và đối chiếu

Build Notes ground truth:

```powershell
python .\scripts\ground_truth\build_notes_ground_truth.py `
  .\md_reports `
  --output .\ground_truth\notes
```

Tạo review queue cho ba bảng chính:

```powershell
python .\scripts\ground_truth\prepare_main_statement_gold.py `
  --baselines .\ground_truth\main_statements `
  --source-dir .\md_reports `
  --output .\output\main_statement_gold_queue
```

So sánh output với baseline:

```powershell
python .\scripts\evaluation\compare_main_statement_ground_truth.py `
  --ground-truth .\ground_truth\main_statements `
  --current .\output\current\audit `
  --ground-truth-mode eligible `
  --sources .\md_reports `
  --report .\output\main_statement_comparison.json
```

Chế độ `raw` giữ mọi observation. Chế độ `eligible` loại observation mơ hồ hoặc cần review khỏi chỉ số chính. Comparator so sánh `label + period + value` và tách `missing` khỏi `unexpected`.

Ground truth chỉ dùng để đánh giá. Runtime không đọc ground truth. Baseline chưa được human-review không phải gold standard.

## Production schema

B01, B02 và B03 dùng cùng cách tổ chức record. Mỗi statement có `items` và `observations`.

- `items` là node đã map semantic.
- `observations` là dòng nguồn chưa map hoặc cần reconcile.
- `value` chứa giá trị theo kỳ.
- `provenance` chứa evidence và mapping.
- `raw_text` giúp truy lại dòng Markdown.

Ví dụ rút gọn:

```json
{
  "contract": {"name": "vn_financial_report_output", "version": "2.0.0"},
  "report": {
    "id": "r_<sha256-prefix>",
    "source": {"name": "<report>.md", "sha256": "<sha256>"}
  },
  "periods": {
    "current": {"year": 2025},
    "previous": {"year": 2024}
  },
  "statements": {
    "income_statement": {
      "status": "ok",
      "items": [
        {
          "id": "INCOME.ENTERPRISE.NET_REVENUE",
          "label": "Doanh thu thuần",
          "value": {"current": 1000, "previous": 900},
          "provenance": {
            "evidence": [{"source_line": 42, "confidence": 1.0}],
            "mapping": {
              "status": "mapped",
              "method": "exact_label",
              "confidence": 1.0
            }
          }
        }
      ],
      "observations": []
    }
  },
  "notes": {"status": "not_detected"},
  "quality": {"status": "ok", "issues": []}
}
```

`source_only` dùng cho observation chưa có semantic link. `not_reported` dùng khi engine chưa ghi metadata mapping. Giá trị chưa xác định dùng `null`.

Schema nằm trong:

- `resources/schemas/production_report.schema.json`;
- `resources/schemas/batch_manifest.schema.json`.

## Kiểm thử

```powershell
python -m pytest -q
python -m compileall -q .
git diff --check
```

Test suite kiểm tra:

- structural parsing;
- period và year inference;
- source-only integrity;
- B01 recovery;
- B02 semantic mapping;
- B03 cash-flow fidelity;
- Notes parsing;
- ground-truth quality;
- locator routing.

Khi thêm rule mới:

1. viết test cho layout hoặc lỗi mới;
2. dùng cấu trúc hoặc semantic context, không dùng tên file;
3. kiểm tra provenance và period pairing;
4. chạy toàn bộ test;
5. cập nhật schema hoặc guide nếu rule áp dụng chung.

## Review trước khi dùng

1. Chạy pipeline trên Markdown nguồn.
2. Kiểm tra `manifest.json` và report tương ứng.
3. Chạy `--audit` nếu cần so sánh hoặc điều tra.
4. Kiểm tra `missing`, `unexpected`, `raw_text`, `source_line`, period và conflict.
5. Review các report có `partial_mapping`, `partial_source_coverage`, confidence thấp hoặc conflict niên độ.
6. Chỉ dùng output cho kết luận nghiệp vụ sau khi review xong conflict quan trọng.

## Phiên bản

Phiên bản parser nằm trong `VERSION.txt`. Repository lưu code, schema, guide, test và script đánh giá. Dữ liệu nguồn, ground truth và output cục bộ không thuộc release artifact.
