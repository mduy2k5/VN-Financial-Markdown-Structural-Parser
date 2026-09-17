# VN-Financial-Markdown-Structural-Parser

> Parser deterministic, source-first để trích xuất và chuẩn hóa Báo cáo tài chính Việt Nam từ Markdown được tạo bởi OCR/Vision-LLM.

Dự án xử lý đồng thời ba báo cáo chính:

- **B01 — Financial Position:** Bảng cân đối kế toán.
- **B02 — Income Statement:** Báo cáo kết quả hoạt động kinh doanh (KQKD).
- **B03 — Cash Flow:** Báo cáo lưu chuyển tiền tệ (LCTT).
- **Notes:** Thuyết minh báo cáo tài chính, được xuất thành Notes IR và các dòng phẳng để kiểm tra.

Bản parser hiện tại là **v23.1.0 — structural notes extraction**. Pipeline chạy trực tiếp trên Markdown nguồn, ghi lại provenance, suy luận niên độ theo từng báo cáo và không lấy output cũ làm dữ liệu đầu vào.

## Kết quả hiện tại

Phần này mô tả **kết quả kỹ thuật của lần chạy gần nhất**, không phải kết luận nghiệp vụ và không dùng tên, mã hay đặc điểm nhận diện của bộ dữ liệu. Số lượng file được phát hiện là biến động theo thư mục input; số liệu chính thức của từng lần chạy nằm trong `scan_manifest.json` và `comparison_summary.json`.

### 1. Sức khỏe vận hành

| Nhóm kiểm tra | Kết quả snapshot gần nhất | Ý nghĩa |
| :--- | :--- | :--- |
| Discovery | **100%** file được phát hiện có summary | Không có file nguồn bị bỏ qua ở bước điều phối |
| Provenance | **100%** kết quả có `source_sha256` | Có thể xác minh output thuộc đúng source đã parse |
| B01 | **100% `ok`** | Đường structural parser và source recovery đang hoạt động ổn định |
| B02 | **56,14% `ok`**, **43,86% `partial_mapping`** | Đã đọc được dòng nguồn nhưng còn dòng chưa ánh xạ đầy đủ vào schema semantic |
| B03 | **96,49% `ok`**, **1,75% `partial_mapping`**, **1,75% `partial_source_coverage`** | Cần tiếp tục xử lý layout, section hoặc method chưa đủ bằng chứng |
| Notes | **100% `parsed`** | Đây là lớp bổ sung, không ghi đè giá trị của ba bảng chính |
| Regression suite | **81 passed** | Code hiện tại vượt qua toàn bộ test tự động trong repository |

Các tỷ lệ trên được tính trên `N` file Markdown được discovery ở thời điểm chạy; `N` không phải tham số cố định và phải lấy từ manifest của lần chạy tương ứng.

Trạng thái `ok` chỉ cho biết pipeline hoàn tất và có dữ liệu đạt điều kiện tối thiểu. Nó không đồng nghĩa với việc mọi giá trị đều đúng tuyệt đối. Ngược lại, `partial_mapping` hoặc `partial_source_coverage` là tín hiệu cần review, không phải lỗi hệ thống hoàn toàn.

### 2. Độ bao phủ bằng chứng

Kết quả đối chiếu hiện tại với parser-assisted baseline:

| Bảng | Numeric pair match | Value-only coverage | Cách đọc |
| :--- | ---: | ---: | :--- |
| B01 | **96,90%** | **98,22%** | Bao phủ tốt, nhưng vẫn cần kiểm tra các dòng khác kỳ hoặc khác nhãn |
| B02 | **99,60%** | **99,60%** | Giá trị thu được ổn định trên các observation đủ điều kiện |
| B03 | **95,33%** | **96,90%** | Còn chênh lệch do section, method hoặc period pairing |

Hai metric không phải accuracy tuyệt đối:

- `Numeric pair match`: cùng semantic label, period và giá trị số sau chuẩn hóa.
- `Value-only coverage`: chỉ kiểm tra giá trị số, bỏ qua nhãn và kỳ; metric này dùng để phát hiện dữ liệu đã được thu nhưng có thể gán sai ngữ cảnh.
- `source_hash`: kiểm tra tính toàn vẹn của source, không kiểm tra tính đúng đắn kế toán.
- `status`: phản ánh mức hoàn tất của parser, không phải đánh giá chất lượng nghiệp vụ.

