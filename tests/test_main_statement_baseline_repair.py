from scripts.repair_main_statement_baselines import repair_baseline


def test_repair_income_table_moves_current_value_out_of_label():
    document = {
        "schema_version": "financial_baseline_observation_ir_v1",
        "source_file": "income.md",
        "statements": {
            "income_statement": {
                "rows": [{
                    "row_id": "r0001",
                    "label": "13.604.093",
                    "label_path": ["13.604.093"],
                    "note": "Thu nhập lãi",
                    "observations": [{
                        "period_key": "prior",
                        "period_raw": "Năm trước",
                        "value": 9027696,
                        "value_raw": "9.027.696",
                        "source_line": 1,
                        "raw_text": "Thu nhập lãi | 13.604.093 | 9.027.696",
                    }],
                }]
            }
        },
    }
    repaired = repair_baseline(document, ["Thu nhập lãi | 13.604.093 | 9.027.696"])
    row = repaired["statements"]["income_statement"]["rows"][0]
    assert row["label"] == "Thu nhập lãi"
    assert row["note"] is None
    assert [(x["period_key"], x["value"]) for x in row["observations"]] == [
        ("current", 13604093),
        ("prior", 9027696),
    ]


def test_repair_cashflow_inline_pair_adds_prior_observation():
    document = {
        "schema_version": "financial_baseline_observation_ir_v1",
        "source_file": "cashflow.md",
        "statements": {
            "cash_flow": {
                "rows": [{
                    "row_id": "r0001",
                    "label": "Thu nhập lãi",
                    "observations": [{
                        "period_key": "current",
                        "value": 100,
                        "value_raw": "100",
                        "source_line": 1,
                        "raw_text": "* Thu nhập lãi: 100 triệu đồng (Năm nay), 90 triệu đồng (Năm trước)",
                    }],
                }]
            }
        },
    }
    repaired = repair_baseline(document, ["* Thu nhập lãi: 100 triệu đồng (Năm nay), 90 triệu đồng (Năm trước)"])
    observations = repaired["statements"]["cash_flow"]["rows"][0]["observations"]
    assert [(x["period_key"], x["value"]) for x in observations] == [("current", 100), ("prior", 90)]


def test_repair_code_label_table_preserves_code_and_semantic_label():
    document = {
        "schema_version": "financial_baseline_observation_ir_v1",
        "source_file": "cashflow.md",
        "statements": {
            "cash_flow": {
                "rows": [{
                    "row_id": "r0001",
                    "label": "01",
                    "code": None,
                    "note": "Lợi nhuận trước thuế",
                    "observations": [{
                        "period_key": "prior",
                        "value": 90,
                        "value_raw": "90",
                        "source_line": 1,
                        "raw_text": "01 | Lợi nhuận trước thuế | 100 | 90",
                    }],
                }]
            }
        },
    }
    repaired = repair_baseline(document, ["01 | Lợi nhuận trước thuế | 100 | 90"])
    row = repaired["statements"]["cash_flow"]["rows"][0]
    assert row["code"] == "01"
    assert row["label"] == "Lợi nhuận trước thuế"
    assert [(x["period_key"], x["value"]) for x in row["observations"]] == [
        ("current", 100),
        ("prior", 90),
    ]
