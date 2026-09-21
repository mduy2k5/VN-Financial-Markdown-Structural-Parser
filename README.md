# VN-Financial-Markdown-Structural-Parser

Đọc báo cáo tài chính tiếng Việt ở dạng Markdown và xuất JSON có cấu trúc cho:

- **B01**: bảng cân đối kế toán;
- **B02**: báo cáo kết quả hoạt động kinh doanh;
- **B03**: báo cáo lưu chuyển tiền tệ;
- **Notes**: phần thuyết minh.

Dữ liệu báo cáo đầu vào chỉ đến từ Markdown nguồn. Runtime không đọc output,
ground truth hoặc kết quả của lần chạy trước. Logic parser cũng không chọn theo
tên file, ticker hay giá trị đã biết.

## Bản đồ code theo phase

Để đọc nhanh đường chạy production và biết mỗi phase gọi những file nào, xem
[`docs/codebase-phase-map-vi.md`](docs/codebase-phase-map-vi.md). Tài liệu này
phân biệt critical path production với các script ground truth, evaluation,
maintenance và visualization; không thay đổi layout import của code.

## Thông tin về example

Example synthetic dùng để regression và bộ input/output kiểm tra chỉ tồn tại
trong checkout nội bộ; không nằm trong public production release. Dữ liệu này
hoàn toàn mô phỏng, có `synthetic_sample: true` và `Synthetic Data License 1.0`,
không đại diện cho doanh nghiệp hoặc báo cáo tài chính thật.

Bộ 57 file báo cáo thật vẫn là dữ liệu nội bộ, không nằm trong repository công
khai. Vì vậy kết quả bên dưới tách riêng kết quả kiểm tra nội bộ và kết quả của
example synthetic.

## Kết quả kiểm tra

### Bộ 57 file nội bộ

Batch `schema_v1_7` trên 57 file Markdown ngày 21/09/2026 cho chỉ số nhận diện
trung bình khoảng **96,7%**. Chỉ số này là `coverage_avg`: tỷ lệ trung bình
các chỉ tiêu có đủ giá trị ở hai kỳ trong bộ đánh giá; đây không phải accuracy
được xác nhận thủ công cho mọi loại nguồn.

| Hạng mục | Kết quả |
|---|---:|
| File được nhận | 57/57 |
| Chỉ số nhận diện trung bình | khoảng 96,7% |
| Row-block canary so với baseline | 0 khác biệt giá trị node |
| Runtime | 0 lỗi |
| Regression suite | **141 passed** |

Các file còn trạng thái review được giữ nguyên để kiểm tra source evidence,
quan hệ cha-con, kỳ báo cáo hoặc công thức. Parser không tự điền khi Markdown
không đủ bằng chứng.

### Example synthetic

Example chạy thành công qua pipeline đầy đủ với B01, B02, B03 và Notes:

| Hạng mục | Kết quả |
|---|---:|
| Input | 1 file synthetic |
| B01 | `ok`; 60 observations; coverage hai kỳ 100%/100% |
| B02 | 18/18 dòng map; coverage hai kỳ 100%/100%; công thức 7/7 pass |
| B03 | 20/20 dòng map; coverage hai kỳ 100%/100%; công thức 2/2 pass |
| Notes | `parsed`; 31 sections; 17 links; confidence 0,97 |
| Quality gate | `ok`; `eligible_for_use=true` cho fixture synthetic |
| Lỗi và xung đột kỳ | 0 |

Kết quả example chỉ chứng minh pipeline hoạt động đúng trên fixture mô phỏng;
không phải xác nhận pháp lý, kế toán hoặc chất lượng của dữ liệu doanh nghiệp
thật.

## Bắt đầu nhanh

Yêu cầu Python 3.10 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Runtime không có dependency ngoài Python standard library.
```

Chạy toàn bộ Markdown và bật Notes:

```powershell
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --notes
```

`input` có thể là một file Markdown hoặc một thư mục. Khi không truyền năm,
parser tự suy luận năm hiện tại và năm so sánh cho từng file.

Các lệnh thường dùng:

```powershell
# Chỉ chạy B01, B02 và B03
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --no-notes

# Ghi thêm artifact phục vụ điều tra
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --notes `
  --audit

# Ép cặp năm cho một lần chạy
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --current-year 2025 `
  --previous-year 2024

# Override sector cho B02
python .\app\pipeline.py .\md_reports `
  --output .\output\current `
  --sector bank `
  --notes
```

