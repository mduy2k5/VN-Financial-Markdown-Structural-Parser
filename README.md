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
| Schema profile | `schema_v1_7` | Schema overlay cho BSI B01/B03 và alias overlay versioned cho cả B01/B02/B03; baseline vẫn có thể rollback. |
| Discovery | 57/57 | Pipeline nhận đủ file Markdown trong input. |
| Runtime | 0 lỗi | Batch chạy xong 57/57 file, không có runtime error. |
| Report-level status | 6 `ok`; 51 `review_required` | Lấy từ manifest; `review_required` là cổng review, không đồng nghĩa parser đọc sai. |
| B01 statement status | 32 `ok`; 25 `review_required` | Các file còn lại chủ yếu thiếu quan hệ cha–con hoặc có conflict trong source evidence. |
| B02 statement status | 57 `ok` | Alias overlay chỉ chuẩn hóa nhãn; không làm thay đổi giá trị semantic trước/sau. |
| B03 statement status | 56 `ok`; 1 `no_structural_rows` | `no_structural_rows` là file nguồn không có block B03 đủ cấu trúc, không phải runtime failure. |
| Audit fingerprint B01 | 32 `ok`; 25 `review_required` | Đây là audit gate riêng, không phải report-level status trong manifest. |
| Audit coverage B03 | 56 `ok`; 1 `no_structural_rows` | Alias coverage đã loại được trạng thái `partial_source_coverage`; file còn lại thiếu block cấu trúc trong source. |
| Formula checks | 8 file; 11 cảnh báo | Không tăng do schema overlay trong focused comparison; cần triage riêng. |
| Notes | 57/57 chạy khi bật `--notes` | Notes không ghi đè B01, B02 hoặc B03. |
| Regression suite | **136 passed** | Kết quả của `python -m pytest -q`. |

Các số liệu trên là kết quả batch schema_v1_7 ngày 21/09/2026 sau khi bổ sung alias
overlay. Chúng mô tả
một lần chạy, không phải cam kết accuracy cho mọi nguồn mới. Nguyên nhân chính
của các trường hợp còn review_required là Markdown đầu vào làm mất ngữ cảnh
hàng/cột, kỳ báo cáo và quan hệ cha–con; dữ liệu nguồn thiếu hoặc schema chưa
bao phủ biến thể mới là các nguyên nhân thứ cấp.

Alias mới được kiểm soát theo nguyên tắc: chỉ thêm biến thể nhãn có nghĩa rõ,
có bằng chứng lặp lại trong batch và không làm mất ngữ cảnh cấu trúc. Các nhãn
vẫn phụ thuộc quan hệ cha–con, số thứ tự biểu mẫu hoặc cột Markdown bị mất
không được ép thành alias global.

Báo cáo chi tiết:

- [Báo cáo lỗi còn tồn đọng và nguyên nhân](PARSER_REMAINING_ISSUES_REPORT_VI.md)
- [Bằng chứng VCB, BSI, VIB](PARSER_EVIDENCE_VCB_BSI_VIB_VI.md)
- [Báo cáo ảnh hưởng của Markdown](MARKDOWN_IMPACT_REPORT_VI.md)

## Flow xử lý một file Markdown

`app/pipeline.py::main()` điều phối toàn bộ pipeline. Với mỗi file, code gọi các bước theo thứ tự này:

```text
Markdown
  -> chọn file và đọc source
  -> suy luận kỳ và năm
  -> B02: extract, map, validate
  -> B03: extract, map, validate
  -> B01: parse cấu trúc, map, validate
  -> Notes: scan, parse, link
  -> chuẩn hóa contract
  -> ghi report JSON và manifest
```

## Thứ tự đọc code để hiểu hệ thống

Đọc theo luồng một file, từ điều phối đến dữ liệu cuối:

