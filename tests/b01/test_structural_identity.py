import json
from types import SimpleNamespace

from src.b03_cashflow.extractor import extract_cashflow_fallback
from src.common.source_canonical_hydrator import hydrate_canonical_by_form_code
from src.common.source_observation import augment_from_rows


def test_column_major_cashflow_uses_label_slots_and_period_vectors():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
### Phương pháp gián tiếp
**CHỈ TIÊU**
**Mã số**
**Năm nay**
**Năm trước**
* **I. LƯU CHUYỂN TIỀN TỆ TỪ HOẠT ĐỘNG KINH DOANH**
* Lợi nhuận trước thuế
* Các khoản phải thu
* Chi phí phải trả trước
* Tiền thu từ khách hàng
01
02
03
20
10000
20000
30000
40000
90000
18000
27000
36000
"""
    result = extract_cashflow_fallback(text, 2025, 2024, fallback_unit="vnd")

    layout = result["column_major_layout"]
    assert layout["detected"] is True
    assert layout["row_slots"] == 4
    assert [row["source_label"] for row in result["rows"]] == [
        "Lợi nhuận trước thuế",
        "Các khoản phải thu",
        "Chi phí phải trả trước",
        "Tiền thu từ khách hàng",
    ]
    assert [(row["current"], row["previous"]) for row in result["rows"]] == [
        (10000, 90000), (20000, 18000), (30000, 27000), (40000, 36000)
    ]
    assert all(row["code"] is None for row in result["rows"])
    assert all(row["pattern"] == "CF_COLUMN_MAJOR_STRUCTURAL" for row in result["rows"])


def test_detached_pipe_period_table_uses_semantic_label_block():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
### Phương pháp trực tiếp
**LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG TÀI CHÍNH**
* Tăng vốn cổ phần từ góp vốn và/hoặc phát hành cổ phiếu
* Tiền thu từ phát hành giấy tờ có giá dài hạn
* Tiền chi thanh toán giấy tờ có giá dài hạn
* Lưu chuyển tiền thuần từ hoạt động tài chính
**Lưu chuyển tiền thuần trong năm**
* Tiền và các khoản tương đương tiền - đầu năm
* Tiền và các khoản tương đương tiền cuối năm

**Thuyết minh** | **Năm nay** | **Năm trước**
--- | --- | ---
| | **2.558.119** | **934.706**
| | **2.500.000** | **1.000.000**
| | **(1.084.870)** | **(839.000)**
| | **3.973.249** | **1.095.706**
| | **11.006.108** | **8.102.220**
| | **44.594.502** | **36.492.282**
| | **55.600.610** | **44.594.502**
"""
    result = extract_cashflow_fallback(text, 2025, 2024, fallback_unit="million_vnd")

    layout = result["column_major_layout"]
    assert layout["detected"] is True
    assert layout["layout_type"] == "detached_period_table"
    assert layout["row_slots"] == 7
    rows = {row["source_label"]: row for row in result["rows"]}
    assert rows["Tăng vốn cổ phần từ góp vốn và/hoặc phát hành cổ phiếu"]["current"] == 2558119
    assert rows["Tiền và các khoản tương đương tiền cuối năm"]["previous"] == 44594502
    assert all(row["code"] is None for row in rows.values())
    json.dumps(result, ensure_ascii=False)


def test_value_before_label_does_not_shift_normal_label_first_rows():
    text = """
# BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
### Phương pháp trực tiếp
* **Thu nhập lãi và các khoản thu nhập tương tự nhận được:**
    * **Năm nay (Triệu đồng):** 11.871.739
    * **Năm trước (Triệu đồng):** 9.868.811
* **Chi phí lãi và các chi phí tương tự đã trả:**
    * **Năm nay (Triệu đồng):** (8.477.145)
    * **Năm trước (Triệu đồng):** (7.271.379)
"""
    result = extract_cashflow_fallback(text, 2025, 2024, fallback_unit="million_vnd")
    rows = {row["source_label"]: row for row in result["rows"]}
    assert rows["Thu nhập lãi và các khoản thu nhập tương tự nhận được"]["current"] == 11871739
    assert rows["Thu nhập lãi và các khoản thu nhập tương tự nhận được"]["previous"] == 9868811
    assert rows["Chi phí lãi và các chi phí tương tự đã trả"]["current"] == -8477145
    assert rows["Chi phí lãi và các chi phí tương tự đã trả"]["previous"] == -7271379