Baseline hiện tại vẫn là **parser-assisted baseline**, chưa phải gold standard được con người xác nhận hoàn toàn. Các observation mơ hồ về nhãn, kỳ, đơn vị hoặc nguồn phải được đưa vào review queue trước khi dùng cho báo cáo nghiệp vụ.

### 3. Diễn giải theo từng bảng

#### B01 — Financial Position

B01 hiện là bảng ổn định nhất về mặt cấu trúc. Parser dựng scope, cây parent/child, semantic anchor và cột kỳ trước khi tạo canonical node. Source recovery chỉ bổ sung observation còn thiếu và giữ lại provenance. Các điểm cần tiếp tục audit là:

- dòng bị tách thành nhiều cụm cột;
- cặp kỳ không nằm trên cùng một dòng;
- dòng tổng và dòng chi tiết có cấu trúc lồng nhau;
- conflict giữa canonical node và source observation.

#### B02 — Income Statement

B02 có độ bao phủ giá trị cao, nhưng trạng thái `partial_mapping` thường phản ánh việc extractor đã tìm thấy dòng nhưng mapper chưa thể xác định semantic node duy nhất. Nguyên nhân cần theo dõi gồm:

- nhãn bị OCR làm biến dạng;
- cùng một nhãn xuất hiện trong nhiều context;
- sector/schema không có node tương ứng;
- dòng current/previous bị tách khỏi nhãn;
- alias gần giống nhau nhưng chưa đủ margin để tự động chọn.

#### B03 — Cash Flow

B03 phụ thuộc đồng thời vào section và phương pháp dòng tiền. Một dòng có thể giống nhau về mặt chữ nhưng khác ý nghĩa nếu nằm ở section khác hoặc thuộc method khác. Các trạng thái partial thường cần kiểm tra:

- nhận diện direct/indirect;
- ranh giới giữa statutory section và supplemental section;
- period pairing trong bảng nhiều cột;
- bảng chỉ có mã biểu mẫu nhưng thiếu nhãn semantic;
- công thức có thành phần tùy chọn hoặc thiếu trong source.

### 4. Niên độ và provenance

Niên độ được suy luận độc lập cho từng tài liệu từ nội dung nguồn. Resolver ưu tiên ngày kết thúc kỳ, header kỳ và câu dẫn báo cáo; tên file chỉ là bằng chứng phụ trợ. Khi có xung đột, parser giữ lại `year_resolution`, `confidence` và `conflict` trong provenance thay vì tự động ghi đè.

### 5. Kết luận kỹ thuật

Kết quả hiện tại đủ tốt để tiếp tục phát triển parser và tạo hàng đợi review, nhưng chưa nên coi toàn bộ canonical output là kết luận nghiệp vụ tự động. Ưu tiên tiếp theo là:

1. review các observation `partial_mapping` và `partial_source_coverage`;
2. kiểm tra các conflict period/label bằng `source_line` và `raw_text`;
3. nâng baseline parser-assisted thành gold standard có người xác nhận;
4. chỉ công bố metric sau khi tách rõ lỗi thu dòng, lỗi period và lỗi semantic mapping.

## 1. Nguyên tắc thiết kế

### Source-first

Pipeline chỉ đọc các file Markdown trong thư mục input. Pipeline không tự quét project root, `output/`, ground truth hoặc các kết quả của lần chạy trước. Mỗi output mang theo:

- `source_name` và `source_sha256`;
- dòng nguồn và đoạn text gốc khi có thể;
- phương pháp mapping và độ tin cậy;
- `year_resolution` gồm bằng chứng, confidence và conflict.

### Không fix cứng theo báo cáo

- `current_year` và `previous_year` mặc định là `None`; mỗi file được suy luận độc lập.
- Năm được chọn từ ngày kết thúc kỳ, cột kỳ hiện tại/kỳ trước và các câu dẫn báo cáo. Năm trong tên file chỉ là bằng chứng bổ trợ hoặc candidate khi khác nội dung.
- Các ngày hành chính, ngày kiểm toán, ngày phát hành và ngày trong phần pháp lý bị giảm trọng số.
- Ngày đầu tháng 1 được nhận diện là số đầu kỳ; kỳ quý/YTD được phân loại riêng, không tự động coi là kỳ trước.
- Mã số biểu mẫu và số Thuyết minh không được dùng làm khóa identity, join, dedupe hoặc reconciliation. Chúng chỉ là metadata/provenance.

Các công cụ so sánh/review được tách khỏi runtime parser. Chúng chỉ đọc output hoặc ground truth khi được gọi tường minh sau một lần scan để đánh giá; không có đường fallback từ output về parser.