1. `app/pipeline.py::main()` — nhận tham số, chọn Markdown và điều phối batch.
2. `app/pipeline.py::process_one()` — xử lý một báo cáo và ghép B01, B02, B03, Notes.
3. `src/common/report_period.py::resolve_report_years()` — xác định kỳ hiện tại và kỳ so sánh.
4. `app/pipeline.py::run_income()` — gọi locator, extractor và mapper B02.
5. `app/pipeline.py::run_cashflow()` — gọi locator, extractor và mapper B03.
6. `src/b01_financial_position/extractor.py::FinancialPositionSourceParser.parse_text()` — đưa B01 vào structural parser.
7. `flat_parser/pipeline.py::FlatParserPipeline.parse_text()` — chuẩn hóa, dựng cây, gán giá trị và tạo canonical B01.
8. `src/notes/pipeline.py::NotesPipeline.parse_text()` — đọc vùng thuyết minh và tạo Notes IR bổ sung.
9. `src/common/output_contract.py::build_production_report()` — tạo JSON production thống nhất.
10. `src/common/output_contract.py::manifest_entry()` — tạo dòng manifest cho từng báo cáo.

Trong các file trên, docstring của hàm lõi dùng cùng một mẫu:

- `Đầu vào`: dữ liệu và tùy chọn mà hàm nhận.
- `Xử lý`: các quyết định chính và thứ tự các bước.
- `Đầu ra`: kiểu dữ liệu và ý nghĩa của kết quả.

Đọc `extractor.py` trước `mapper.py` để phân biệt hai việc: extractor tìm đúng dòng và giá trị trong source; mapper mới gán dòng đó vào node của schema. `output_contract.py` không parse lại source. File này chỉ làm sạch và đóng gói kết quả đã được các engine tạo ra.

### Bước 1 — Chọn file

File chạy:

- `app/pipeline.py::main()`
- `app/pipeline.py::select_md_files()`
- `app/pipeline.py::ensure_output_is_outside_input()`

`main()` nhận một file Markdown hoặc một thư mục. `select_md_files()` lập danh sách file cần chạy. Pipeline kiểm tra output không nằm trong input. Pipeline không đọc output cũ.

### Bước 2 — Đọc source và suy luận kỳ

File chạy:

- `app/pipeline.py::process_one()`
- `src/common/report_period.py::infer_report_year_pair()`
- `src/common/value_semantics.py::detect_document_unit()`

`process_one()` đọc text, tính SHA-256 và lấy unit chung của báo cáo. `infer_report_year_pair()` tìm năm hiện tại và năm trước từ nội dung Markdown. Kết quả này được truyền cho cả B01, B02, B03 và Notes.

### Bước 3 — Chạy B02

Trong `process_one()`, B02 chạy trước B03 và B01.

File chạy:

- `app/pipeline.py::run_income()`
- `flat_parser/statement_locator.py::StatementLocator.locate()` với profile `income_statement`
- `src/b02_income/extractor.py::extract_income_fallback()`
- `src/b02_income/mapper.py::IncomeMapper.map_rows()`
- `src/b02_income/mapper.py::IncomeMapper.canonical()`
- `src/common/source_observation.py::augment_from_rows()`
- `src/common/source_recovery.py::extract_generic_statement_rows()`
- `src/common/source_canonical_hydrator.py::augment_canonical_with_recovered_rows()`
- `src/common/source_reconciler.py::reconcile_source_observations()`
- `src/common/pipeline_metrics.py::build_metrics()`

Thứ tự xử lý:

1. Locator tìm scope có thể là B02.
2. Extractor đọc row từ bảng, bullet hoặc plain OCR.
3. Mapper map row vào schema theo sector.
4. Source recovery tìm row chưa được lấy vào canonical node.
5. Reconciler giữ lại observation và conflict.
6. Metrics ghi số row, coverage, mapping và validation.

### Bước 4 — Chạy B03

File chạy:

- `app/pipeline.py::run_cashflow()`
- `flat_parser/statement_locator.py::StatementLocator.locate()` với profile `cash_flow`
- `src/b03_cashflow/extractor.py::extract_cashflow_fallback()`
- `src/b03_cashflow/mapper.py::CashFlowMapper.map_rows()`
- `src/b03_cashflow/mapper.py::CashFlowMapper.canonical()`
- `src/common/source_observation.py::augment_from_rows()`
- `src/common/source_recovery.py::extract_generic_statement_rows()`
- `src/common/source_recovery.py::extract_code_period_table()`
- `src/common/source_canonical_hydrator.py::augment_canonical_with_recovered_rows()`
- `src/common/source_reconciler.py::reconcile_source_observations()`
- `src/common/pipeline_metrics.py::build_cashflow_metrics()`

