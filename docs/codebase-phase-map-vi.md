# Bản đồ code theo phase

Tài liệu này gom các file theo vai trò trong từng phase chạy. Đây là bản đồ
đọc code, không phải thay đổi layout thư mục vật lý; giữ nguyên import và
đường chạy hiện tại.

## 1. Luồng production chính

```text
python app/pipeline.py <input.md|input-folder>
        |
        +-- P0. Khởi tạo CLI, schema profile, output boundary
        |
        +-- P1. Discovery source + suy luận kỳ báo cáo
        |
        +-- P2. Normalize Markdown + định vị scope statement
        |
        +-- P3A. B02: extract -> adapt -> map -> validate
        +-- P3B. B03: extract -> adapt -> map -> validate
        +-- P3C. B01: dựng cây -> map semantic -> validate
        |
        +-- P4. Source recovery/hydration/reconcile
        |
        +-- P5. Notes bổ sung và link với B01/B02/B03
        |
        +-- P6. Metrics, output contract, production report, audit, manifest
```

Trong một report, thứ tự gọi thực tế của `app/pipeline.py` là **B02 -> B03 ->
B01 -> Notes**. P4 không phải một chương trình chạy riêng; nó được gọi bên
trong từng nhánh B01/B02/B03 sau khi có kết quả map ban đầu.

## 2. Các file nằm trên critical path

Đây là nhóm cần đọc trước nếu muốn hiểu một lần chạy production:

| Phase | File điều phối | File engine/chính | Khi chạy |
|---|---|---|---|
| P0 | `app/pipeline.py` | `resources/schemas/**`, `resources/guides/**` | Luôn chạy |
| P1 | `app/pipeline.py` | `src/common/report_period.py`, `src/common/value_semantics.py` | Luôn chạy |
| P2 | `app/pipeline.py`, `flat_parser/statement_locator.py` | `flat_parser/textnorm.py`, `flat_parser/preprocess.py`; `flat_parser/statement_scanner.py` cho Notes; `src/common/row_block_scanner.py` tùy chọn | Locator luôn cho primary; scanner dùng khi chạy Notes; row-block tùy `--row-scan-mode` |
| P3A | `app/pipeline.py::run_income` | `src/b02_income/extractor.py`, `src/b02_income/scope.py`, `src/b02_income/mapper.py`, `src/b02_income/validator.py` | Luôn chạy |
| P3B | `app/pipeline.py::run_cashflow` | `src/b03_cashflow/extractor.py`, `src/b03_cashflow/mapper.py` | Luôn chạy |
| P3C | `app/pipeline.py::process_one` | `src/b01_financial_position/extractor.py`, `flat_parser/pipeline.py` | Luôn chạy |
| P4 | Được gọi từ P3 | `src/common/source_recovery.py`, `src/common/source_canonical_hydrator.py`, `src/common/source_observation.py`, `src/common/source_reconciler.py`, `src/common/structural_identity.py` | Sau map ban đầu |
| P5 | `app/pipeline.py` | `src/notes/pipeline.py` và các module `src/notes/**` | Khi bật `--notes` |
| P6 | `app/pipeline.py` | `src/common/pipeline_metrics.py`, `src/common/output_contract.py` | Ghi production/audit |

## 3. Chi tiết từng phase

### P0 — Entrypoint và cấu hình

File chạy trực tiếp:

- `app/pipeline.py`: entrypoint production cho toàn bộ báo cáo.
- `app/run_notes.py`: entrypoint riêng cho Notes, không chạy B01/B02/B03.

Resource được nạp theo schema profile:

- `resources/schemas/*.json`: schema và alias baseline;
- `resources/schemas/overlays/*.json`: bundle versioned, ví dụ `schema_v1_7`;
- `resources/guides/compiled/structural_guide.json`: guide cho structural
  parser;
- `resources/guides/A*_*/`: pattern nguồn trước khi compile guide.

