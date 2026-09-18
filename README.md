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
| B01 | 57/57 đã chạy | Structural parser và source recovery hoàn tất; các conflict ngữ nghĩa vẫn được giữ ở trạng thái `review_required` để review |
| B02 | 57/57 `ok` | Tỷ lệ ánh xạ theo dòng: 100%; đã chuẩn hóa nested note/carry-forward, vector column-major và các node chi phí chi tiết |
| B03 | 57/57 `ok` | Tỷ lệ ánh xạ theo dòng: 100%; nhãn được lấy từ nội dung `Diễn giải` khi báo cáo serialize mã và giá trị thành các nhánh con |
| Notes | 57/57 `parsed` | Lớp bổ sung, không ghi đè primary statements |
| Locator | B01: 41/57; B02: 46/57; B03: 44/57 | Alias-assisted routing chỉ kích hoạt khi đủ bằng chứng; file còn lại dùng fallback an toàn |
| Batch quality | 14 `ok`; 43 `review_required` | `review_required` phản ánh conflict/thiếu bằng chứng cần kiểm tra, không phải lỗi runtime |
| Regression suite | **102 passed** | Kiểm thử tự động hiện hành |

Các số liệu trên là snapshot của một lần chạy, không phải cam kết accuracy tuyệt đối. `partial_mapping` và `partial_source_coverage` là tín hiệu cần review; chúng không có nghĩa toàn bộ báo cáo bị loại bỏ.

## Nguyên tắc thiết kế

### Source-first

Mỗi báo cáo có context riêng gồm cặp kỳ, sector, phạm vi bảng và provenance. Output lưu lại khi có thể:

- `report.source.name`, `report.source.sha256`;
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
Resolver kỳ/năm + alias-assisted locator theo từng báo cáo
    │
    ▼
Candidate scope + candidate rows (chỉ là evidence định tuyến)
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

### Alias-assisted locator

`StatementLocator` là lớp định tuyến trước khi parse, không phải mapper cuối cùng. Nó quét alias dùng chung của B01/B02/B03, nhận diện title/signature, kỳ báo cáo, mật độ số liệu và các dòng có khả năng thuộc bảng. Locator loại các dòng mục lục và vùng thuyết minh không liên quan, sau đó trả về `selected_scope` và `candidate_rows` cho parser.

Scope chỉ được chấp nhận khi có title-backed evidence, mức chồng lấn với vùng scope hiện có và confidence đạt ngưỡng. Nếu bằng chứng yếu, pipeline giữ nguyên scope/fallback hiện hữu. Candidate rows chỉ giúp định tuyến và thu hẹp vùng tìm kiếm; chúng không được dùng để tự động map canonical node. Vì vậy mã biểu mẫu, số thuyết minh, tên file và giá trị biết trước không thể trở thành khóa identity.

Thông tin locator phục vụ audit gồm `locator_enabled`, `locator_activated`, `locator_reason`, `locator_confidence`, `locator_alias_hits` và `locator_candidate_rows`. Các trường này không làm thay đổi production contract; chúng chỉ giúp giải thích vì sao một file được định tuyến hoặc fallback.

## Các engine

### B01 — Financial Position

B01 xử lý bảng Markdown, dòng bị tách cột và cấu trúc bullet/OCR. Locator có thể thu hẹp vùng ứng viên, sau đó structural core phục hồi section, parent/child, nhãn và hai slot kỳ trước khi ánh xạ sang canonical schema. Source recovery chỉ bổ sung observation có bằng chứng và luôn giữ provenance.

Mã chính nằm trong `src/b01_financial_position/` và `flat_parser/`.

### B02 — Income Statement

B02 xác định scope và sector (`bank`, `enterprise`, `securities`, `insurance`) từ source. Locator chỉ định tuyến vùng ứng viên khi có đủ bằng chứng; extractor thu dòng từ bảng, bullet hoặc plain OCR; mapper chuẩn hóa nhãn bằng alias và semantic matching có ngưỡng/margin; validator kiểm tra coverage và công thức khi đủ dữ liệu.