Thứ tự xử lý:

1. Locator tìm scope B03.
2. Extractor tìm sector, phương pháp direct hoặc indirect và các row.
3. Mapper map row vào schema.
4. Source recovery ghép lại row bị tách hoặc thiếu một kỳ.
5. Reconciler giữ riêng các section bổ sung và các conflict.
6. Metrics ghi kết quả map và validation.

### Bước 5 — Chạy B01

File chạy:

- `src/b01_financial_position/extractor.py::FinancialPositionSourceParser.parse_text()`
- `flat_parser/pipeline.py::FlatParserPipeline.parse_text()`

`FlatParserPipeline.parse_text()` chạy các file theo thứ tự:

1. `flat_parser/textnorm.py::normalize_lines()` chuẩn hóa dòng.
2. `flat_parser/preprocess.py::filter_noise()` bỏ nhiễu.
3. `flat_parser/statement_locator.py::StatementLocator.locate()` tìm scope B01.
4. `flat_parser/context.py::financial_position_scope()` tạo scope cấu trúc dự phòng.
5. `flat_parser/tables.py::detect_tables()` tìm bảng.
6. `flat_parser/document.py::build_nodes()` dựng cây node.
7. `flat_parser/document.py::hydrate_keyed_record_wrappers()` và `hydrate_column_major_statement_blocks()` bổ sung cấu trúc bị tách.
8. `flat_parser/structural_classifier.py::StructuralClassifier.classify_all()` phân loại node.
9. `flat_parser/collector.py::collect_observation()` lấy observation từ node.
10. `flat_parser/resolver.py::resolve_observation()` gán period, unit và giá trị.
11. `flat_parser/consolidator.py::consolidate_resolved_fields()` gộp continuation.
12. `flat_parser/canonical_mapper.py::map_first_value_per_period()` tạo canonical nodes.
13. `flat_parser/validator.py::validate_financial_position()` kiểm tra tổng tài sản và tổng nguồn vốn.

Sau parser cấu trúc, B01 chạy source recovery:

- `src/common/source_recovery.py::extract_financial_position_source_rows()`
- `src/common/source_canonical_hydrator.py::augment_canonical_with_recovered_rows()`
- `src/common/source_reconciler.py::reconcile_source_observations()`

Locator chỉ chọn scope khi có title evidence, overlap đủ lớn và confidence đạt ngưỡng. Nếu không, B01 dùng scope cấu trúc ban đầu.

### Same-label recovery và rollback

Khi nhãn cha và nhãn con giống nhau, parser không dùng nhãn đơn độc làm
identity. Nó kết hợp `hierarchy_path`, parent trực tiếp, occurrence và các alias
giao nhau giữa node với parent. Ví dụ `Tài sản Có khác` ở cấp cha và cấp con
được map lần lượt vào `ASSET.OTHER` và `ASSET.OTHER.OTHER`.

Tính năng được bật mặc định. Có thể chạy lại baseline để so sánh hoặc rollback
ngay bằng:

```powershell
python -m app.pipeline <input> --output <output> --no-same-label-recovery
```

Trạng thái đã dùng được ghi trong `debug.stats.same_label_recovery`,
`parser.same_label_recovery` và `audit/run_metadata.json`. Tắt tính năng chỉ
đổi quyết định mapping; không xóa source observation hoặc output run cũ.

### Schema profile và rollback

Schema bổ sung cho BSI được triển khai dưới dạng overlay versioned, không ghi
đè schema baseline. CLI hiện dùng `schema_v1_7` mặc định, gồm:

- B01: các node con của `ASSET.OTHER.NON_CURRENT`;
- B03 securities: `103` và `103.1` cho tiền cuối năm;
- công thức kiểm tra tiền cuối năm của profile securities;
- B01 alias overlay `financial_position_aliases_v1_8_0.json`;
- B02 alias overlay `income_statement_aliases_v1_3_4.json`;
- B03 alias overlay `cash_flow_aliases_v1_3_0.json`.