### Primary statements là nguồn chính

B01, B02 và B03 được parse trực tiếp từ source Markdown. Notes là lớp bổ sung: có thể link/reconcile với primary nhưng không ghi đè giá trị primary nếu không có bằng chứng nguồn phù hợp.

## 2. Flow xử lý

```text
md_reports/*.md
      │
      ▼
Discovery + đọc Markdown + SHA-256
      │
      ▼
Resolver niên độ/kỳ báo cáo theo từng file
      │
      ├── B01: structural recovery → semantic nodes → canonical
      ├── B02: scope/sector → row extraction → alias/semantic mapping → validation
      ├── B03: layout/sector detection → row extraction → cash-flow mapping
      └── Notes: scope → sections → blocks/table/bullet → Notes IR → row export
      │
      ▼
Source recovery + hydration + reconciliation + provenance
      │
      ▼
Canonical JSON theo từng báo cáo + summary CSV/JSON + manifest
```

Mỗi báo cáo có một resolver context chung để mọi engine dùng cùng current/previous period. Điều này tránh việc parser và evaluator suy luận hai cặp năm khác nhau.

## 3. Các engine

### B01 — Bảng cân đối kế toán

B01 xử lý cả bảng Markdown thông thường, bảng bị tách cột và cấu trúc bullet/OCR. Lớp structural recovery phục hồi section, parent/hierarchy, nhãn và hai slot kỳ trước khi ánh xạ sang semantic node. Kết quả được hydrate/reconcile từ source observation nhưng giữ lại raw text để kiểm toán.

Thư mục chính: `src/b01_financial_position/` và `flat_parser/`.

`flat_parser` có các chế độ debug:

- `v05`: pipeline hai lượt, tạo cây cấu trúc rồi ánh xạ ngữ nghĩa.
- `flow`: chuỗi pattern structural P1–P34.
- `hybrid`: dùng v05 làm nền và Flow fill các vị trí còn thiếu.
- `compare`: chạy và so sánh ba engine.

Các engine debug này phục vụ phân tích B01; pipeline thống nhất vẫn là `pipeline.py` với Markdown làm nguồn duy nhất.

### B02 — KQKD

B02 trước hết xác định phạm vi báo cáo và sector (`bank`, `enterprise`, `securities`, `insurance`). Sau đó extractor thu các dòng từ bảng/bullet/plain OCR, mapper chuẩn hóa nhãn bằng alias chính xác, regex có biên và semantic overlap có ngưỡng/margin. Validator kiểm tra cấu trúc và các quan hệ công thức khi có đủ dữ liệu.

Mapping không phụ thuộc ticker hoặc mã biểu mẫu; `form_code` chỉ được giữ để truy vết.

Thư mục chính: `src/b02_income/`.

### B03 — LCTT

B03 tự phát hiện scope/sector từ chính phần LCTT, phân biệt dòng tiền statutory với supplemental/customer/broker sections và phục hồi các layout column-major. Extractor lấy giá trị theo hai vector kỳ, mapper dùng schema/alias LCTT và giữ riêng các nhóm có cùng mã biểu mẫu nhưng khác ngữ nghĩa.

Thư mục chính: `src/b03_cashflow/`.

### Notes — Thuyết minh

Notes pipeline gồm các lớp:

1. `scanner` tìm phạm vi Thuyết minh.
2. `sectionizer` chia theo đề mục.
3. `block_classifier` nhận diện bảng, bullet, plain OCR và movement block.
4. `table_parser`/`structural_parser` tách nhãn, hierarchy, đơn vị và các slot kỳ.
5. `linker` liên kết với primary khi có bằng chứng; `reconciliation` chỉ tạo đề xuất có provenance.
6. `row_exporter` xuất dòng phẳng CSV/JSON để review và xây ground truth.

Bullet được xử lý như cấu trúc cây: thụt đầu dòng tạo parent/child context, dòng `Thuyết minh` là metadata của node, còn các dòng `Tại ngày`, `Năm nay`, `Năm trước` được tách thành giá trị theo period. Nếu layout bị tách thành nhiều cụm cột, parser chỉ ghép khi section, cấu trúc và số lượng slot nhất quán.

Thư mục chính: `src/notes/`.

## 4. Cấu trúc repository