> Cờ rollback quan trọng nằm ở `app/pipeline.py`:
>
> - `--schema-profile baseline`: quay về schema baseline;
> - `--no-same-label-recovery`: tắt recovery cha-con trùng tên;
> - `--row-scan-mode off`: tắt fast row-block scan;
> - `--no-notes`: tắt Notes mà không ảnh hưởng primary statements.

### P1 — Discovery source và suy luận kỳ

Điều phối trong `app/pipeline.py`:

- `select_md_files`: chọn một Markdown đại diện cho mỗi report;
- `stem_base`: gom các biến thể cùng tên gốc;
- `ensure_output_is_outside_input`: ngăn output bị đọc lại như input;
- `infer_report_year_pair`: suy luận năm hiện tại/năm so sánh cho từng file;
- `detect_document_unit`: lấy đơn vị chung của báo cáo.

Module dùng chung:

- `src/common/report_period.py`: kỳ báo cáo, ngày và cặp năm;
- `src/common/value_semantics.py`: đơn vị, text folding, semantics giá trị.

### P2 — Chuẩn hóa Markdown và định vị vùng dữ liệu

Chuỗi xử lý:

1. `flat_parser/textnorm.py::normalize_lines` chuyển raw text thành các dòng có
   line number và dạng normalized.
2. `flat_parser/preprocess.py::filter_noise` loại dòng nhiễu.
3. `flat_parser/statement_locator.py::StatementLocator` dùng alias/schema để
   thu hẹp scope ứng viên, nhưng phải qua safety gate của
   `flat_parser/pipeline.py::FlatParserPipeline._accept_locator_scope`.
4. Khi Notes cần context sector hoặc chạy `app/run_notes.py`,
   `flat_parser/statement_scanner.py::scan_statements` mới quét candidate B01,
   B02, B03 và sector.
5. `src/common/row_block_scanner.py` là bộ quét nhanh theo row block. Chế độ
   `shadow` chỉ ghi evidence; `assist` cho B02 dùng cửa sổ dòng đáng tin cậy;
   mặc định `off` để dễ rollback.

File chịu trách nhiệm tạo cây B01 ở phase sau:

- `flat_parser/document.py`: dựng node và hierarchy từ scope;
- `flat_parser/tables.py`: nhận diện bảng Markdown;
- `flat_parser/context.py`: context statement và period/unit context;
- `flat_parser/models.py`: model trung gian.

### P3A — B02: báo cáo kết quả kinh doanh

Điểm vào là `app/pipeline.py::run_income`.

```text
src/b02_income/extractor.py
        -> src/b02_income/scope.py
        -> src/b02_income/mapper.py
        -> src/b02_income/validator.py
        -> common recovery/hydration/reconcile
        -> src/common/pipeline_metrics.py
```

Vai trò file:

- `extractor.py`: nhận diện scope B02 và lấy row từ nhiều layout;
- `scope.py`: chọn vùng, parse period/value và loại header/nhiễu;
- `mapper.py`: biến row nguồn thành `IncomeRow`, map vào schema theo sector;
- `validator.py`: kiểm tra công thức và chuẩn hóa dấu theo bank/enterprise/
  securities/insurance.

### P3B — B03: báo cáo lưu chuyển tiền tệ

Điểm vào là `app/pipeline.py::run_cashflow`.

```text
src/b03_cashflow/extractor.py
        -> src/b03_cashflow/mapper.py
        -> common recovery/hydration/reconcile
        -> src/common/pipeline_metrics.py
```

Vai trò file:

- `extractor.py`: chọn scope, phát hiện sector/phương pháp direct/indirect,
  xử lý bảng dòng-cột và các layout value-before-label;
- `mapper.py`: chuẩn hóa row, map theo schema/alias và tạo canonical B03.

### P3C — B01: bảng cân đối kế toán

Điểm vào là `src/b01_financial_position/extractor.py`, được gọi từ
`app/pipeline.py::process_one`.

```text
src/b01_financial_position/extractor.py
        -> flat_parser/pipeline.py::FlatParserPipeline
        -> normalize/filter/scope
        -> build document tree + table context
        -> classify structural nodes
        -> PASS 1: semantic anchors
        -> PASS 2: collect payload trong boundary child
        -> resolve period/value/context
        -> consolidate + dual-role expansion
        -> canonical mapping + validation + QA
```

