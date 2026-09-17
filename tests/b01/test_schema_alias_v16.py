import json
from pathlib import Path

from flat_parser.models import AliasCandidate, FieldObservation, PrimitivePeriod, PrimitiveValue, StatementContext
from flat_parser.resolver import resolve_observation
from flat_parser.semantic_catalog import SemanticCatalog

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "resources" / "schemas" / "financial_position_schema.json"
_cand_aliases = ROOT / "resources" / "schemas" / "financial_position_aliases.json"
ALIASES = _cand_aliases



def test_schema_alias_v16_sets_identical_and_has_extensions():
    s = json.loads(SCHEMA.read_text(encoding="utf-8"))
    a = json.loads(ALIASES.read_text(encoding="utf-8"))
    assert s["schema_version"] == "1.6.0"
    assert a["alias_schema_version"] == "1.6.0"
    assert {n["node_id"] for n in s["nodes"]} == set(a["nodes"])
    ids = {n["node_id"] for n in s["nodes"]}
    assert "OFF_BALANCE.WRITTEN_OFF_BAD_DEBT" in ids
    assert "LIABILITY.CURRENT.PROVISIONS" in ids
    assert "LIABILITY.NON_CURRENT.PROVISIONS" in ids


def _candidate(node_id, kind="group"):
    return AliasCandidate(
        node_id=node_id,
        canonical_name="Các cam kết khác",
        parent_id="OFF_BALANCE",
        kind=kind,
        sector="bank",
        matched_alias="Các cam kết khác",
        method="exact",
        alias_score=0.99,
        context_score=0.0,
        final_score=0.99,
        evidence=[],
    )


def test_off_balance_conflicting_same_period_payload_is_not_first_wins():
    p1 = PrimitivePeriod(raw_period="31/12/2025", normalized="31/12/2025", role="current", line_no=1)
    p2 = PrimitivePeriod(raw_period="31/12/2024", normalized="31/12/2024", role="previous", line_no=2)
    obs = FieldObservation(
        anchor_node_index=0,
        source_label="Các cam kết khác",
        line_no=1,
        selected=_candidate("OFF_BALANCE.OTHER_COMMITMENTS"),
        all_candidates=[],
        pattern_id="SP_PERIOD_CHILDREN",
        pattern_name="label_with_period_children",
        period_values=[
            (p1, PrimitiveValue(raw_value="122", normalized_candidate=None, line_no=1)),
            (p2, PrimitiveValue(raw_value="58", normalized_candidate=None, line_no=2)),
            (p1, PrimitiveValue(raw_value="182", normalized_candidate=None, line_no=3)),
            (p2, PrimitiveValue(raw_value="213", normalized_candidate=None, line_no=4)),
        ],
    )
    field, err = resolve_observation(obs, StatementContext(report_year=2025))
    assert field is None
    assert err == "conflicting_period_payloads"
