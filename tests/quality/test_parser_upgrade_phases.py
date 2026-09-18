from types import SimpleNamespace

from src.b02_income import extract_income_fallback
from src.b02_income.mapper import IncomeMapper, adapt_row
from src.b03_cashflow import extract_cashflow_fallback
from src.b03_cashflow.mapper import CashFlowMapper, adapt_cashflow_row
from src.common.error_taxonomy import build_error_taxonomy
from src.common.source_recovery import extract_financial_position_source_rows
from src.common.source_reconciler import reconcile_source_observations


def test_income_vector_columns_are_rehydrated_without_using_codes_as_identity():
    text = """
# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT
B02-DN/HN
CHỈ TIÊU
Thuyết minh
Mã số
Năm nay
Năm trước
1. Doanh thu bán hàng và cung cấp dịch vụ
2. Các khoản giảm trừ doanh thu
3. Doanh thu thuần về bán hàng và cung cấp dịch vụ
4. Giá vốn hàng bán và dịch vụ cung cấp
5. Lợi nhuận gộp về bán hàng và cung cấp dịch vụ
01
02
10
11
20
10000
20000
30000
40000
50000
9000
19000
29000
39000
49000
"""
    result = extract_income_fallback(text, 2025, 2024)
    vector_rows = [
        row for row in result["rows"]
        if row.get("pattern_id") == "SP_INCOME_VECTOR_COLUMN_MAJOR"
    ]

    assert len(vector_rows) == 5
    assert vector_rows[0]["indicator"] == "Doanh thu bán hàng và cung cấp dịch vụ"
    assert (vector_rows[0]["current"], vector_rows[0]["previous"]) == ("10000", "9000")

    mapper = IncomeMapper(
        schema_path="resources/schemas/income_statement_schema.json",
        aliases_path="resources/schemas/income_statement_aliases.json",
        sector="enterprise",
    )
    mapped = mapper.map_rows([adapt_row(row) for row in vector_rows])
    assert all(row.mapping_status == "mapped" for row in mapped)


def test_income_label_normalization_removes_serializer_prefixes():
    mapper = IncomeMapper(
        schema_path="resources/schemas/income_statement_schema.json",
        aliases_path="resources/schemas/income_statement_aliases.json",
        sector="enterprise",
    )
    row = adapt_row({
        "indicator": "Diễn giải: Doanh thu bán hàng và cung cấp dịch vụ",
        "current": "100",
        "previous": "90",
    })
    assert mapper.map_row(row).mapping_status == "mapped"


def test_income_interleaved_rows_use_statement_identity_to_restore_adjacent_values():
    text = """
# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
B02-DN
CHỈ TIÊU
Năm nay
Năm trước
3. Doanh thu thuần về bán hàng và cung cấp dịch vụ
10
1000
900
4. Giá vốn hàng bán
11
600
400
300
200
5. Lợi nhuận gộp về bán hàng và cung cấp dịch vụ
20
"""
    result = extract_income_fallback(text, 2025, 2024)
    rows = {
        row["indicator"]: row
        for row in result["rows"]
        if row.get("pattern_id") == "SP_INCOME_INTERLEAVED_FORMULA_PAIR"
    }

    assert rows["Giá vốn hàng bán"]["current"] == "600"
    assert rows["Giá vốn hàng bán"]["previous"] == "300"
    assert rows["Lợi nhuận gộp về bán hàng và cung cấp dịch vụ"]["current"] == "400"
    assert rows["Lợi nhuận gộp về bán hàng và cung cấp dịch vụ"]["previous"] == "200"


def test_income_mapping_normalizes_nested_notes_carry_forward_and_hierarchical_indexes():
    mapper = IncomeMapper(sector="enterprise")
    rows = mapper.map_rows([
        adapt_row({
            "indicator": "16.1. Lợi nhuận sau thuế của cổ đông của Công ty mẹ",
            "current": "100",
            "previous": "90",
        }),
        adapt_row({
            "indicator": "Lãi cơ bản trên cổ phiếu (Thuyết minh 20(a))",
            "current": "10",
            "previous": "9",
        }),
        adapt_row({
            "indicator": "Tổng lợi nhuận trước thuế (mang sang trang sau)",
            "current": "100",
            "previous": "90",
        }),
    ])

    assert all(row.mapping_status == "mapped" for row in rows)