Các module structural được `flat_parser/pipeline.py` gọi trực tiếp:

- `alias_matcher.py`, `mapping_strategy.py`, `regex_matcher.py`: tạo candidate
  semantic;
- `semantic_catalog.py`, `schema_loader.py`: nạp schema/alias và quan hệ node;
- `source_context.py`: dựng context cha-con từ source;
- `collector.py`, `resolver.py`, `canonical_mapper.py`: lấy payload, resolve
  period/value và tạo canonical;
- `consolidator.py`, `dual_role.py`: gộp continuation và xử lý dòng có hai vai
  trò;
- `structural_classifier.py`, `primitives.py`, `guide.py`: nhận diện pattern,
  period/value và structural guide;
- `qa.py`, `validator.py`: coverage, completeness, total và validation;
- `models.py`, `document.py`, `tables.py`, `context.py`, `textnorm.py`,
  `preprocess.py`: model và nền tảng dựng cây.

### P4 — Source recovery, hydration và reconcile

Phase này chạy sau kết quả map ban đầu của từng statement, không đọc output của
lần chạy trước.

- `src/common/source_recovery.py`: vét source rows, period, form code, hierarchy
  context và các layout bị tách dòng/cột;
- `src/common/source_canonical_hydrator.py`: bổ sung kỳ còn thiếu hoặc hydrate
  node đã tồn tại; không tự tạo identity tùy tiện;
- `src/common/source_observation.py`: thêm observation từ row nguồn;
- `src/common/source_reconciler.py`: đối chiếu semantic node với source
  observation, xử lý conflict/ambiguous mapping;
- `src/common/structural_identity.py`: tạo identity theo label, context và
  occurrence để giảm collision cha-con cùng tên;
- `src/common/row_block_scanner.py`: cung cấp boundary evidence khi bật scan.

Các tiện ích chạy xuyên suốt P1-P4:

- `src/common/report_period.py`;
- `src/common/value_semantics.py`;
- `src/common/period_resolver.py`;
- `src/common/output_contract.py` chưa ghi output ở đây nhưng dùng lại kết quả
  của P4 ở P6.

### P5 — Notes bổ sung

`app/pipeline.py::process_one` gọi Notes sau khi đã có primary B01/B02/B03.
`app/run_notes.py` có thể chạy Notes độc lập.

```text
src/notes/pipeline.py
        -> scanner.py
        -> sectionizer.py
        -> block_classifier.py
             -> table_parser.py
             -> structural_parser.py
             -> dimension_inference.py
        -> unit_normalization.py + sector_profile.py
        -> linker.py
        -> reconciliation.py
        -> diagnostics.py
        -> row_exporter.py
```

Vai trò chính:

- `note_ir.py`: model IR cho section/block/row/value/link;
- `scanner.py`: xác định vùng Notes và loại primary heading giả;
- `sectionizer.py`: chia Notes thành section;
- `block_classifier.py`: phân loại block bảng/bullet/semantic;
- `table_parser.py`, `structural_parser.py`: đọc hai dạng layout chính;
- `dimension_inference.py`, `unit_normalization.py`, `sector_profile.py`: suy
  luận dimension, unit và topic theo sector;
- `linker.py`, `reconciliation.py`: link với primary và đối chiếu tổng;
- `diagnostics.py`: tạo diagnostics;
- `row_exporter.py`: xuất row-level CSV/JSON và aggregate.

Notes là lớp bổ sung. Khi Notes không tìm thấy hoặc link không chắc chắn,
primary statement vẫn là nguồn chính trong production contract.

### P6 — Metrics, contract và output

File chính:

- `src/common/pipeline_metrics.py`: metrics mapping/coverage/formula/recovery;
- `src/common/output_contract.py`: quality gate, clean statement, clean Notes,
  production envelope và manifest entry;
- `app/pipeline.py`: ghi `reports/*.json`, `manifest.json`, audit canonical,
  comparison summary và row-block audit;
