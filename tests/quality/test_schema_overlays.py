from pathlib import Path

from flat_parser.schema_loader import load_alias_document, load_schema_document
from src.b01_financial_position.extractor import FinancialPositionSourceParser
from src.b02_income.mapper import IncomeMapper, adapt_row
from src.b03_cashflow.extractor import extract_cashflow_fallback
from src.b03_cashflow.mapper import CashFlowMapper, adapt_cashflow_row


ROOT = Path(__file__).resolve().parents[2]
OVERLAYS = ROOT / "resources" / "schemas" / "overlays"


def test_schema_v17_overlays_materialize_without_mutating_baseline_catalogs():
    fp_schema = load_schema_document(OVERLAYS / "financial_position_schema_v1_7_0.json")
    fp_aliases = load_alias_document(OVERLAYS / "financial_position_aliases_v1_7_0.json")
    cf_schema = load_schema_document(OVERLAYS / "cash_flow_schema_v1_2_0.json")
    cf_aliases = load_alias_document(OVERLAYS / "cash_flow_aliases_v1_2_0.json")

    assert fp_schema["schema_version"] == "1.7.0"
    assert cf_schema["schema_version"] == "1.2.0"
    assert set(node["node_id"] for node in fp_schema["nodes"]) == set(fp_aliases["nodes"])
    assert {"CASHFLOW.SECURITIES.INDIRECT.CASH_ENDING", "CASHFLOW.SECURITIES.INDIRECT.CASH_ENDING_CASH"} <= {
        node["node_id"] for node in cf_schema["nodes"]
    }
    assert "CASHFLOW.SECURITIES.INDIRECT.CASH_ENDING" in cf_aliases

    baseline_fp = load_schema_document(ROOT / "resources/schemas/financial_position_schema.json")
    baseline_cf = load_schema_document(ROOT / "resources/schemas/cash_flow_schema.json")
    assert baseline_fp["schema_version"] == "1.6.0"
    assert baseline_cf["schema_version"] == "1.1.1"
    assert not any(node["node_id"] == "ASSET.OTHER.NON_CURRENT.OTHER" for node in baseline_fp["nodes"])
    assert not any(node["node_id"] == "CASHFLOW.SECURITIES.INDIRECT.CASH_ENDING" for node in baseline_cf["nodes"])


def test_bsi_financial_position_overlay_separates_non_current_parent_and_child():
    source = ROOT / "md_reports/BSI_BCTC_2025_hop_nhat_kiem_toan.md"
    parser = FinancialPositionSourceParser(
        schema_path=OVERLAYS / "financial_position_schema_v1_7_0.json",
        aliases_path=OVERLAYS / "financial_position_aliases_v1_7_0.json",
        same_label_recovery=True,
    )
    result = parser.parse_text(
        source.read_text(encoding="utf-8"),
        source_name=source.name,
        current_year=2025,
        previous_year=2024,
    )
    nodes = {node["node_id"]: node for node in result["canonical"]["nodes"]}

    assert nodes["ASSET.OTHER.NON_CURRENT"]["value"]["current"] == "57.855.069.670"
    assert nodes["ASSET.OTHER.NON_CURRENT.OTHER"]["value"]["current"] == "15.000.000.000"
    assert nodes["ASSET.OTHER.NON_CURRENT.PLEDGED_LONG_TERM"]["value"]["current"] == "11.454.479.792"
    assert nodes["ASSET.OTHER.NON_CURRENT.PAYMENT_SUPPORT_FUND"]["value"]["current"] == "21.400.000.000"
    assert nodes["ASSET.OTHER.PREPAID_EXPENSE.LONG_TERM"]["value"]["current"] == "10.000.589.878"


def test_bsi_cashflow_overlay_maps_103_and_disambiguates_same_label_103_1():
    mapper = CashFlowMapper(
        OVERLAYS / "cash_flow_schema_v1_2_0.json",
        OVERLAYS / "cash_flow_aliases_v1_2_0.json",
        sector="securities",
        method="indirect",
    )
    rows = [
        adapt_cashflow_row({
            "source_label": "Tiền và các khoản tương đương tiền cuối năm",
            "current": 1064105925053,
            "previous": 284434076341,
            "code": "103",
            "statement_code": "103",
            "section": "reconciliation",
            "method": "indirect",
        }),
        adapt_cashflow_row({
            "source_label": "Tiền",
            "current": 1064105925053,
            "previous": 284434076341,
            "code": "103.1",
            "statement_code": "103.1",
            "section": "reconciliation",
            "method": "indirect",
        }),
    ]
    mapped = mapper.map_rows(rows)
    assert mapped[0].mapped_node_id == "CASHFLOW.SECURITIES.INDIRECT.CASH_ENDING"
    assert mapped[1].mapped_node_id == "CASHFLOW.SECURITIES.INDIRECT.CASH_ENDING_CASH"
    assert mapped[1].mapping_method == "form_code_disambiguation"

    canonical = mapper.canonical(mapped, "BSI_BCTC_2025_hop_nhat_kiem_toan.md", 2025, 2024)
    assert canonical["schema_version"] == "1.2.0"
    assert canonical["diagnostics"]["formula_summary"]["failed"] == 0