Chạy Notes riêng:

```powershell
python .\app\run_notes.py .\md_reports `
  --output .\output\notes_current `
  --write-ir
```

## Luồng hoạt động

```text
Markdown nguồn
  -> chọn file và tạo source hash
  -> suy luận cặp kỳ báo cáo và đơn vị
  -> chọn scope riêng cho B01, B02, B03
  -> row-block pre-scan tùy chọn
       off    : bỏ qua scanner
       shadow : ghi boundary/coverage, không đổi kết quả
       assist : chỉ mở row window khi qua safety gate
  -> xử lý từng statement
       B01: dựng structural tree -> map -> recovery -> validate
       B02: đọc row -> map semantic -> validate
            assist hợp lệ thì đọc window; lệch kết quả thì đọc lại toàn scope
       B03: đọc section -> map direct/indirect -> validate
            scanner chỉ bổ sung evidence, không tự map theo mã
  -> ghép source recovery và reconciliation
  -> Notes đọc bổ sung, không ghi đè statement chính
  -> chuẩn hóa production contract
  -> ghi report JSON, manifest và audit artifact
```

`app/pipeline.py::main()` điều phối batch. `process_one()` đọc source một lần,
chạy B02, B03, B01, sau đó mới chạy Notes và tạo production report. Các parser
giữ scope riêng; audit không trở thành input cho lần chạy sau.

### B01: Financial Position

`flat_parser/` xử lý bảng Markdown, dòng bị tách cột và bullet/OCR theo chuỗi:

1. chuẩn hóa dòng và lọc nhiễu;
2. tìm scope và bảng ứng viên;
3. dựng cây node, nhận diện cấu trúc và gán period/unit;
4. tạo canonical nodes và kiểm tra tổng tài sản, tổng nguồn vốn;
5. chạy source recovery cho các row còn có evidence trong source.

`src/b01_financial_position/extractor.py` là adapter của B01 và điểm nối với
source recovery. Row-block scanner chỉ ghi evidence cho B01; structural tree
vẫn là nguồn quyết định quan hệ cha-con và semantic identity.

### B02: Income Statement

B02 tìm scope và sector, đọc row từ bảng, bullet hoặc plain OCR, rồi map vào
schema theo semantic match và alias. Validator kiểm tra coverage và công thức
khi đủ dữ liệu. Các sector được hỗ trợ là `bank`, `enterprise`, `securities`
và `insurance`.

`form_code` chỉ phục vụ truy vết. Nó không quyết định identity của row.
Khi `--row-scan-mode assist` đạt gate, các collector đọc từng row window;
collector cần toàn scope vẫn đọc toàn scope. Kết quả window được so với đường
đọc đầy đủ; nếu khác, B02 dùng lại đường đầy đủ.

### B03: Cash Flow

B03 phát hiện scope, sector và phương pháp direct hoặc indirect. Parser tách
statutory section khỏi supplemental, customer hoặc broker section; các row có
cùng mã nhưng khác ngữ nghĩa vẫn được giữ riêng. Hai vector kỳ chỉ được ghép
sau khi kiểm tra cấu trúc. Row-block scanner chỉ gắn provenance/evidence và
không thay mapper quyết định identity.

### Notes

Notes là lớp bổ sung, không ghi đè B01, B02 hoặc B03. Pipeline Notes:

1. tìm vùng thuyết minh;
2. chia section theo đề mục;
3. phân loại bảng, bullet, OCR và movement block;
4. đọc label, hierarchy, unit và period;
5. link với primary statement và giữ provenance;
6. xuất row-level CSV hoặc JSON để review.

Bullet được đọc như cây: thụt đầu dòng tạo parent và child, metadata gắn với
node gần nhất. Parser chỉ ghép các cụm cột khi section, cấu trúc và số slot
phù hợp.

## Các rào chắn dữ liệu

### Same-label recovery

Khi nhãn cha và nhãn con giống nhau, parser kết hợp `hierarchy_path`, parent,
occurrence và alias giao nhau thay vì dùng nhãn đơn độc. Tính năng này bật mặc
định. Chạy baseline để so sánh hoặc rollback:

```powershell
python -m app.pipeline .\md_reports `
  --output .\output\baseline `
  --no-same-label-recovery
```

Trạng thái được ghi trong `debug.stats.same_label_recovery`,
`parser.same_label_recovery` và `audit/run_metadata.json` khi bật audit.

### Schema profile