def _source_node_for_code(statement_code: str):
    canonical = {"nodes": []}
    row = SimpleNamespace(
        label="Các khoản phải thu",
        current=100,
        previous=90,
        section="operating",
        method="indirect",
        statement_code=statement_code,
        note_ref="20",
        code=statement_code,
        note="20",
        source_line=12,
        pattern="test",
        parent_label="",
        hierarchy_path="",
        unit="vnd",
        mapping_status="mapped",
        mapping_method="exact_label",
    )
    augment_from_rows(canonical, [row], "CASHFLOW")
    return canonical["nodes"][0]


def test_statement_code_and_note_reference_do_not_change_source_identity():
    first = _source_node_for_code("02")
    second = _source_node_for_code("99")

    assert first["node_id"] == second["node_id"]
    assert first["statement_code"] == "02"
    assert second["statement_code"] == "99"
    assert first["note_ref"] == second["note_ref"] == "20"

    canonical = {"nodes": []}
    row_a = SimpleNamespace(**{
        "label": "Các khoản phải thu", "current": 100, "previous": 90,
        "section": "operating", "method": "indirect", "statement_code": "02",
        "note_ref": "20", "code": "02", "note": "20", "source_line": 12,
        "pattern": "test", "parent_label": "", "hierarchy_path": "", "unit": "vnd",
        "mapping_status": "mapped", "mapping_method": "exact_label",
    })
    row_b = SimpleNamespace(**{**row_a.__dict__, "statement_code": "99", "code": "99"})
    augment_from_rows(canonical, [row_a, row_b], "CASHFLOW")
    assert len(canonical["nodes"]) == 1


def test_unique_code_only_period_evidence_hydrates_a_semantic_node():
    canonical = {
        "nodes": [{
            "node_id": "CASHFLOW.TEST.PROFIT",
            "canonical_name": "Lợi nhuận trước thuế",
            "sector": "enterprise",
            "method": "indirect",
            "form_code": "01",
            "value": {"current": None, "previous": None},
        }]
    }
    hydrate_canonical_by_form_code(
        canonical,
        [{"code": "01", "statement_code": "01", "current": 100, "previous": 90}],
        "enterprise",
        "indirect",
    )

    assert canonical["nodes"][0]["value"] == {"current": 100, "previous": 90}
    assert canonical["diagnostics"]["form_code_period_recovery"]["filled_nodes"] == 1
    assert canonical["diagnostics"]["form_code_period_recovery"]["filled_periods"] == 2


def test_ambiguous_code_only_period_evidence_does_not_hydrate():
    canonical = {
        "nodes": [
            {
                "node_id": "CASHFLOW.TEST.ONE",
                "sector": "bank",
                "method": "direct",
                "form_code": "01",
                "value": {"current": None, "previous": None},
            },
            {
                "node_id": "CASHFLOW.TEST.TWO",
                "sector": "bank",
                "method": "direct",
                "form_code": "01",
                "value": {"current": None, "previous": None},
            },
        ]
    }

    hydrate_canonical_by_form_code(
        canonical,
        [{"code": "01", "current": 100, "previous": 90}],
        "bank",
        "direct",
    )

    assert all(node["value"] == {"current": None, "previous": None} for node in canonical["nodes"])
    assert canonical["diagnostics"]["form_code_period_recovery"]["ambiguous_codes"] == ["1"]