`form_code` chỉ được giữ để truy vết, không quyết định identity của dòng.

Mã chính nằm trong `src/b02_income/`.

### B03 — Cash Flow

B03 phát hiện scope, sector và direct/indirect method từ chính phần LCTT. Locator hỗ trợ chọn vùng ứng viên, còn parser vẫn phân biệt statutory section với supplemental/customer/broker section, ghép hai vector kỳ và giữ riêng các dòng có cùng mã nhưng khác ngữ nghĩa.

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
├── flat_parser/                   # Structural core, locator và scanner dùng chung
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

`manifest.json` là chỉ mục batch, chứa contract version, số lượng báo cáo, source hash, kỳ báo cáo và đường dẫn tương đối tới từng report. Tên report lấy từ tên file Markdown đã chuẩn hóa, kèm hậu tố hash để tránh trùng; không cần mở manifest vẫn có thể nhận diện nguồn. Mỗi report JSON dùng `vn_financial_report_output@2.0.0`, gồm `contract`, `report`, `periods`, `statements`, `notes` và `quality`. Các mảng lồng nhau được lưu dưới dạng JSON native; giá trị số được chuẩn hóa thành number hoặc `null`.

Các parser diagnostics, mapping score, raw IR và bảng so sánh không nằm trong output production. Khi cần đánh giá hoặc điều tra, bật profile audit:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --notes `
  --audit
```

Khi đó artifact giàu thông tin được đặt riêng dưới `output/current/audit/` (`*.canonical.json`, `*.comparison.json`, `notes_rows/`, `comparison_summary.*`, `run_metadata.json`). Mỗi statement audit có thêm `error_taxonomy` để tách nhiễu cấu trúc, thiếu slot kỳ, lỗi column-major, duplicate và semantic mapping gap. Đây là lớp phục vụ review/evaluation, không phải contract dữ liệu chính.

Để kiểm tra trực quan toàn bộ output hiện tại, chạy viewer không phụ thuộc thư viện:

```powershell
python .\scripts\visualize_output.py --open
```

