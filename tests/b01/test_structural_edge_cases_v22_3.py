from src.b02_income import extract_income_fallback
from src.common import (
    extract_financial_position_source_rows,
    extract_generic_statement_rows,
    extract_securities_supplemental_cashflow_rows,
)
from src.common.source_canonical_hydrator import augment_canonical_with_recovered_rows
from src.common.source_recovery import RecoveredRow


INCOME_FRAGMENTED_SAMPLE = """
# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT

Các khoản điều chỉnh giảm doanh thu  
02  
26  
(200)  
(180)

Thu nhập tài chính  
21  
28  
300  
250
"""


FINANCIAL_POSITION_SAMPLE = """
# BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT

| Chỉ tiêu | Mã số | TM | 31/12/2025 | 01/01/2025 |
|---|---:|---:|---:|---:|
| Các khoản phải thu khác | 135 |  | 180 | 160 |
| Dự phòng tổn thất các khoản phải thu | 137 |  | (60) | (50) |
| C. NỢ PHẢI TRẢ | 300 |  | 5650 | 4900 |
| Tài sản ngắn hạn khác | 155 |  | 30 | 30 |
| Tài sản dài hạn khác | 268 |  | 60 | 40 |
"""


def _by_code(rows, code):
    return [r for r in rows if getattr(r, "code", None) == code]


def test_income_fragmented_vertical_note_column():
    out = extract_income_fallback(INCOME_FRAGMENTED_SAMPLE, 2025, 2024)
    rows = out["rows"]

    r02 = next(r for r in rows if r.get("code") == "02" and "điều chỉnh giảm" in r.get("indicator", "").lower())
    assert r02["current"] == "(200)"
    assert r02["previous"] == "(180)"
    assert r02["note"] == "26"

    r21 = next(r for r in rows if r.get("code") == "21" and "thu nhập tài chính" in r.get("indicator", "").lower())
    assert r21["current"] == "300"
    assert r21["previous"] == "250"
    assert r21["note"] == "28"


def test_income_quarterly_primary_window_beats_cumulative_window():
    text = """
# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
Quý 4
* **Chi phí hoạt động**
    * Kỳ này: (10) triệu đồng
    * Kỳ trước: (9) triệu đồng
    * Luỹ kế từ đầu năm đến cuối quý: (100) triệu đồng
    * Luỹ kế từ đầu năm đến cuối quý trước: (90) triệu đồng
"""
    out = extract_income_fallback(text, 2025, 2024)
    row = next(r for r in out["rows"] if r.get("indicator") == "Chi phí hoạt động")
    assert (row["current"], row["previous"]) == ("(10)", "(9)")


def test_fp_structural_edge_cases():
    out = extract_financial_position_source_rows(FINANCIAL_POSITION_SAMPLE, 2025, 2024)
    rows = out["rows"]

    r135 = next(r for r in rows if r.code == "135" and r.label == "Các khoản phải thu khác")
    assert (r135.current, r135.previous) == (180, 160)

    r137 = next(r for r in rows if r.code == "137" and "Dự phòng tổn thất" in r.label)
    assert (r137.current, r137.previous) == (-60, -50)

    r300 = next(r for r in rows if r.code == "300")
    assert (r300.current, r300.previous) == (5650, 4900)

    r155 = next(r for r in rows if r.code == "155")
    assert (r155.current, r155.previous) == (30, 30)

    r268 = next(r for r in rows if r.code == "268")
    assert (r268.current, r268.previous) == (60, 40)


