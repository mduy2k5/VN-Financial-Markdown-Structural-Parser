from types import SimpleNamespace

from src.common.output_contract import build_production_report, clean_statement
from src.common.source_canonical_hydrator import augment_canonical_with_recovered_rows
from src.common.source_reconciler import reconcile_source_observations


def _recovered_row(*, current, previous):
    return SimpleNamespace(
        label="Tiền mặt",
        current=current,
        previous=previous,
        code=None,
        statement_code=None,
        note=None,
        note_ref=None,
        section=None,
        source_line=10,
        pattern="test",
        parent_label=None,
        hierarchy_path=None,
        unit="vnd",
        unit_source="test",
    )


def test_numeric_formatting_difference_is_not_a_source_recovery_conflict():
    canonical = {
        "unit": "vnd",
        "nodes": [{
            "node_id": "ASSET.CASH",
            "canonical_name": "Tiền mặt",
            "kind": "semantic",
            "value": {"current": "116752", "previous": "90"},
        }],
    }

    augment_canonical_with_recovered_rows(
        canonical,
        [_recovered_row(current="116.752", previous="90")],
        "FINANCIAL_POSITION",
    )

    recovery = canonical["diagnostics"]["source_statement_recovery"]
    assert recovery["conflicts"] == 0
    assert recovery["representation_equivalent_matches"] == 1


def test_b02_sign_normalization_is_not_reported_as_source_conflict():
    canonical = {
        "unit": "million_vnd",
        "nodes": [{
            "node_id": "INCOME.SECURITIES.FVTPL_LOSS",
            "canonical_name": "Lỗ bán các tài sản tài chính FVTPL",
            "kind": "line",
            "value": {"current": -210, "previous": -120},
        }],
    }
    row = SimpleNamespace(
        label="Lỗ bán các tài sản tài chính FVTPL",
        current=210,
        previous=120,
        code=None,
        statement_code=None,
        note=None,
        note_ref=None,
        section=None,
        source_line=25,
        pattern="test",
        parent_label=None,
        hierarchy_path=None,
        unit="million_vnd",
        unit_source="test",
    )

    augment_canonical_with_recovered_rows(canonical, [row], "INCOME")

    recovery = canonical["diagnostics"]["source_statement_recovery"]
    assert recovery["conflicts"] == 0
    assert recovery["sign_equivalent_matches"] == 1
    assert canonical["diagnostics"]["source_recovery_sign_equivalents"][0]["target_node_id"] == "INCOME.SECURITIES.FVTPL_LOSS"


def test_sign_difference_remains_a_conflict_outside_b02_normalization():
    canonical = {
        "unit": "vnd",
        "nodes": [{
            "node_id": "ASSET.CASH",
            "canonical_name": "Tiền mặt",
            "kind": "line",
            "value": {"current": -210, "previous": -120},
        }],
    }
    augment_canonical_with_recovered_rows(
        canonical,
        [_recovered_row(current=210, previous=120)],
        "FINANCIAL_POSITION",
    )

    assert canonical["diagnostics"]["source_statement_recovery"]["conflicts"] == 1


def test_b02_quarter_and_cumulative_source_scope_is_not_parser_conflict():
    canonical = {
        "unit": "million_vnd",
        "nodes": [{
            "node_id": "INCOME.BANK.PROFIT_AFTER_TAX",
            "canonical_name": "Lợi nhuận sau thuế",
            "kind": "line",
            "value": {"current": 35198433, "previous": 33853117},
        }],
    }
    row = SimpleNamespace(
        label="Lợi nhuận sau thuế",
        current=8633783,
        previous=8569921,
        code=None,
        statement_code=None,
        note=None,
        note_ref=None,
        section=None,
        source_line=752,
        pattern="INCOME_RAW_CHILDREN",
        parent_label=None,
        hierarchy_path=None,
        unit="million_vnd",
        unit_source="statement_header",
    )

    augment_canonical_with_recovered_rows(canonical, [row], "INCOME")

    recovery = canonical["diagnostics"]["source_statement_recovery"]
    assert recovery["conflicts"] == 0
    assert recovery["period_scope_ambiguities"] == 1
    assert canonical["diagnostics"]["source_period_scope_ambiguities"][0]["node_id"] == "INCOME.BANK.PROFIT_AFTER_TAX"