`schema_v1_7` là overlay có version trên schema baseline. Overlay hiện bao gồm
các bổ sung BSI cho B01/B03 và alias có version cho B01/B02/B03. Các file overlay
nằm trong `resources/schemas/overlays/` và được materialize khi runtime chạy.

Rollback về baseline:

```powershell
python -m app.pipeline .\md_reports `
  --output .\output\baseline `
  --schema-profile baseline
```

Mỗi audit run ghi profile và đường dẫn schema trong
`audit/run_metadata.json`. Nên ghi output baseline và overlay vào hai thư mục
khác nhau khi so sánh.

### Fast row-block scan

`src/common/row_block_scanner.py` là lớp tiền xử lý tùy chọn. Scanner xác định
block từ một anchor chỉ tiêu đến trước anchor kế tiếp; nó không tự quyết định
node cha, node con hay semantic identity. Các khoảng dòng chồng lấn được hợp
nhất trước khi tính `coverage`, nên metric không vượt quá 100%.

| Mode | Hành vi |
|---|---|
| `off` | Không chạy scanner; mặc định và là đường baseline. |
| `shadow` | Ghi boundary và coverage vào audit, không đổi kết quả map. |
| `assist` | Chỉ cho B02 dùng row window khi đạt gate coverage và không có mã mơ hồ; nếu không đạt, dùng collector toàn scope. |

B01 vẫn dùng structural tree làm nguồn quyết định. B03 chỉ giữ block làm
evidence, không map theo mã đơn độc.

Batch canary 57 file cho thấy canonical values không thay đổi so với baseline.
`assist` chỉ được chấp nhận sau khi kết quả window bằng kết quả đọc toàn scope;
trường hợp không bằng sẽ fallback. Vì đường kiểm chứng toàn scope vẫn được giữ,
chưa dùng batch này để kết luận parser đã nhanh hơn.

Chạy canary:

```powershell
python -m app.pipeline md_reports `
  --output output/row_scan_shadow `
  --audit --no-notes `
  --schema-profile schema_v1_7 `
  --row-scan-mode shadow

python -m app.pipeline md_reports `
  --output output/row_scan_assist `
  --audit --no-notes `
  --schema-profile schema_v1_7 `
  --row-scan-mode assist
```

Trước khi bật `assist`, so sánh `comparison_summary.csv`, canonical values,
conflict và runtime với baseline. Rollback bằng `--row-scan-mode off`.

## Output

Production output có dạng:

```text
output/current/
├── manifest.json
└── reports/
    ├── <source-stem>__<sha256-prefix>.json
    └── ...
```

`manifest.json` ghi contract version, số report, source hash, kỳ báo cáo và
đường dẫn tới từng report. Mỗi report dùng contract
`vn_financial_report_output@2.0.0` với các phần:

```text
contract, report, periods, statements, notes, quality
```

Mỗi statement có `items` và `observations`:

- `items`: node đã map semantic;
- `observations`: row nguồn chưa map hoặc cần reconcile;
- `value`: giá trị theo kỳ;
- `provenance`: evidence, source line và mapping;
- `raw_text`: dòng Markdown dùng để truy lại source.

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
            "mapping": {"status": "mapped", "method": "exact_label", "confidence": 1.0}
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

Output production không chứa raw IR, mapping score hoặc bảng so sánh. Dùng
`--audit` khi cần điều tra; audit được ghi trong `<output>/audit/` và có thể
chứa canonical JSON, comparison, Notes rows, metrics, summary và
`error_taxonomy`.

Viewer, evaluation, ground-truth, test, example và các báo cáo điều tra là
workflow nội bộ. Checkout nội bộ có thể giữ các file này để review và tái tạo
kết quả. Public production release chỉ chứa parser, runtime resources, schema,
compiled guide và tài liệu vận hành cốt lõi.

## Ground truth và đối chiếu nội bộ

Ground truth chỉ dùng để đánh giá; runtime không đọc ground truth. Baseline
chưa được human-review không phải gold standard. Các tool tạo ground truth,
review queue và so sánh output được giữ ở checkout nội bộ, không phát hành
trong public repository.

## Tài liệu production

- [Bản đồ code theo phase](docs/codebase-phase-map-vi.md)
- [Chính sách dữ liệu](docs/data-publication-policy-vi.md)

## Đọc code

Để theo dõi một file từ đầu đến output, đọc theo thứ tự:

