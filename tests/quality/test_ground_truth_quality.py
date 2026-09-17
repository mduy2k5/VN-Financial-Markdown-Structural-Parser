from src.common.ground_truth_quality import (
    assess_observation,
    infer_year_pair,
    normalize_label,
    observation_period,
    period_evidence_conflict,
    period_role,
    extract_inline_period_values,
    source_period_hint,
)
from src.common.report_period import infer_report_year_pair
from src.common.period_resolver import period_role_for_date
from src.b02_income import extract_income_fallback
from src.b03_cashflow import extract_cashflow_fallback
from src.notes.table_parser import parse_markdown_tables
from src.common.pipeline_metrics import build_metrics
from types import SimpleNamespace


def test_period_resolution_uses_raw_evidence_when_key_is_unknown():
    observation = {
        "period_key": "unknown",
        "period_raw": "Năm 2031",
        "value": "1.234",
        "source_line": 4,
        "raw_text": "* Năm 2031: 1.234 triệu đồng",
    }
    assert observation_period(observation, 2031, 2030) == "current"


def test_opening_date_is_previous_period_before_generic_year_matching():
    assert period_role("2025-01-01", 2025, 2024) == "previous"
    assert period_role("01/01/2025", 2025, 2024) == "previous"
    assert period_role("31/12/2025", 2025, 2024) == "current"


def test_cumulative_quarter_window_is_not_treated_as_primary_previous_period():
    observation = {
        "period_key": "prior",
        "period_raw": "Luỹ kế từ đầu năm đến cuối quý trước",
        "value": 10,
        "source_line": 4,
        "raw_text": "Luỹ kế từ đầu năm đến cuối quý trước: 10",
    }
    assert observation_period(observation, 2025, 2024) == "quarter"
    assert not assess_observation(
        {"label": "Doanh thu"},
        observation,
        current_year=2025,
        previous_year=2024,
    ).eligible


def test_conflicting_raw_period_evidence_is_not_silently_reassigned():
    observation = {
        "period_key": "current",
        "period_raw": "Năm 2030",
        "value": 9,
        "source_line": 4,
        "raw_text": "* Năm trước: 9 triệu đồng",
    }
    assert observation_period(observation, 2031, 2030) == "current"
    assert period_evidence_conflict(observation, 2031, 2030)


def test_year_pair_is_inferred_without_fixed_report_years():
    document = {
        "source_file": "statement_2031.md",
        "statements": {
            "income_statement": {
                "rows": [{
                    "label": "Doanh thu",
                    "observations": [{
                        "period_key": "current",
                        "period_raw": "Năm 2031",
                        "value": 10,
                        "value_raw": "10",
                        "source_line": 1,
                        "raw_text": "Doanh thu: 10 năm 2031",
                    }, {
                        "period_key": "previous",
                        "period_raw": "Năm 2030",
                        "value": 9,
                        "value_raw": "9",
                        "source_line": 2,
                        "raw_text": "Doanh thu: 9 năm 2030",
                    }],
                }]
            }
        },
    }
    assert infer_year_pair(document) == (2031, 2030)


def test_year_inference_ignores_audit_date_metadata():
    document = {
        "source_file": "report_2025.md",
        "statements": {
            "financial_position": {
                "rows": [
                    {
                        "label": "Ngày",
                        "observations": [{
                            "period_key": "2026",
                            "period_raw": "26 tháng 03 năm 2026",
                            "value": 2026,
                            "raw_text": "Ngày: 26 tháng 03 năm 2026",
                        }],
                    },
                    {
                        "label": "Tiền mặt",
                        "observations": [
                            {"period_key": "2025", "period_raw": "Năm 2025", "value": 100},
                            {"period_key": "2024", "period_raw": "Năm 2024", "value": 90},
                        ],
                    },
                ]
            }
        },
    }
    assert infer_year_pair(document) == (2025, 2024)


def test_year_inference_ignores_old_legal_reference_as_comparative_period():
    document = {
        "source_file": "report_2025.md",
        "statements": {
            "financial_position": {
                "rows": [{
                    "label": "Ban hành theo",
                    "observations": [{
                        "period_key": "2014",
                        "period_raw": "Thông tư số 49/2014/TT-NHNN ngày 31 tháng 12 năm 2014",
                        "value": 2014,
                    }],
                }]
            }
        },
    }
    assert infer_year_pair(document) == (2025, 2024)


def test_runtime_year_resolution_is_per_report_and_preserves_provenance():
    resolved = infer_report_year_pair(
        "BÁO CÁO TÀI CHÍNH cho năm tài chính kết thúc ngày 31/12/2032\n"
        "Năm trước: 2031",
        source_name="issuer_2032.md",
    )
    assert resolved["current_year"] == 2032
    assert resolved["previous_year"] == 2031
    assert resolved["method"] == "filename_and_source_cues"


def test_non_december_fiscal_year_uses_statement_end_date_and_flags_filename_conflict():
    resolved = infer_report_year_pair(
        "BÁO CÁO TÀI CHÍNH\n"
        "Cho năm tài chính kết thúc ngày 31 tháng 3 năm 2026\n"
        "Số liệu so sánh ngày 31 tháng 3 năm 2025",
        source_name="CMG_BCTC_2025.md",
    )
    assert (resolved["current_year"], resolved["previous_year"]) == (2026, 2025)
    assert resolved["current_end_date"] == "2026-03-31"
    assert resolved["previous_end_date"] == "2025-03-31"
    assert resolved["current_start_date"] == "2025-04-01"
    assert resolved["fiscal_year_label"] == 2025
    assert resolved["conflict"] is True
    assert "filename_year_differs_from_statement_end_year" in resolved["conflict_reasons"]
    assert resolved["method"] == "statement_end_date"