```text
Flatten/
├── pipeline.py                         # Entry point cho B01 + B02 + B03 + Notes
├── run_debug.py                        # Chạy/debug các engine B01
├── run_notes.py                        # CLI riêng cho Notes
├── src/
│   ├── b01_financial_position/         # Bảng cân đối và source integration
│   ├── b02_income/                     # Scope, extractor, mapper, validator
│   ├── b03_cashflow/                   # Extractor và mapper LCTT
│   ├── common/                          # Period, source recovery, identity, reconciliation
│   └── notes/                           # Notes IR, structural parser, linking, export
├── flat_parser/                        # Engine structural/debug cho B01
├── resources/                          # Schema, alias và structural guide
├── md_reports/                         # Markdown nguồn do người dùng cung cấp
├── ground_truth/                       # Baseline, Notes GT và review artifacts
├── output/                             # Artifact chạy cục bộ, được gom theo nhóm
├── scripts/                            # Demo, build GT, compare, audit/review
├── tests/                              # Regression suite hiện hành
│   └── legacy/                         # Test cũ, không chạy mặc định
├── samples/                            # Fixture kiểm thử nhỏ
├── DEMO_GUIDE.md
├── VERSION.txt
└── requirements.txt
```

Các schema/alias chính trong `resources/`:

- `universal_financial_position_schema_v1_6.json` và alias tương ứng;
- `income_statement_schema.json` và `income_statement_aliases.json`;
- `cash_flow_schema.json` và `cash_flow_aliases.json`;
- schema/alias supplemental ngân hàng và `universal_structural_guide_a1_a5.json`.

## 5. Cài đặt

Yêu cầu Python 3.10 trở lên, khuyến nghị 3.11 hoặc 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
```

`requirements.txt` hiện chỉ yêu cầu `pytest`; parser runtime sử dụng thư viện chuẩn Python và các resource JSON trong repository.

## 6. Chạy pipeline

### Demo toàn bộ báo cáo trong input

```powershell
python .\scripts\run_demo.py
```

Lệnh mặc định tương đương:

```powershell
python .\scripts\run_demo.py `
  --input .\md_reports `
  --output .\output\demo\latest
```

Chỉ định output khác hoặc tắt Notes:

```powershell
python .\scripts\run_demo.py `
  --input .\md_reports `
  --output .\output\demo\my_run `
  --no-notes
```

Không cần truyền năm nếu muốn dùng resolver tự động. Có thể truyền `--current-year` và `--previous-year` cho một batch kiểm thử có kiểm soát; đây là override tường minh, không phải cấu hình mặc định.

### Pipeline production trực tiếp

```powershell
python .\pipeline.py .\md_reports `
  --output .\output\comparisons\current_run `
  --notes
```

`--sector auto` là mặc định. Có thể dùng `--sector bank|enterprise|securities|insurance` để override sector cho B02; B03 vẫn phát hiện scope độc lập.

## 7. Debug engine B01

```powershell
# Chạy từng engine
python .\run_debug.py .\md_reports --mode v05 --output .\output\demo\v05
python .\run_debug.py .\md_reports --mode flow --output .\output\demo\flow
python .\run_debug.py .\md_reports --mode hybrid --output .\output\demo\hybrid

# So sánh engine
python .\run_debug.py .\md_reports --mode compare --output .\output\demo\engine_compare

# Bật strict regex fallback sau alias mapping
python .\run_debug.py .\md_reports `
  --mode hybrid `
  --mapping-strategy alias-regex-fallback `
  --output .\output\demo\mapping_fallback
```

## 8. Ground truth và đối chiếu

### Xây Notes ground truth

```powershell
python .\scripts\build_notes_ground_truth.py `
  .\md_reports `
  --output .\ground_truth\notes
```

Năm được suy luận theo từng source file nếu không truyền override.

### Tạo gold-candidate và review queue

```powershell
python .\scripts\prepare_main_statement_gold.py `
  --baselines .\ground_truth\main_statements `
  --source-dir .\md_reports `
  --output .\output\evaluations\main_statement_gold_queue
```

Lệnh này không ghi đè baseline. Các observation thiếu giá trị, mơ hồ về kỳ/nhãn, supplemental hoặc có conflict được tách sang review queue.

### So sánh ba bảng chính

```powershell
python .\scripts\compare_main_statement_ground_truth.py `
  --ground-truth .\ground_truth\main_statements `
  --current .\output\demo\latest\results `
  --ground-truth-mode eligible `
  --sources .\md_reports `
  --report .\output\evaluations\comparison_main_statements.json