1. `app/pipeline.py::main()` chọn input, nhận option và điều phối batch.
2. `app/pipeline.py::process_one()` đọc source, suy luận kỳ/unit và ghép các statement.
3. `app/pipeline.py::run_income()` chạy B02 và gọi row-block scan khi mode khác `off`.
4. `src/common/row_block_scanner.py::scan_row_blocks()` tạo boundary/evidence; B02 chỉ dùng window sau safety gate.
5. `app/pipeline.py::run_cashflow()` chạy B03; scanner chỉ bổ sung evidence.
6. `src/b01_financial_position/extractor.py::FinancialPositionSourceParser.parse_text()` nối B01 với structural parser.
7. `flat_parser/pipeline.py::FlatParserPipeline.parse_text()` dựng và map cây B01.
8. `src/common/source_recovery.py` và `src/common/source_reconciler.py` xử lý row còn evidence và conflict.
9. `src/notes/pipeline.py::NotesPipeline.parse_text()` chạy Notes IR và linking.
10. `src/common/output_contract.py::build_production_report()` tạo report JSON.
11. `src/common/output_contract.py::manifest_entry()` tạo dòng manifest.

## Cây thư mục

```text
Flatten/
├── app/                         # CLI và batch orchestration
│   ├── pipeline.py              # Điều phối toàn bộ production flow
│   └── run_notes.py             # Chạy Notes riêng
├── docs/
│   ├── README.md                # Chỉ mục tài liệu
│   ├── codebase-phase-map-vi.md # Luồng production theo phase
│   └── data-publication-policy-vi.md # Chính sách dữ liệu public
├── src/
│   ├── b01_financial_position/  # Adapter, cây và recovery B01
│   ├── b02_income/              # Extractor, mapper, validator B02
│   ├── b03_cashflow/            # Extractor, mapper, validator B03
│   ├── common/                  # Kỳ, recovery, output, metrics, row scanner
│   │   └── row_block_scanner.py # Index vùng chỉ tiêu tùy chọn
│   └── notes/                   # Scanner, parser, link và export Notes
├── flat_parser/                 # Structural parser và locator dùng chung
│   └── version.py               # Version của package parser
├── resources/
│   ├── schemas/                 # Schema, alias và production contract
│   └── guides/compiled/         # Structural guide đã compile cho runtime
├── md_reports/                  # Markdown input cục bộ
├── ground_truth/                # Baseline và review queue cục bộ
├── output/                      # Output chạy cục bộ
│   ├── reports/                 # Production JSON
│   └── audit/                   # Canonical, comparison và row-block evidence
├── requirements.txt             # Dependency runtime
```

`md_reports/`, `ground_truth/` và `output/` chỉ dùng ở local và được Git bỏ
qua. Runtime đọc `md_reports/` và ghi `output/`.

## Kiểm thử và review

```powershell
python -m compileall -q app src flat_parser
git diff --check
```

Bộ test, `pytest.ini` và các artifact đánh giá được giữ ở checkout nội bộ,
không thuộc public production release.

Khi phát triển rule mới trong checkout nội bộ:

1. viết test cho layout hoặc lỗi mới;
2. dùng cấu trúc và semantic context, không dùng tên file;
3. kiểm tra provenance và period pairing;
4. chạy toàn bộ test;
5. cập nhật schema hoặc guide nếu rule áp dụng chung.

Trước khi dùng output cho nghiệp vụ:

1. chạy pipeline trên Markdown nguồn;
2. kiểm tra `manifest.json` và report tương ứng;
3. bật `--audit` khi cần so sánh hoặc điều tra;
4. xem `missing`, `unexpected`, `raw_text`, `source_line`, period và conflict;
5. review report có `partial_mapping`, `partial_source_coverage`, confidence thấp hoặc conflict niên độ;
6. chỉ sử dụng kết quả sau khi review xong các conflict quan trọng.

## Giới hạn hiện tại

Markdown đầu vào có thể làm mất cột, hàng, kỳ hoặc quan hệ cha-con. Parser giữ
row chưa map và provenance để review, nhưng không đoán khi evidence không đủ.
Vì vậy status và coverage phải được đọc cùng với source line, raw text và audit
artifact.

## Phiên bản

Package structural parser dùng version trong
[`flat_parser/version.py`](flat_parser/version.py):

```text
parser package: 0.6.0
```

Thông tin release metadata bổ sung được giữ ở máy local và không nằm trong
public release artifact. Repository lưu code, schema, guide và test; dữ liệu
nguồn, ground truth và output cục bộ không thuộc release artifact.