Schema loader materialize overlay tại runtime. B02 dùng cùng loader với B01/B03;
B03 hỗ trợ cập nhật danh sách alias mà không phải copy lại catalog baseline.
Vì vậy mọi alias mới đều có thể truy vết về file base và không sửa trực tiếp
catalog production cũ.

Toàn bộ overlay nằm trong `resources/schemas/overlays/`. Để rollback về
baseline:

```powershell
python -m app.pipeline <input> --output <output> --schema-profile baseline
```

Mỗi audit run ghi `schema_profile` và đường dẫn schema đã dùng trong
`audit/run_metadata.json`; output của baseline và overlay nên được ghi vào hai
thư mục khác nhau để so sánh và khôi phục an toàn. Lệnh kiểm chứng batch dùng
cho thay đổi alias:

```powershell
python -m app.pipeline md_reports --output output/validation_alias_v18_batch_r2 --audit --no-notes --schema-profile schema_v1_7
python -m pytest -q
```

### Bước 6 — Chạy Notes

File chạy:

- `app/pipeline.py::scan_statement_context()`
- `src/notes/pipeline.py::NotesPipeline.parse_text()`
- `src/notes/scanner.py::detect_notes_scope()`
- `src/notes/sectionizer.py::sectionize_notes()`
- `src/notes/block_classifier.py::extract_blocks()`
- `src/notes/table_parser.py::parse_markdown_tables()`
- `src/notes/structural_parser.py::parse_bullet_structures()`
- `src/notes/linker.py::link_notes_to_primary()`
- `src/notes/reconciliation.py::reconcile_notes()`
- `src/notes/diagnostics.py::build_diagnostics()`

`scan_statement_context()` dùng scanner chung để cung cấp evidence cho Notes. `NotesPipeline` tìm vùng thuyết minh, chia section, đọc bảng và bullet, rồi link với kết quả primary. Notes là lớp bổ sung. Notes không ghi đè B01, B02 hoặc B03.

### Bước 7 — Chuẩn hóa và ghi output

File chạy:

- `app/pipeline.py::process_one()`
- `src/common/output_contract.py::clean_statement()`
- `src/common/output_contract.py::clean_notes()`
- `src/common/output_contract.py::build_production_report()`
- `app/pipeline.py::main()`
- `src/common/output_contract.py::report_filename()`
- `src/common/output_contract.py::manifest_entry()`

`process_one()` đồng bộ unit giữa các statement. `clean_statement()` và `clean_notes()` đưa kết quả về production contract. `build_production_report()` tạo một report JSON. `main()` ghi report vào `reports/` và ghi danh sách batch vào `manifest.json`.

Khi bật `--audit`, `process_one()` ghi thêm canonical artifacts, comparison, Notes rows và metrics vào `output/current/audit/`. Các file này chỉ phục vụ review.

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

Repository có ba lớp code chính:

1. `app/` nhận input và điều phối batch.
2. `src/` chứa engine cho B01, B02, B03, Notes và các module dùng chung.
3. `flat_parser/` chứa structural parser dùng chung, đặc biệt cho B01.

```text
Flatten/
├── app/                         # Entry point của pipeline
│   ├── pipeline.py              # Chạy B02 -> B03 -> B01 -> Notes -> output
│   └── run_notes.py             # Chạy riêng Notes
├── src/
│   ├── b01_financial_position/  # Extractor B01
│   ├── b02_income/              # Extractor, mapper và validator B02
│   ├── b03_cashflow/            # Extractor và mapper B03
│   ├── common/                  # Period, recovery, output, metrics
│   └── notes/                   # Scanner, parser, link và export Notes
├── flat_parser/                 # Parser cấu trúc và locator dùng chung
├── resources/
│   ├── schemas/                 # Schema, alias và output contract
│   └── guides/                  # Guide structural
├── scripts/                     # Evaluation, ground truth và maintenance
├── tests/                       # Unit, integration và quality tests
├── md_reports/                  # Input Markdown cục bộ
├── ground_truth/                # Baseline và review queue cục bộ
├── output/                      # Output chạy cục bộ
├── VERSION.txt                  # Phiên bản parser
└── requirements.txt             # Gói dùng cho test
```

### Entry point

