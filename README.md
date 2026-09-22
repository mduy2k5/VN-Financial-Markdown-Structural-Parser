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

Markdown được tạo ở bước upstream bằng LLM từ tài liệu báo cáo tài chính gốc.
Do quá trình sinh nội dung không hoàn toàn ổn định, Markdown có thể bị mất
cột, mất hàng, sai thứ tự, thiếu kỳ báo cáo hoặc làm biến dạng quan hệ cha-con.
Parser tập trung vào đọc cấu trúc, nhận diện ngữ nghĩa, map schema, kiểm tra
bằng chứng và giữ lại các dòng chưa map khi dữ liệu đầu vào chưa đủ chắc chắn.

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

Với thuyết minh ngân hàng, `--notes-alias-profile auto` bật catalog
`bank_v1` trong [`resources/schemas/notes_aliases_bank_v1.json`](resources/schemas/notes_aliases_bank_v1.json).
Với doanh nghiệp, cùng tùy chọn bật `enterprise_v1` trong
[`resources/schemas/notes_aliases_enterprise_v1.json`](resources/schemas/notes_aliases_enterprise_v1.json),
được xây từ mẫu B09/DN cùng các biến thể quan sát được ở bộ báo cáo doanh
nghiệp. Catalog doanh nghiệp khớp theo cả mã mục và tiêu đề vì B09 dùng lại
các số 1, 2, ... ở nhiều nhóm; tiêu đề tiếp theo được coi là phần tiếp của
cùng mục.

Với công ty chứng khoán, tùy chọn auto bật profile securities_v1 trong
[resources/schemas/notes_aliases_securities_v1.json](resources/schemas/notes_aliases_securities_v1.json).
Profile này dựa trên mẫu BCTC-CK và xử lý cả kiểu đánh số BSI (5–36) lẫn CTS
(3.x–12). Các mục lặp được đối chiếu bằng cả mã và tiêu đề; bảng nhiều cột
vẫn giữ nguyên ở raw_matrix.

Với công ty bảo hiểm, tùy chọn auto bật profile insurance_v1 trong
[resources/schemas/notes_aliases_insurance_v1.json](resources/schemas/notes_aliases_insurance_v1.json).
Profile dùng chung cho báo cáo kết hợp bảo hiểm nhân thọ và phi nhân thọ,
đồng thời bao phủ một số nhóm chỉ tiêu có hình thức giống doanh nghiệp như
thuế, vốn chủ sở hữu, tài sản cố định, chi phí quản lý và bên liên quan. Hai
mẫu nguồn được đối chiếu là BCTC-BHNT và BCTC-BHPNT; các bảng nhiều cột vẫn
được giữ nguyên ở raw_matrix.

Alias chỉ là metadata khớp exact trong đúng section. Dòng không có alias vẫn
được giữ ở `raw_tree`; bảng nhiều cột giữ `headers`, `raw_cells`, thứ tự giá
trị, kỳ và `source_column`. Có thể rollback lớp alias bằng
`--notes-alias-profile none`; parser Notes và B01/B02/B03 không bị thay đổi.

## Cơ chế xử lý chính

### Same-label recovery

Khi nhãn cha và nhãn con giống nhau, parser kết hợp `hierarchy_path`, parent,
occurrence và alias giao nhau thay vì dùng nhãn đơn độc. Tính năng này bật mặc
định.

Trạng thái được ghi trong `debug.stats.same_label_recovery`,
`parser.same_label_recovery`.

### Schema profile

`schema_v1_11` là overlay có version trên schema mặc định. Overlay bổ sung các
nhánh B01 còn thiếu (đặc biệt các dòng phải trả nội bộ ngắn/dài hạn và dự phòng
rủi ro khác của ngân hàng), alias B01 cho biến thể dấu `(*)`/cách viết theo
mẫu, các dòng B02 chứng khoán bị thiếu, nhóm B03 trực tiếp và đầy đủ các dòng
B03 gián tiếp của công ty chứng khoán, đồng thời hoàn thiện alias B03 trực tiếp
và gián tiếp của ngân hàng. Các công thức B03 gián tiếp cũ được giữ nguyên
trong overlay mới. `schema_v1_10`, `schema_v1_9`, `schema_v1_7` và `baseline`
vẫn có thể chọn để rollback. Các file overlay nằm trong
`resources/schemas/overlays/` và được materialize khi runtime chạy.

Runtime chọn profile bằng tùy chọn `--schema-profile`.

Notes chạy bằng pipeline riêng, không mở rộng schema của B01/B02/B03. Có thể
chọn `--notes-parser-mode v2` để giữ cây cha-con, kỳ, measure và các giá trị
movement đầy đủ; mặc định `legacy` để bảo toàn hành vi hiện tại và có thể
rollback ngay bằng cách bỏ tùy chọn.

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
provenance và trạng thái chất lượng của từng statement. Notes bổ sung
`rows[].source.raw_cells`, `rows[].metadata.parser_metadata` và
`raw_blocks` để các dòng không có alias hoặc phần văn bản không có số không bị
mất khỏi output.

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
│   ├── notes-bank-alias-policy-vi.md # Chính sách alias Notes ngân hàng
│   ├── notes-enterprise-alias-policy-vi.md # Chính sách alias Notes doanh nghiệp
│   ├── notes-securities-alias-policy-vi.md # Chính sách alias Notes công ty chứng khoán
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