def test_fp_inline_code_children_and_code_only_pipe_rows():
    text = """
# BẢNG CÂN ĐỐI KẾ TOÁN
* **C. NỢ PHẢI TRẢ** (Mã số: 300)
    * Số cuối năm: 1260
    * Số đầu năm (Trình bày lại): 1090
    * 1. Nợ ngắn hạn (Mã số: 310)
        * Số cuối năm: 940
        * Số đầu năm (Trình bày lại): 750
    * 1. Phải trả người bán ngắn hạn (Mã số: 311)
        * Số cuối năm: 210
        * Số đầu năm (Trình bày lại): 140

| Mã số | Thuyết minh | Số cuối năm | Số đầu năm |
|---|---|---|---|
| 210 |  | 290 | 923 |
| 411a |  | 76 | 63 |
"""
    rows = extract_generic_statement_rows(text, 1, len(text.splitlines()), 2025, 2024, "FINANCIAL_POSITION")

    r300 = next(r for r in rows if r.code == "300" and r.label == "C. NỢ PHẢI TRẢ")
    assert (r300.current, r300.previous) == (1260, 1090)

    r311 = next(r for r in rows if r.code == "311" and "Phải trả người bán" in r.label)
    assert (r311.current, r311.previous) == (210, 140)

    r210 = next(r for r in rows if r.code == "210" and r.pattern.endswith("RAW_CODE_PIPE"))
    assert r210.label == "Mã số 210"
    assert (r210.current, r210.previous) == (290, 923)

    r411a = next(r for r in rows if r.code == "411a" and r.pattern.endswith("RAW_CODE_PIPE"))
    assert (r411a.current, r411a.previous) == (76, 63)


def test_fp_bare_end_begin_period_children():
    text = """
# BẢNG CÂN ĐỐI KẾ TOÁN
* **1. Khoản mục có kỳ không có tiền tố Số**
    * Cuối năm: 119.632.590.016
    * Đầu năm: 255.421.568.164
"""
    rows = extract_generic_statement_rows(text, 1, len(text.splitlines()), 2031, 2030, "FINANCIAL_POSITION")

    row = next(r for r in rows if r.label == "Khoản mục có kỳ không có tiền tố Số")
    assert (row.current, row.previous) == (119632590016, 255421568164)


def test_securities_customer_cashflow_is_bounded_before_b04():
    text = """
**PHẦN LƯU CHUYỂN TIỀN TỆ HOẠT ĐỘNG MÔI GIỚI, ỦY THÁC CỦA KHÁCH HÀNG**
* Tiền thu bán chứng khoán môi giới cho khách hàng: 100 (31/12/2025); 90 (31/12/2024)
* Tiền chi mua chứng khoán môi giới cho khách hàng: (80) (31/12/2025); (70) (31/12/2024)

**BÁO CÁO TÌNH HÌNH BIẾN ĐỘNG VỐN CHỦ SỞ HỮU**
* Số dư cuối năm: 999 (31/12/2025); 888 (31/12/2024)
"""
    out = extract_securities_supplemental_cashflow_rows(text, 2025, 2024)
    assert out["scope_start_line"] == 2
    assert out["scope_end_line"] == 5
    labels = {row.label: (row.current, row.previous) for row in out["rows"]}
    assert labels["Tiền thu bán chứng khoán môi giới cho khách hàng"] == (100, 90)
    assert labels["Tiền chi mua chứng khoán môi giới cho khách hàng"] == (-80, -70)
    assert "Số dư cuối năm" not in labels


def test_securities_supplemental_section_does_not_collide_with_statutory_code():
    canonical = {
        "sector": "securities",
        "method": "direct",
        "nodes": [{
            "node_id": "STATUTORY.02",
            "canonical_name": "Tiền chi khác cho hoạt động kinh doanh",
            "kind": "semantic",
            "section": "operating",
            "form_code": "02",
            "value": {"current": 1, "previous": 2},
        }],
    }
    recovered = [RecoveredRow(
        label="Tiền chi mua chứng khoán môi giới cho khách hàng",
        current=-10,
        previous=-20,
        code="02",
        section="customer_broker_flow",
        source_line=100,
        pattern="TEST_SUPPLEMENTAL",
    )]

    out = augment_canonical_with_recovered_rows(canonical, recovered, "CASHFLOW")
    semantic = [n for n in out["nodes"] if n["kind"] == "semantic"]
    source = [n for n in out["nodes"] if n["kind"] == "source_observation"]

    assert semantic[0]["value"] == {"current": 1, "previous": 2}
    assert len(source) == 1
    assert source[0]["section"] == "customer_broker_flow"
    assert source[0]["form_code"] == "02"
