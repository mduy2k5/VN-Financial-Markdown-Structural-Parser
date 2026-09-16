"""Persist the evidence-backed adjudication for the four VBB v3 conflicts.

This is a review register, not a primary-value overwrite.  It records which
entries are safe to use after the v4 parser repair and which remain blocked
because the source hierarchy is not aligned.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_FILE = "VBB_BCTC_2025_hop_nhat_kiem_toan.md"


def _items() -> list[dict[str, Any]]:
    common = {
        "source_file": SOURCE_FILE,
        "target_financial_unit": "million_vnd",
        "reviewer": "rule_based_manual_adjudication",
        "source_hash_scope": "md_reports source and v3 specialized baseline preserved",
    }
    return [
        {
            **common,
            "review_id": "VBB-NOTE-7.1-financial_position-r0004-current",
            "source_ref": "NOTE:7.1@L2549",
            "target_ref": "financial_position:r0004",
            "period": "current",
            "v3_status": "conflict",
            "v4_status": "conflict",
            "primary_value": 51514898,
            "note_value": 50914898,
            "difference": -600000,
            "decision": "hold_scope_mismatch",
            "business_use": "blocked",
            "rationale": (
                "Note 7.1 total is 50,914,898, while the primary row is 51,514,898. "
                "The difference equals Note 7.2 current loan value 600,000; therefore "
                "the linked primary row contains deposits plus loans and cannot be "
                "treated as an exact Note 7.1 reconciliation."
            ),
            "evidence": {
                "primary_lines": [482, 483, 485, 487, 489],
                "note_7_1_lines": [2549, 2566, 2567],
                "note_7_2_lines": [2589, 2592],
                "equation": "50,914,898 + 600,000 = 51,514,898",
            },
            "recommended_action": "Keep primary value; add component/aggregate scope handling before business use.",
        },
        {
            **common,
            "review_id": "VBB-NOTE-7.1-financial_position-r0004-previous",
            "source_ref": "NOTE:7.1@L2549",
            "target_ref": "financial_position:r0004",
            "period": "previous",
            "v3_status": "conflict",
            "v4_status": "conflict",
            "primary_value": 35921200,
            "note_value": 34021200,
            "difference": -1900000,
            "decision": "hold_scope_mismatch",
            "business_use": "blocked",
            "rationale": (
                "Note 7.1 total is 34,021,200, while the primary row is 35,921,200. "
                "The difference equals Note 7.2 previous loan value 1,900,000; the "
                "same component/aggregate scope issue is present in the prior period."
            ),
            "evidence": {
                "primary_lines": [482, 483, 486, 487, 490],
                "note_7_1_lines": [2549, 2566, 2568],
                "note_7_2_lines": [2589, 2593],
                "equation": "34,021,200 + 1,900,000 = 35,921,200",
            },
            "recommended_action": "Keep primary value; add component/aggregate scope handling before business use.",
        },
        {
            **common,
            "review_id": "VBB-NOTE-20.1-income_statement-r0017-current",
            "source_ref": "NOTE:20.1",
            "target_ref": "income_statement:r0017",
            "period": "current",
            "v3_status": "conflict",
            "v4_status": "confirmed",
            "primary_value": -321919,
            "v3_note_value": -54,
            "reviewed_note_value": 321919,
            "difference_after_normalization": 0,
            "decision": "confirmed_sign_convention",
            "business_use": "eligible_with_sign_normalization",
            "rationale": (
                "v3 selected the detail row 'Chuyển lỗ từ công ty con' at line 4357 "
                "because 'công' was misclassified as a total. The actual current-tax "
                "total is 321,919 at line 4373 and matches the primary magnitude; the "
                "negative primary sign is an additive expense convention."
            ),
            "evidence": {
                "primary_lines": [837, 839],
                "incorrect_candidate_lines": [4356, 4357],
                "correct_total_lines": [4372, 4373],
                "comparison_basis": "absolute_amount",
            },
            "recommended_action": "Use the v4 confirmed reconciliation; preserve primary sign and record sign convention.",
        },
        {
            **common,
            "review_id": "VBB-NOTE-20.1-income_statement-r0017-previous",
            "source_ref": "NOTE:20.1",
            "target_ref": "income_statement:r0017",
            "period": "previous",
            "v3_status": "conflict",
            "v4_status": "confirmed",
            "primary_value": -230373,
            "v3_note_value": -14,
            "reviewed_note_value": 230373,
            "difference_after_normalization": 0,
            "decision": "confirmed_sign_convention",
            "business_use": "eligible_with_sign_normalization",
            "rationale": (
                "v3 selected the detail row 'Chuyển lỗ từ công ty con' at line 4358 "
                "instead of the actual current-tax total 230,373 at line 4374. The "
                "correct note total matches the primary magnitude under the same "
                "expense sign convention."
            ),
            "evidence": {
                "primary_lines": [837, 840],
                "incorrect_candidate_lines": [4356, 4358],
                "correct_total_lines": [4372, 4374],
                "comparison_basis": "absolute_amount",
            },
            "recommended_action": "Use the v4 confirmed reconciliation; preserve primary sign and record sign convention.",
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ground_truth/reconciliation_review_specialized_v4/vbb_manual_adjudication.json"),
    )
    args = parser.parse_args()
    items = _items()
    payload = {
        "schema_version": "financial_notes_manual_adjudication_v1",
        "source_file": SOURCE_FILE,
        "scope": "four VBB conflicts exposed by specialized-v3 versus v2 comparison",
        "items": items,
        "summary": {
            "items": len(items),
            "by_decision": dict(sorted(Counter(item["decision"] for item in items).items())),
            "by_business_use": dict(sorted(Counter(item["business_use"] for item in items).items())),
            "primary_values_mutated": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