def test_income_bank_detail_expenses_have_distinct_schema_nodes():
    mapper = IncomeMapper(sector="bank")
    rows = mapper.map_rows([
        adapt_row({"indicator": "Chi phí nhân viên", "current": "10", "previous": "9"}),
        adapt_row({"indicator": "Chi phí khấu hao và khấu trừ", "current": "10", "previous": "9"}),
    ])

    assert [row.node_id for row in rows] == [
        "INCOME.BANK.PERSONNEL_EXPENSE",
        "INCOME.BANK.ASSET_EXPENSE",
    ]


def test_cashflow_period_major_blocks_recombine_current_and_previous_values():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
B03-DN/HN
### Phương pháp gián tiếp
I. LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG KINH DOANH
III. LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG TÀI CHÍNH
Năm nay:
    Tiền thu từ đi vay: 100
Năm trước:
    Tiền thu từ đi vay: 90
"""
    result = extract_cashflow_fallback(text, 2025, 2024)
    rows = [row for row in result["rows"] if row["source_label"] == "Tiền thu từ đi vay"]

    assert rows
    assert rows[0]["current"] == 100
    assert rows[0]["previous"] == 90


def test_cashflow_inline_bullet_period_roles_map_bank_direct_rows():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ
**LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG KINH DOANH**
* **Thu nhập lãi và các khoản thu nhập tương tự nhận được:** 12.919.243 triệu đồng (Năm nay), 9.453.794 triệu đồng (Năm trước)
* **Chi phí lãi và các chi phí tương tự đã trả:** (7.652.424) triệu đồng (Năm nay), (7.279.639) triệu đồng (Năm trước)
* **Thu nhập từ hoạt động dịch vụ nhận được:** 260.547 triệu đồng (Năm nay), 499.749 triệu đồng (Năm trước)
* **Chênh lệch số tiền thực thu từ hoạt động kinh doanh chứng khoán, vàng bạc, ngoại tệ:** (100.046) triệu đồng (Năm nay), 371.027 triệu đồng (Năm trước)
* **Thu nhập (chi phí) khác:** 3.095.446 triệu đồng (Năm nay), 318.683 triệu đồng (Năm trước)
* **Tiền thu các khoản nợ đã được xử lý xoá, bù đắp bằng nguồn dự phòng rủi ro:** 207.490 triệu đồng (Năm nay), 196.165 triệu đồng (Năm trước)
* **Tiền chi trả cho nhân viên và hoạt động quản lý, công vụ:** (1.874.490) triệu đồng (Năm nay), (2.276.722) triệu đồng (Năm trước)
* **Tiền thuế thu nhập thực nộp trong năm:** (539.615) triệu đồng (Năm nay), (105.913) triệu đồng (Năm trước)
* **Lưu chuyển tiền thuần từ hoạt động kinh doanh trước những thay đổi về tài sản và nợ phải trả hoạt động:** 6.316.151 triệu đồng (Năm nay), 1.177.144 triệu đồng (Năm trước)
"""
    result = extract_cashflow_fallback(text, 2025, 2024)
    expected = {
        "Thu nhập lãi và các khoản thu nhập tương tự nhận được": (12919243, 9453794),
        "Chi phí lãi và các chi phí tương tự đã trả": (-7652424, -7279639),
        "Thu nhập từ hoạt động dịch vụ nhận được": (260547, 499749),
        "Chênh lệch số tiền thực thu từ hoạt động kinh doanh chứng khoán, vàng bạc, ngoại tệ": (-100046, 371027),
        "Thu nhập (chi phí) khác": (3095446, 318683),
        "Tiền thu các khoản nợ đã được xử lý xoá, bù đắp bằng nguồn dự phòng rủi ro": (207490, 196165),
        "Tiền chi trả cho nhân viên và hoạt động quản lý, công vụ": (-1874490, -2276722),
        "Tiền thuế thu nhập thực nộp trong năm": (-539615, -105913),
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh trước những thay đổi về tài sản và nợ phải trả hoạt động": (6316151, 1177144),
    }
    rows = [row for row in result["rows"] if row["source_label"] in expected]
    assert len(rows) == len(expected)
    assert {
        row["source_label"]: (row["current"], row["previous"])
        for row in rows
    } == expected
    inline = next(
        row for row in rows
        if row["source_label"] == "Thu nhập lãi và các khoản thu nhập tương tự nhận được"
    )
    assert inline["raw_text"].startswith("* **Thu nhập lãi")
    assert "12.919.243" in inline["raw_text"]
    assert "Năm trước" in inline["raw_text"]

    mapper = CashFlowMapper(
        schema_path="resources/schemas/cash_flow_schema.json",
        aliases_path="resources/schemas/cash_flow_aliases.json",
        sector="bank",
        method="direct",
    )
    mapped = mapper.map_rows([adapt_cashflow_row(row) for row in rows])
    assert all(row.mapping_status == "mapped" for row in mapped)
    assert all(row.mapped_node_id for row in mapped)