def test_bsi_cashflow_extractor_keeps_101_1_and_103_1_same_label_rows_separate():
    source = ROOT / "md_reports/BSI_BCTC_2025_hop_nhat_kiem_toan.md"
    extracted = extract_cashflow_fallback(
        source.read_text(encoding="utf-8"),
        current_year=2025,
        previous_year=2024,
    )
    rows = {row.get("code"): row for row in extracted["rows"]}

    assert rows["101.1"]["source_label"] == "Tiền"
    assert rows["103.1"]["source_label"] == "Tiền"
    assert rows["103.1"]["current"] == 1064105925053

    legacy = extract_cashflow_fallback(
        source.read_text(encoding="utf-8"),
        current_year=2025,
        previous_year=2024,
        preserve_decimal_branch_rows=False,
    )
    assert not any(row.get("code") == "103.1" for row in legacy["rows"])


def test_alias_v18_overlays_materialize_and_keep_baseline_reversible():
    fp = load_alias_document(OVERLAYS / "financial_position_aliases_v1_8_0.json")
    income = load_alias_document(OVERLAYS / "income_statement_aliases_v1_3_4.json")
    cashflow = load_alias_document(OVERLAYS / "cash_flow_aliases_v1_3_0.json")

    assert fp["alias_schema_version"] == "1.8.0"
    assert income["alias_schema_version"] == "1.3.4"
    assert cashflow["alias_schema_version"] == "1.3.0"
    assert "Tiền gửi tại TCTD khác" in fp["nodes"]["ASSET.INTERBANK.DEPOSITS"]["match"]["aliases"]
    assert "Tài sản dài hạn khác" in fp["nodes"]["ASSET.OTHER.PREPAID_EXPENSE.LONG_TERM"]["match"]["parent_context"]
    assert "Lợi nhuận gộp về bán và dịch vụ cung cấp" in income["nodes"]["INCOME.ENTERPRISE.GROSS_PROFIT"]["exact"]
    assert "Chi phí lãi và các khoản chi phí tương tự đã trả" in cashflow["CASHFLOW.BANK.DIRECT.INTEREST_PAID"]

    baseline_income = load_alias_document(ROOT / "resources/schemas/income_statement_aliases.json")
    baseline_cashflow = load_alias_document(ROOT / "resources/schemas/cash_flow_aliases.json")
    assert "Lợi nhuận gộp về bán và dịch vụ cung cấp" not in baseline_income["nodes"]["INCOME.ENTERPRISE.GROSS_PROFIT"]["exact"]
    assert "Chi phí lãi và các khoản chi phí tương tự đã trả" not in baseline_cashflow.get("CASHFLOW.BANK.DIRECT.INTEREST_PAID", [])


def test_income_alias_overlay_maps_short_enterprise_labels_as_exact_aliases():
    mapper = IncomeMapper(
        schema_path=ROOT / "resources/schemas/income_statement_schema.json",
        aliases_path=OVERLAYS / "income_statement_aliases_v1_3_4.json",
        sector="enterprise",
    )
    rows = mapper.map_rows([
        adapt_row({"indicator": "Cổ đông của Công ty mẹ", "current": "10", "previous": "9"}),
        adapt_row({"indicator": "Cổ đông không kiểm soát", "current": "2", "previous": "1"}),
        adapt_row({"indicator": "Phần lãi (lỗ) trong công ty liên kết", "current": "3", "previous": "2"}),
    ])

    assert [row.node_id for row in rows] == [
        "INCOME.ENTERPRISE.PROFIT_ATTRIBUTABLE_PARENT",
        "INCOME.ENTERPRISE.PROFIT_ATTRIBUTABLE_NCI",
        "INCOME.ENTERPRISE.SHARE_OF_PROFIT_ASSOCIATES",
    ]
    assert all(row.mapping_method == "exact_alias" for row in rows)
