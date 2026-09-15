from pathlib import Path

from src.income_observation_patch import extract_income_fallback
from src.source_statement_recovery import extract_financial_position_source_rows


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "md_test" / "BID_BCTC_gia_lap_2025_20_trang.md"


def _by_code(rows, code):
    return [r for r in rows if getattr(r, "code", None) == code]


def test_income_fragmented_vertical_note_column():
    if not FIXTURE.exists():
        return
    text = FIXTURE.read_text(encoding="utf-8")
    out = extract_income_fallback(text, 2025, 2024)
    rows = out["rows"]

    r02 = next(r for r in rows if r.get("code") == "02" and "điều chỉnh giảm" in r.get("indicator", "").lower())
    assert r02["current"] == "(200)"
    assert r02["previous"] == "(180)"
    assert r02["note"] == "26"

    r21 = next(r for r in rows if r.get("code") == "21" and "thu nhập tài chính" in r.get("indicator", "").lower())
    assert r21["current"] == "300"
    assert r21["previous"] == "250"
    assert r21["note"] == "28"


def test_fp_structural_edge_cases():
    if not FIXTURE.exists():
        return
    text = FIXTURE.read_text(encoding="utf-8")
    out = extract_financial_position_source_rows(text, 2025, 2024)
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
