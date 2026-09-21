# VN-Financial-Markdown-Structural-Parser

Đọc báo cáo tài chính tiếng Việt ở dạng Markdown và xuất JSON có cấu trúc cho:

- **B01**: bảng cân đối kế toán;
- **B02**: báo cáo kết quả hoạt động kinh doanh;
- **B03**: báo cáo lưu chuyển tiền tệ;
- **Notes**: phần thuyết minh.

## Dữ liệu đầu vào

Parser nhận báo cáo tài chính tiếng Việt đã được chuẩn hóa ở dạng Markdown.
Markdown giữ lại heading, bảng, bullet, nhãn chỉ tiêu, kỳ báo cáo, giá trị và
phần thuyết minh để parser dựng lại cấu trúc B01/B02/B03 và Notes.

Việc thu thập tài liệu gốc và chuyển đổi sang Markdown là bước upstream; parser
tập trung vào đọc cấu trúc, nhận diện ngữ nghĩa, map schema và tạo output có
cấu trúc.

## Thông tin về example

Repository công bố một example synthetic để minh họa parser:

- **Input:** [`examples/synthetic_high_coverage_statement.md`](examples/synthetic_high_coverage_statement.md)
- **Output:** [`examples/output/`](examples/output/)
- **Kết quả mẫu:** [`evaluation_report_vi.md`](examples/output/evaluation_report_vi.md)
- **Tính chất dữ liệu:** hoàn toàn mô phỏng, có `synthetic_sample: true` và
  `Synthetic Data License 1.0`; không đại diện cho doanh nghiệp hoặc báo cáo
  tài chính thật.

Example synthetic là file minh họa có thể dùng để chạy thử parser mà không cần
chuẩn bị dữ liệu doanh nghiệp thật.

## Bắt đầu nhanh

Yêu cầu Python 3.10 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Runtime không có dependency ngoài Python standard library.
```

Chạy parser với một thư mục Markdown và bật Notes:

```powershell
python .\app\pipeline.py .\input `
  --output .\output\current `
  --notes
```

`input` có thể là một file Markdown hoặc một thư mục. Khi không truyền năm,
parser tự suy luận năm hiện tại và năm so sánh cho từng file.

Các lệnh thường dùng:

```powershell
# Chỉ chạy B01, B02 và B03
python .\app\pipeline.py .\input `
  --output .\output\current `
  --no-notes

# Ép cặp năm cho một lần chạy
python .\app\pipeline.py .\input `
  --output .\output\current `
  --current-year 2025 `
  --previous-year 2024

# Override sector cho B02
python .\app\pipeline.py .\input `
  --output .\output\current `
  --sector bank `
  --notes
```

Chạy Notes riêng:

```powershell
python .\app\run_notes.py .\input `
  --output .\output\notes_current `
  --write-ir
```

## Luồng hoạt động

```text
Markdown nguồn
  -> suy luận cặp kỳ báo cáo và đơn vị
  -> chọn scope riêng cho B01, B02, B03
  -> row-block pre-scan tùy chọn
       off    : bỏ qua scanner
       shadow : ghi boundary/coverage, không đổi kết quả
       assist : chỉ mở row window khi qua safety gate
  -> xử lý từng statement
       B01: dựng structural tree -> map -> recovery -> validate
       B02: đọc row -> map semantic -> validate
            assist hợp lệ thì đọc window; không đạt gate thì dùng toàn scope
       B03: đọc section -> map direct/indirect -> validate
            scanner chỉ bổ sung evidence, không tự map theo mã
  -> Notes đọc bổ sung, không ghi đè statement chính
  -> chuẩn hóa production contract
  -> ghi JSON report và manifest
```

`app/pipeline.py::main()` điều phối batch. `process_one()` suy luận kỳ/unit,
chạy B02, B03, B01, sau đó chạy Notes và tạo production report. Mỗi parser giữ
scope riêng để tránh trộn dữ liệu giữa các báo cáo.

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
Khi `--row-scan-mode assist` đạt gate, collector có thể xử lý từng row window;
collector cần toàn scope hoặc trường hợp không đạt gate sẽ dùng toàn scope.

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
6. xuất row-level CSV hoặc JSON.

Bullet được đọc như cây: thụt đầu dòng tạo parent và child, metadata gắn với
node gần nhất. Parser chỉ ghép các cụm cột khi section, cấu trúc và số slot
phù hợp.

## Cơ chế xử lý chính

### Same-label recovery

Khi nhãn cha và nhãn con giống nhau, parser kết hợp `hierarchy_path`, parent,
occurrence và alias giao nhau thay vì dùng nhãn đơn độc. Tính năng này bật mặc
định.

Trạng thái được ghi trong `debug.stats.same_label_recovery`,
`parser.same_label_recovery`.

### Schema profile

`schema_v1_7` là overlay có version trên schema mặc định. Overlay hiện bao gồm
các bổ sung BSI cho B01/B03 và alias có version cho B01/B02/B03. Các file overlay
nằm trong `resources/schemas/overlays/` và được materialize khi runtime chạy.

Runtime chọn profile bằng tùy chọn `--schema-profile`.

### Fast row-block scan

`src/common/row_block_scanner.py` là lớp tiền xử lý tùy chọn. Scanner xác định
block từ một anchor chỉ tiêu đến trước anchor kế tiếp; nó không tự quyết định
node cha, node con hay semantic identity. Các khoảng dòng chồng lấn được hợp
nhất trước khi tính `coverage`, nên metric không vượt quá 100%.

| Mode | Hành vi |
|---|---|
| `off` | Không chạy scanner. |
| `shadow` | Ghi boundary và coverage, không đổi kết quả map. |
| `assist` | Chỉ cho B02 dùng row window khi đạt gate coverage và không có mã mơ hồ; nếu không đạt, dùng collector toàn scope. |

B01 vẫn dùng structural tree làm nguồn quyết định. B03 chỉ giữ block làm
evidence, không map theo mã đơn độc.

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

Output production tập trung vào dữ liệu đã map, các observation chưa map,
provenance và trạng thái chất lượng của từng statement.

## Đọc code

Để đọc nhanh đường chạy production và biết mỗi phase gọi những file nào, xem
[`Bản đồ code theo phase`](docs/codebase-phase-map-vi.md).

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
│   └── data-publication-policy-vi.md # Thông tin sử dụng dữ liệu
├── examples/                    # Input/output synthetic để minh họa
│   ├── synthetic_high_coverage_statement.md
│   └── output/
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
├── requirements.txt             # Dependency runtime
```

## Giới hạn hiện tại

Markdown đầu vào có thể làm mất cột, hàng, kỳ hoặc quan hệ cha-con. Parser giữ
row chưa map và provenance, nhưng không tự điền khi evidence không đủ.

## Phiên bản

Package structural parser dùng version trong
[`flat_parser/version.py`](flat_parser/version.py):

```text
parser package: 0.6.0
```