def test_source_observation_links_to_semantic_evidence_without_using_form_code():
    canonical = {
        "nodes": [
            {
                "node_id": "CASHFLOW.BANK.DIRECT.EXAMPLE",
                "canonical_name": "Canonical label",
                "kind": "semantic",
                "section": "operating",
                "value": {"current": 12, "previous": 9},
                "extraction_meta": {
                    "occurrences": [{
                        "source_line": 10,
                        "source_label": "Raw label",
                        "current": 12,
                        "previous": 9,
                    }],
                },
            },
            {
                "node_id": "SOURCE.CASHFLOW.example",
                "canonical_name": "Raw label",
                "kind": "source_observation",
                "section": "operating",
                "form_code": "99",
                "value": {"current": 12, "previous": 9},
                "extraction_meta": {
                    "occurrences": [{
                        "source_line": 10,
                        "source_label": "Raw label",
                        "current": 12,
                        "previous": 9,
                    }],
                },
            },
        ],
    }

    out = reconcile_source_observations(canonical, "CASHFLOW")
    source = next(node for node in out["nodes"] if node["kind"] == "source_observation")
    meta = source["extraction_meta"]
    assert meta["mapping_status"] == "mapped"
    assert meta["mapped_node_id"] == "CASHFLOW.BANK.DIRECT.EXAMPLE"
    assert meta["mapping_method"] == "source_evidence_link"


def test_financial_position_date_blocks_pair_current_and_opening_values():
    text = """
# BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
31/12/2025
* TÀI SẢN
    * Tiền và các khoản tương đương tiền: 100 đồng
01/01/2025
* TÀI SẢN
    * Tiền và các khoản tương đương tiền: 90 đồng
"""
    result = extract_financial_position_source_rows(text, 2025, 2024)
    row = next(
        item for item in result["rows"]
        if item.label == "Tiền và các khoản tương đương tiền"
    )

    assert (row.current, row.previous) == (100, 90)


def test_financial_position_column_years_and_single_bar_rows_keep_both_periods():
    text = """
# BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
**Tại ngày 31 tháng 12 năm**
* **Mã số:** NGUỒN VỐN
* **Thuyết minh**
* **2025 (VND)**
* **2024 (VND)**
**300 NỢ PHẢI TRẢ:** 180 (đồng) | 90 (đồng)
* **310 Nợ ngắn hạn:** 150 (đồng) | 70 (đồng)
"""
    result = extract_financial_position_source_rows(text, 2025, 2024)
    rows = {row.label: row for row in result["rows"]}

    assert (rows["NỢ PHẢI TRẢ"].current, rows["NỢ PHẢI TRẢ"].previous) == (180, 90)
    assert (rows["Nợ ngắn hạn"].current, rows["Nợ ngắn hạn"].previous) == (150, 70)


def test_cashflow_note_reference_colon_is_not_treated_as_a_value():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
B03-DN/HN
### Phương pháp gián tiếp
I. LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG KINH DOANH
* **06. Chi phí đi vay và phát hành trái phiếu (Thuyết minh: 30):**
    * Năm nay: 292.046
    * Năm trước: 420.300
