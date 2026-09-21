from pathlib import Path

from src.b02_income.extractor import extract_income_fallback
from src.b03_cashflow.extractor import extract_cashflow_fallback
from src.common.row_block_scanner import (
    attach_row_block_evidence,
    iter_eligible_read_ranges,
    scan_row_blocks,
)


ROOT = Path(__file__).resolve().parents[2]


def test_scanner_partitions_numbered_rows_and_keeps_nested_parent_evidence():
    text = """* **01. Parent:**
    * **01.1. Child A:**
        * Năm 2025: 10
        * Năm 2024: 9
    * **01.2. Child B:**
        * Năm 2025: 8
        * Năm 2024: 7
* **02. Sibling:**
    * Năm 2025: 6
    * Năm 2024: 5
"""

    scan = scan_row_blocks(text, 1, len(text.splitlines()), profile="income_statement")

    assert scan["version"] == "row_block_v1"
    assert scan["eligible"] is True
    assert 0.0 <= scan["coverage"] <= 1.0
    assert list(iter_eligible_read_ranges(scan))[0] == (1, 1)
    child = next(block for block in scan["blocks"] if block["anchor_label"] == "Child A")
    assert child["parent_anchor_label"] == "Parent"
    assert child["next_anchor_line"] == 5


def test_repeated_code_is_not_treated_as_unique_key():
    text = """* **01. First:**
    * Năm 2025: 10
* **01. Second:**
    * Năm 2025: 9
* **02. Third:**
    * Năm 2025: 8
"""

    scan = scan_row_blocks(text, 1, len(text.splitlines()), profile="cash_flow")

    repeated = [block for block in scan["blocks"] if block["form_code"] == "01"]
    assert len(repeated) == 2
    assert all(block["code_ambiguous_in_section"] for block in repeated)
    assert all(not block["eligible"] for block in repeated)


def test_row_block_evidence_attaches_only_to_unambiguous_source_lines():
    text = """* **01. Alpha:**
    * Năm 2025: 10
    * Năm 2024: 9
* **02. Beta:**
    * Năm 2025: 8
"""
    scan = scan_row_blocks(text, 1, len(text.splitlines()), profile="income_statement")
    rows = [{"indicator": "Alpha", "source_line": 1}, {"indicator": "Beta", "source_line": 4}]

    stats = attach_row_block_evidence(rows, scan)

    assert stats["attached"] == 2
    assert rows[0]["row_block_id"] == "income_statement:1-3"
    assert rows[1]["row_block_start_line"] == 4


def test_income_assist_keeps_semantic_rows_equal_to_full_scope_path():
    source = ROOT / "md_reports/FRT_BCTC_2025_hop_nhat_kiem_toan.md"
    text = source.read_text(encoding="utf-8")
    baseline = extract_income_fallback(text, 2025, 2024, row_scan_mode="off")
    assisted = extract_income_fallback(text, 2025, 2024, row_scan_mode="assist")

    def semantic(rows):
        return sorted(
            (row.get("indicator"), row.get("current"), row.get("previous"))
            for row in rows
        )

    assert assisted["row_block_scan"]["eligible"] is True
    assert semantic(assisted["rows"]) == semantic(baseline["rows"])


def test_income_assist_fails_closed_when_block_windows_differ():
    source = ROOT / "md_reports/GEE_BCTC_2025_hop_nhat_kiem_toan.md"
    text = source.read_text(encoding="utf-8")
    baseline = extract_income_fallback(text, 2025, 2024, row_scan_mode="off")
    assisted = extract_income_fallback(text, 2025, 2024, row_scan_mode="assist")

    assert assisted["rows"] == baseline["rows"]
    assert assisted["row_block_scan"]["assist_used"] is False
    assert assisted["row_block_scan"]["assist_decision"] == "fallback_full_scope_mismatch"


def test_cashflow_shadow_only_adds_diagnostics_and_does_not_change_rows():
    source = ROOT / "md_reports/BSI_BCTC_2025_hop_nhat_kiem_toan.md"
    text = source.read_text(encoding="utf-8")
    baseline = extract_cashflow_fallback(text, 2025, 2024, row_scan_mode="off")
    shadow = extract_cashflow_fallback(text, 2025, 2024, row_scan_mode="shadow")

    def semantic(rows):
        return sorted(
            (row.get("source_label"), row.get("current"), row.get("previous"), row.get("code"))
            for row in rows
        )

    assert shadow["row_block_scan"]["eligible"] is True
    assert semantic(shadow["rows"]) == semantic(baseline["rows"])