def test_previous_period_prefers_latest_compatible_end_date_over_old_template_dates():
    resolved = infer_report_year_pair(
        "Cho năm tài chính kết thúc ngày 31/12/2025\n"
        "Cho năm tài chính kết thúc ngày 31/12/2024\n"
        "Ban hành theo Thông tư ngày 31/12/2014",
        source_name="HDB_BCTC_2025.md",
    )
    assert (resolved["current_year"], resolved["previous_year"]) == (2025, 2024)
    assert resolved["previous_end_date"] == "2024-12-31"


def test_non_december_date_roles_are_shared_by_financial_position_repair():
    assert period_role_for_date(31, 3, 2026, 2026, 2025) == "current"
    assert period_role_for_date(1, 4, 2025, 2026, 2025) == "previous"
    assert period_role_for_date(31, 3, 2025, 2026, 2025) == "previous"


def test_standalone_statement_parsers_infer_years_without_fixed_defaults():
    income_text = (
        "# BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH\n"
        "| Chỉ tiêu | 2023 | 2022 |\n|---|---:|---:|\n"
        "| Doanh thu bán hàng và cung cấp dịch vụ | 100 | 90 |\n"
    )
    income = extract_income_fallback(income_text)
    assert income["rows"] and income["rows"][0]["current"] == "100"
    assert income["rows"][0]["previous"] == "90"

    cashflow_text = (
        "# BÁO CÁO LƯU CHUYỂN TIỀN TỆ\n"
        "### Phương pháp gián tiếp\n"
        "| Chỉ tiêu | Mã số | 2023 | 2022 |\n|---|---:|---:|---:|\n"
        "| Lợi nhuận trước thuế | 01 | 100 | 90 |\n"
    )
    cashflow = extract_cashflow_fallback(cashflow_text)
    assert cashflow["rows"] and cashflow["rows"][0]["current"] == 100
    assert cashflow["rows"][0]["previous"] == 90


def test_notes_ytd_header_is_not_previous_period():
    blocks = parse_markdown_tables(
        "| Nội dung | Lũy kế từ đầu năm | Năm trước |\n"
        "|---|---:|---:|\n"
        "| Doanh thu | 100 | 90 |\n",
        1,
        "TEST",
        current_year=2026,
        previous_year=2025,
    )
    values = blocks[0].rows[0].values
    assert values[0].period_role == "quarter"
    assert values[1].period_role == "previous"


def test_source_observations_do_not_trigger_false_partial_period_status():
    canonical = {
        "status": "ok",
        "nodes": [
            {"node_id": "INCOME.ENTERPRISE.REVENUE", "value": {"current": 10, "previous": 9}},
            {"node_id": "SOURCE.INCOME.recovered", "kind": "source_observation", "value": {"current": 8}},
        ],
        "diagnostics": {},
    }
    rows = [SimpleNamespace(mapping_status="mapped", pattern="test")]
    metrics = build_metrics(canonical, rows, {}, "enterprise", "test")
    assert metrics["status"] == "ok"
    assert metrics["mapping"]["source_observation_nodes"] == 1
    assert metrics["mapping"]["previous_coverage"] == 1.0


def test_inline_year_pair_uses_statement_thousands_separator_semantics():
    assert extract_inline_period_values(
        "Thu nhập: 67.231.128 triệu đồng (Năm 2024: 61.748.921 triệu đồng)",
        2025,
        2024,
        leading_value=67231128,
    ) == [("current", 67231128), ("previous", 61748921)]


def test_inline_date_pair_maps_opening_current_year_to_previous():
    assert extract_inline_period_values(
        "Các khoản tương đương tiền (Mã số: 112): "
        "1.174.862.635.130 đồng (31/12/2025), "
        "1.337.761.330.143 đồng (1/1/2025)",
        2025,
        2024,
        leading_value=112,
    ) == [("current", 1174862635130), ("previous", 1337761330143)]


def test_source_period_hint_uses_nearest_explicit_year_section():
    lines = ["Năm báo cáo: 2025", "* Số liệu: 10", "Năm báo cáo: 2024", "* Số liệu: 9"]
    assert source_period_hint(lines, 4, 2025, 2024) == "previous"


def test_label_normalization_removes_numbered_bullet_prefix_and_maps_d():
    assert normalize_label("1. Đầu tư nắm giữ đến ngày đáo hạn") == "dau tu nam giu den ngay dao han"


def test_label_normalization_removes_statement_section_and_form_codes():
    assert normalize_label("C. NỢ PHẢI TRẢ 300 310 330") == "no phai tra"
    assert normalize_label("I. Doanh thu bán hàng (Mã số: 01)") == "doanh thu ban hang"
    assert normalize_label("A. Nguyên giá TSCĐ") == "nguyen gia tscd"


def test_ambiguous_period_and_placeholder_label_are_queued():
    decision = assess_observation(
        {"label": "Năm nay"},
        {"period_key": "unknown", "value": 10, "source_line": 1, "raw_text": "10"},
        current_year=2031,
        previous_year=2030,
        source_line_text="10",
    )
    assert not decision.eligible
    assert "placeholder_or_shifted_label" in decision.reasons
    assert "non_primary_period" in decision.reasons