Viewer được tạo tại `output/inspection/output_viewer.html`, cho phép lọc theo file, bảng, nhãn, giá trị, mapping, raw text và dòng nguồn.

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
  "contract": {"name": "vn_financial_report_output", "version": "2.0.0"},
  "report": {
    "id": "r_<sha256-prefix>",
    "source": {"name": "<report>.md", "sha256": "<sha256>"}
  },
  "periods": {
    "current": {"year": 2025, "start_date": null, "end_date": "2025-12-31"},
    "previous": {"year": 2024, "start_date": null, "end_date": "2024-12-31"}
  },
  "statements": {
    "cash_flow": {
      "status": "ok",
      "statement_type": "CASH_FLOW_STATEMENT",
      "schema": {"id": "cash_flow", "version": "<schema-version>"},
      "context": {"sector": "bank", "method": "direct", "unit": "million_vnd"},
      "items": [
        {
          "record_type": "semantic_item",
          "id": "CASHFLOW.BANK.DIRECT.INTEREST_RECEIVED",
          "source_id": null,
          "label": "Thu nhập lãi và các khoản thu nhập tương tự nhận được",
          "attributes": {
            "kind": null,
            "parent_id": null,
            "children": [],
            "section": "operating",
            "sector": "bank",
            "method": "direct",
            "form_code": "01",
            "code": null,
            "note_ref": null
          },
          "value": {
            "current": 12919243,
            "previous": 9453794,
            "additional": {},
            "note": null,
            "unit": "million_vnd",
            "raw_text": "* **Thu nhập lãi và các khoản thu nhập tương tự nhận được:** 12.919.243 triệu đồng (Năm nay), 9.453.794 triệu đồng (Năm trước)",
            "raw_values": {"current": null, "previous": null}
          },
          "provenance": {
            "evidence": [{
              "source_line": 42,
              "source_label": "Thu nhập lãi và các khoản thu nhập tương tự nhận được",
              "raw_text": "* **Thu nhập lãi và các khoản thu nhập tương tự nhận được:** 12.919.243 triệu đồng (Năm nay), 9.453.794 triệu đồng (Năm trước)",
              "confidence": 1.0
            }],
            "mapping": {
              "status": "mapped",
              "target_id": "CASHFLOW.BANK.DIRECT.INTEREST_RECEIVED",
              "method": "exact_label",
              "confidence": 1.0
            }
          }
        }
      ],
      "observations": [],
      "summary": {
        "counts": {"items": 1, "observations": 0, "valued_items": 1},
        "mapping": {"input_rows": 1, "mapped_rows": 1, "unmapped_rows": 0, "rate": 1.0},
        "coverage": {"current": 1.0, "previous": 1.0}
      },
      "validation": {
        "status": "ok",
        "formulas": {"evaluated": 0, "passed": 0, "failed": 0, "pass_rate": null}
      }
    }
  },
  "notes": {"status": "not_detected", "schema": {"id": null, "version": null}, "sections": [], "rows": [], "links": [], "summary": {"section_count": 0, "row_count": 0, "link_count": 0}},
  "quality": {"status": "ok", "issues": []}
}
```

Ba statement dùng cùng một record shape: `items` là các mục semantic, `observations` là các dòng quan sát nguồn. Hai mảng không phải hai khóa nghiệp vụ thay thế nhau; `observations` chỉ là provenance/reconciliation layer. Mỗi record luôn có `attributes`, `value` và `provenance`; mỗi `provenance` luôn có `evidence` và `mapping`. Nếu chưa có liên kết semantic, observation có `mapping.status = "source_only"`; nếu metadata mapping chưa được báo cáo, semantic item có `mapping.status = "not_reported"`.

`report.source` là metadata nhận diện input; `source_line`, `source_label`, `raw_text` và `confidence` là provenance để truy ngược Markdown. `value.raw_text` giữ nguyên dòng Markdown đã dùng để lấy giá trị; `value.raw_values` giữ chuỗi số gốc khi parser có chuỗi đó. `value.additional` luôn là object (rỗng khi không có dữ liệu bổ sung), còn giá trị không xác định dùng `null`. Parser không đọc output hoặc ground truth của lần chạy trước để bổ sung dữ liệu.

`notes` dùng contract bảng riêng vì một dòng thuyết minh có thể có nhiều giá trị, chiều phân tích và liên kết. Tuy vậy, section, row, value, source và link đều có bố cục cố định; không trộn các cột phẳng nội bộ vào report production.

Contract được mô tả tương ứng tại `resources/schemas/production_report.schema.json` và `resources/schemas/batch_manifest.schema.json`. Đây là interface production; các artifact trong `audit/` vẫn là dữ liệu kiểm tra nội bộ và có thể thay đổi theo engine.

Để xem đầy đủ trường nội bộ phục vụ đánh giá, đọc các artifact trong `audit/`; không dùng chúng làm interface downstream ổn định.

Ví dụ giá trị trong report production:

```json
{
  "record_type": "semantic_item",
  "id": "INCOME.ENTERPRISE.NET_REVENUE",
  "label": "Doanh thu thuần",
  "value": {
    "current": 1000,
    "previous": 900,
    "additional": {},
    "note": null,
    "unit": null,
    "raw_text": "* Doanh thu thuần: 1.000 (Năm nay), 900 (Năm trước)",
    "raw_values": {"current": null, "previous": null}
  },
  "provenance": {
    "evidence": [{
      "source_line": 42,
      "source_label": "Doanh thu thuần",
      "raw_text": "* Doanh thu thuần: 1.000 (Năm nay), 900 (Năm trước)",
      "confidence": 1.0
    }],
    "mapping": {
      "status": "mapped",
      "target_id": "INCOME.ENTERPRISE.NET_REVENUE",
      "method": "exact_label",
      "confidence": 1.0
    }
  }
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