```

Hai chế độ:

- `raw`: giữ toàn bộ observation đã lưu trong baseline.
- `eligible`: loại observation không đủ điều kiện hoặc cần review khỏi chỉ số chính.

Comparator so sánh bằng chứng chuẩn hóa `label + period + value`, báo riêng `missing` và `unexpected`, đồng thời kiểm tra source hash. Kết quả không nên được đọc như tỷ lệ đúng tuyệt đối nếu baseline chưa được human-review.

### Đánh giá Notes coverage

```powershell
python .\scripts\evaluate_notes_coverage.py .\md_reports `
  --output .\output\evaluations\notes_coverage `
  --write-per-file
```

## 9. Cấu trúc output

Demo mặc định tạo:

```text
output/demo/latest/
├── scan.log
├── scan_summary.md
├── scan_manifest.json
└── results/
    ├── run_metadata.json
    ├── comparison_summary.json
    ├── comparison_summary.csv
    ├── <report>.comparison.json
    ├── <report>.financial_position.canonical.json
    ├── <report>.income.canonical.json
    ├── <report>.cashflow.canonical.json
    ├── <report>.notes.ir.json
    └── notes_rows/<report>.notes_rows.csv
```

`scan_manifest.json` là chỉ mục trung tâm, ghi trạng thái từng báo cáo, cặp năm được suy luận và đường dẫn tới tất cả artifact. Các artifact đánh giá thường nằm tại `output/evaluations/`; snapshot cũ nằm trong `output/archive/` khi được lưu riêng.

Ground truth được tổ chức độc lập với output chạy:

```text
ground_truth/
├── main_statements/                    # Baseline ba bảng chính
├── notes/                              # Notes ground truth theo báo cáo
├── notes_gold/                         # Gold/candidate đã lọc nếu có
└── ...                                 # Audit/review queues và snapshot
```

Output và ground truth sinh cục bộ được Git bỏ qua để tránh commit nhầm dữ liệu lớn. Có thể tái tạo chúng từ `md_reports/` bằng các lệnh ở trên.

## 10. Canonical schema và provenance

Ví dụ rút gọn một canonical statement:

```json
{
  "statement_type": "INCOME_STATEMENT",
  "unit": "million_vnd",
  "periods": {
    "current": 2025,
    "previous": 2024
  },
  "nodes": [
    {
      "node_id": "INCOME.BANK.NET_INTEREST_INCOME",
      "canonical_name": "Thu nhập lãi thuần",
      "value": {
        "current": 5088792,
        "previous": 3035257
      },
      "extraction_meta": {
        "occurrences": [
          {
            "source_line": 3,
            "source_label": "Thu nhập lãi thuần",
            "mapping_method": "exact_alias"
          }
        ]
      }
    }
  ],
  "source_name": "<report>.md",
  "source_sha256": "<sha256>"
}
```

Giá trị được chuẩn hóa dấu âm, dấu phân cách và đơn vị nhưng không nội suy số liệu. `source_line`, `raw_text`, occurrence và mapping metadata cho phép quay lại Markdown nguồn. `canonical_mutated`/hydration metadata nếu có phải được đọc cùng provenance để phân biệt giá trị gốc và giá trị được phục hồi cấu trúc.

## 11. Kiểm thử

```powershell
# Unit/regression suite
python -m pytest -q

# Kiểm tra cú pháp
python -m compileall -q .

# Kiểm tra whitespace trong diff
git diff --check
```

Regression suite hiện hành gồm các nhóm: structural edge cases, identity không phụ thuộc mã, period/year inference, source-only integrity, B01 recovery, B02 semantics, B03 cash-flow fidelity và Notes structural/coverage.

## 12. Quy trình review trước khi dùng nghiệp vụ

1. Chạy pipeline source-first trên Markdown mới.
2. Kiểm tra `scan_manifest.json`: số file, status, source hash, period confidence và conflict.
3. Đối chiếu `eligible` để phát hiện missing/unexpected theo từng bảng.
4. Mở review queue và kiểm tra các dòng cần adjudication bằng raw text/source line.
5. Chỉ sau khi các conflict trọng yếu được xác nhận mới dùng canonical output cho kết luận nghiệp vụ.

Các báo cáo có `partial_mapping`, `partial_source_coverage`, confidence thấp hoặc conflict niên độ không nên tự động được coi là đã hoàn thiện.

## 13. Tài liệu liên quan

- [DEMO_GUIDE.md](DEMO_GUIDE.md): chạy demo và cấu trúc artifact.
- [VERSION.txt](VERSION.txt): phiên bản và phạm vi release.
- `scripts/`: các lệnh build ground truth, compare, audit và review.
- `tests/`: regression suite hiện hành.