def test_structural_source_recovery_conflict_is_reclassified_when_child_values_match():
    canonical = {
        "unit": "million_vnd",
        "nodes": [
            {
                "node_id": "ASSET.CUSTOMER_LOANS",
                "canonical_name": "Cho vay khách hàng",
                "kind": "group",
                "value": {"current": "100", "previous": "90"},
            },
            {
                "node_id": "ASSET.CUSTOMER_LOANS.GROSS",
                "canonical_name": "Cho vay khách hàng trước dự phòng",
                "kind": "line",
                "parent_id": "ASSET.CUSTOMER_LOANS",
                "value": {"current": "110", "previous": "100"},
            },
        ],
    }
    row = SimpleNamespace(
        label="Cho vay khách hàng",
        current=110,
        previous=100,
        code=None,
        statement_code=None,
        note=None,
        note_ref=None,
        section=None,
        source_line=20,
        pattern="FP_RAW_CHILDREN",
        parent_label="Cho vay khách hàng",
        hierarchy_path="Cho vay khách hàng",
        unit="million_vnd",
        unit_source="test",
    )

    augment_canonical_with_recovered_rows(canonical, [row], "FINANCIAL_POSITION")

    recovery = canonical["diagnostics"]["source_statement_recovery"]
    assert recovery["conflicts"] == 0
    assert recovery["representation_equivalent_matches"] == 1
    assert canonical["diagnostics"]["source_recovery_representation_equivalents"][0]["target_node_id"] == "ASSET.CUSTOMER_LOANS.GROSS"


def test_source_reconciliation_normalizes_numeric_representations():
    canonical = {
        "nodes": [
            {
                "node_id": "SOURCE.FINANCIAL_POSITION.one",
                "canonical_name": "Tiền mặt",
                "kind": "source_observation",
                "value": {"current": 116752, "previous": 90},
            },
            {
                "node_id": "SOURCE.FINANCIAL_POSITION.two",
                "canonical_name": "Tiền mặt",
                "kind": "source_observation",
                "value": {"current": "116.752", "previous": "90"},
            },
        ]
    }

    out = reconcile_source_observations(canonical, "FINANCIAL_POSITION")
    view = out["reconciled_source_view"][0]

    assert view["conflict"] is False
    assert view["current_state"] == "unanimous"
    assert view["previous_state"] == "unanimous"


def test_quality_gate_keeps_parser_output_review_only_when_unresolved():
    canonical = {
        "schema_id": "test_schema",
        "schema_version": "1.0.0",
        "nodes": [{
            "node_id": "TEST.VALUE",
            "canonical_name": "Giá trị",
            "kind": "semantic",
            "value": {"current": 1, "previous": 1},
        }],
    }
    metrics = {
        "status": "ok",
        "value_nodes": 1,
        "mapping": {
            "current_coverage": 1.0,
            "previous_coverage": 1.0,
        },
        "parser": {
            "scope_health": "healthy",
            "statement_health": "healthy",
            "unresolved": 1,
        },
        "quality": {"formula_failed": 0},
    }

    statement = clean_statement(canonical, metrics, statement_type="test")
    gate = statement["validation"]["gate"]

    assert statement["status"] == "review_required"
    assert gate["status"] == "review_required"
    assert gate["eligible_for_use"] is False
    assert "unresolved:1" in gate["issues"]
    assert len(statement["items"]) == 1
    assert statement["observations"] == []

    healthy_metrics = {
        **metrics,
        "parser": {**metrics["parser"], "unresolved": 0},
    }
    healthy_statement = clean_statement(
        canonical,
        healthy_metrics,
        statement_type="test",
    )
    report = build_production_report(
        source_name="test.md",
        source_sha256="a" * 64,
        current_year=2025,
        previous_year=2024,
        year_resolution={"conflict": False},
        financial_position=statement,
        income_statement=healthy_statement,
        cash_flow=healthy_statement,
        notes={"status": "disabled"},
    )

    assert report["quality"]["status"] == "review_required"
    assert report["quality"]["gate"]["eligible_for_use"] is False
    assert report["quality"]["gate"]["issues"]["financial_position"] == gate["issues"]