| File | Vai trò |
|---|---|
| `app/pipeline.py` | Chọn file, gọi B02/B03/B01/Notes, tạo report và manifest. |
| `app/run_notes.py` | Chạy Notes riêng và xuất Notes IR. |
| `flat_parser/pipeline.py` | Chạy structural parser và tạo canonical nodes. |

### B01

| File hoặc thư mục | Vai trò |
|---|---|
| `src/b01_financial_position/extractor.py` | Adapter của B01 và source recovery sau parse. |
| `flat_parser/pipeline.py` | Điều phối normalize, scope, node, map và validation. |
| `flat_parser/statement_locator.py` | Tìm scope ứng viên bằng alias và evidence. |
| `flat_parser/document.py` | Dựng cây node và xử lý wrapper/column-major. |
| `flat_parser/collector.py` | Thu observation từ node. |
| `flat_parser/resolver.py` | Gán period, unit và giá trị. |
| `flat_parser/canonical_mapper.py` | Tạo canonical node. |
| `flat_parser/validator.py` | Kiểm tra cấu trúc và tổng statement. |

### B02 và B03

| File hoặc thư mục | Vai trò |
|---|---|
| `src/b02_income/extractor.py` | Tìm scope và đọc row của B02. |
| `src/b02_income/mapper.py` | Map row B02 vào schema theo sector. |
| `src/b02_income/validator.py` | Kiểm tra coverage và công thức B02. |
| `src/b03_cashflow/extractor.py` | Tìm scope, sector, method và row B03. |
| `src/b03_cashflow/mapper.py` | Map row B03 vào schema. |
| `flat_parser/statement_locator.py` | Locator dùng chung cho profile B02 và B03. |

### Module dùng chung

| File hoặc thư mục | Vai trò |
|---|---|
| `src/common/report_period.py` | Suy luận cặp năm và kỳ báo cáo. |
| `src/common/value_semantics.py` | Nhận diện unit và kiểu giá trị. |
| `src/common/source_recovery.py` | Đọc lại row nguồn còn thiếu trong canonical parse. |
| `src/common/source_canonical_hydrator.py` | Bổ sung row có evidence vào canonical output. |
| `src/common/source_observation.py` | Tạo observation từ row nguồn. |
| `src/common/source_reconciler.py` | Giữ provenance và xử lý conflict. |
| `src/common/output_contract.py` | Chuẩn hóa report JSON và manifest. |
| `src/common/pipeline_metrics.py` | Tạo metrics cho B02 và B03. |
| `src/common/error_taxonomy.py` | Phân loại lỗi trong audit. |

### Notes

| File | Vai trò |
|---|---|
| `src/notes/pipeline.py` | Điều phối toàn bộ Notes parser. |
| `src/notes/scanner.py` | Tìm vùng thuyết minh. |
| `src/notes/sectionizer.py` | Chia vùng thành section. |
| `src/notes/block_classifier.py` | Phân loại bảng, bullet và block. |
| `src/notes/table_parser.py` | Đọc Markdown table. |
| `src/notes/structural_parser.py` | Đọc cây bullet và period. |
| `src/notes/linker.py` | Link Notes với primary statement. |
| `src/notes/reconciliation.py` | So sánh Notes với primary statement. |
| `src/notes/row_exporter.py` | Xuất Notes rows để review. |

### Resources, scripts và tests

- `resources/schemas/`: schema và alias cho B01, B02, B03, off-balance, production report và batch manifest.
- `resources/guides/`: pattern guide và `compiled/structural_guide.json`.
- `scripts/ground_truth/`: build, repair, audit và review baseline.
- `scripts/evaluation/`: compare output, Notes và coverage.
- `scripts/maintenance/`: rebuild guide và tạo coverage report.
- `scripts/visualize_output.py`: tạo viewer HTML cho output.
- `tests/b01/`, `tests/b02/`, `tests/b03/`: test theo statement.
- `tests/notes/`: test Notes.
- `tests/integration/`: test toàn pipeline.
- `tests/quality/`: test output, baseline và quality rule.
- `tests/legacy/`: test cũ để giữ tương thích.

`md_reports/`, `ground_truth/` và `output/` chỉ dùng ở local. Git bỏ qua các thư mục này. Runtime chỉ đọc `md_reports/` và ghi `output/`.

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