- `src/notes/row_exporter.py`: ghi Notes rows khi chạy Notes standalone hoặc
  khi `process_one` bật Notes.

Output production khác audit:

- `reports/`: contract ổn định cho consumer;
- `manifest.json`: danh sách report và options của batch;
- `audit/`: canonical/debug/comparison để review, không phải input cho lần chạy
  sau.

## 4. Nhóm script nội bộ ngoài production

Các script dưới đây không được `app/pipeline.py` gọi trong một batch production.
Chúng được chạy theo phase hỗ trợ trong checkout nội bộ. Thư mục `scripts/`
được loại khỏi public repository để tách code runtime khỏi công cụ đánh giá,
ground truth và maintenance.

### Ground truth và review

Thư mục `scripts/ground_truth/`:

- `prepare_main_statement_gold.py`: chuẩn bị/analyze baseline B01/B02/B03;
- `audit_main_statement_baselines.py`: kiểm tra source hash và issue baseline;
- `repair_main_statement_baselines.py`: sửa baseline theo evidence;
- `build_notes_ground_truth.py`: dựng ground truth cho Notes;
- `build_notes_review_queue.py`: chọn item cần review;
- `review_notes_queue.py`: review queue theo source evidence;
- `triage_notes_reconciliation.py`: phân loại conflict/reconciliation Notes.

### Evaluation và báo cáo

Thư mục `scripts/evaluation/`:

- `build_current_evaluation_report.py`: tổng hợp báo cáo đánh giá hiện tại;
- `compare_main_statement_ground_truth.py`: so primary output với ground truth;
- `compare_notes_ground_truth.py`: so Notes với ground truth;
- `compare_linked_notes_outputs.py`: so link/reconciliation Notes;
- `evaluate_notes_coverage.py`: đo coverage Notes;
- `evaluate_notes_quality.py`: đánh giá chất lượng Notes;
- `export_per_report_comparison.py`: xuất bảng so sánh từng report.

### Maintenance và visualization

- `scripts/maintenance/rebuild_universal_guide.py`: compile guide;
- `scripts/maintenance/rebuild_guide.ps1`: wrapper rebuild guide;
- `scripts/maintenance/build_coverage_report.py`: báo cáo coverage structural;
- `scripts/visualize_output.py`: đọc output để dựng visualization.

## 5. Resource và test theo phase

### Resource

- `resources/schemas/`: schema/alias mà mapper và catalog nạp;
- `resources/schemas/overlays/`: bản thay đổi versioned, có thể rollback bằng
  `--schema-profile`;
- `resources/guides/`: guide pattern cho structural parser.

### Test

- `tests/b01/`: dựng cây, scope, identity, hierarchy, schema B01;
- `tests/b02/`: semantics, mapper và quy tắc B02;
- `tests/b03/`: fidelity và layout B03;
- `tests/notes/`: Notes scope, structural parser và row export;
- `tests/quality/`: quality gate, row-block scanner, overlays, version,
  integration-level regression;
- `tests/integration/`: source-only integrity;
- `tests/legacy/`: regression lịch sử, không phải entrypoint production.

## 6. Thứ tự đọc code ngắn nhất

Nếu chỉ cần hiểu production trong một buổi, đọc theo thứ tự này:

1. `app/pipeline.py`: `main` -> `process_one` -> `run_income`/`run_cashflow`.
2. `src/b01_financial_position/extractor.py` để hiểu đường B01 và gọi
   `flat_parser/pipeline.py`.
3. `src/b02_income/extractor.py` + `mapper.py`.
4. `src/b03_cashflow/extractor.py` + `mapper.py`.
5. `src/common/source_recovery.py` + `source_canonical_hydrator.py` +
   `source_reconciler.py`.
6. `src/notes/pipeline.py` nếu cần Notes.
7. `src/common/output_contract.py` để hiểu JSON cuối cùng.
8. Nếu cần hiểu cách đánh giá, xem mô tả phase nội bộ; các script evaluation
   không thuộc critical path và không có trong public checkout.