"""
    result = extract_cashflow_fallback(text, 2025, 2024)
    rows = [row for row in result["rows"] if "Chi phí đi vay" in row["source_label"]]

    assert rows
    assert rows[0]["current"] == 292046
    assert rows[0]["previous"] == 420300
    assert rows[0]["source_label"] == "Chi phí đi vay và phát hành trái phiếu (Thuyết minh: 30)"


def test_cashflow_diễn_giải_child_relabels_the_current_keyed_block():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
B03-DN/HN
Năm 2025
(Theo phương pháp gián tiếp)
* **Chỉ tiêu:**
    * **Mã số:** 60
        * **Thuyết minh:** -
        * **Năm 2025 (VND):** 100
        * **Năm 2024 (VND):** 90
        * **Diễn giải:** Tiền và tương đương tiền đầu năm
    * **Mã số:** 61
        * **Thuyết minh:** -
        * **Năm 2025 (VND):** 10
        * **Năm 2024 (VND):** 9
        * **Diễn giải:** Ảnh hưởng của thay đổi tỷ giá hối đoái quy đổi ngoại tệ
"""
    result = extract_cashflow_fallback(text, 2025, 2024)
    rows = {row["source_label"]: row for row in result["rows"]}

    assert rows["Tiền và tương đương tiền đầu năm"]["current"] == 100
    assert rows["Tiền và tương đương tiền đầu năm"]["previous"] == 90
    assert rows["Ảnh hưởng của thay đổi tỷ giá hối đoái quy đổi ngoại tệ"]["current"] == 10
    assert rows["Ảnh hưởng của thay đổi tỷ giá hối đoái quy đổi ngoại tệ"]["previous"] == 9


def test_cashflow_value_before_label_does_not_cross_signoff_boundary():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
B03-DN/HN
Năm 2025
Tiền và các khoản tương đương tiền cuối năm
* Năm 2025 (triệu đồng): 200
* Năm 2024 (triệu đồng): 100
---
* **Người lập:**
    * Bà Nguyễn Văn A
"""
    result = extract_cashflow_fallback(text, 2025, 2024)
    assert not any(row["source_label"] == "Bà Nguyễn Văn A" for row in result["rows"])


def test_error_taxonomy_separates_structural_noise_from_semantic_gap():
    rows = [
        SimpleNamespace(label="Trang: 12", current=12, previous=11, mapping_status="unmapped"),
        SimpleNamespace(label="Một chỉ tiêu mới", current=12, previous=11, mapping_status="unmapped"),
    ]
    report = build_error_taxonomy("income_statement", rows)

    assert report["by_reason"]["STRUCTURAL_NOISE"] == 1
    assert report["by_reason"]["SEMANTIC_MAPPING_GAP"] == 1


def test_error_taxonomy_recognizes_generic_footer_names_without_a_name_catalog():
    rows = [
        SimpleNamespace(label="Nguyễn Thanh Sơn", current=1, previous=None, mapping_status="unmapped"),
        SimpleNamespace(label="Theo phương pháp gián tiếp (tiếp theo)", current=1, previous=None, mapping_status="unmapped"),
    ]
    report = build_error_taxonomy("cash_flow_statement", rows)

    assert report["unmapped_total"] == 2
    assert report["by_reason"]["STRUCTURAL_NOISE"] == 2


def test_income_noise_filter_removes_role_suffixes_and_flattened_signatories():
    from src.b02_income.extractor import is_non_item_header_or_noise

    assert is_non_item_header_or_noise("Nguyễn Việt Thắng - Tổng Giám đốc")
    assert is_non_item_header_or_noise("Trần Xuân Mai - Người lập biểu")
    assert is_non_item_header_or_noise("### Lãi trên cổ phiếu")


def test_cashflow_aliases_cover_generic_investing_and_financing_labels():
    mapper = CashFlowMapper(
        schema_path="resources/schemas/cash_flow_schema.json",
        aliases_path="resources/schemas/cash_flow_aliases.json",
        sector="enterprise",
        method="indirect",
    )
    rows = mapper.map_rows([
        adapt_cashflow_row({
            "source_label": "Phần lãi trong công ty liên doanh, liên kết",
            "current": 10,
            "previous": 9,
            "section": "operating",
            "method": "indirect",
        }),
        adapt_cashflow_row({
            "source_label": "Tiền trả lại vốn góp cho các cổ đông không kiểm soát",
            "current": 10,
            "previous": 9,
            "section": "financing",
            "method": "indirect",
        }),
    ])

    assert all(row.mapping_status == "mapped" for row in rows)
