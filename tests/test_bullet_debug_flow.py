from pathlib import Path
from flat_parser.bullet_debug import BulletDebugFlow

FIX = Path(__file__).parent / "fixtures" / "bullet_debug" / "four_patterns.md"

def test_four_structures_extract_to_requested_shape():
    rows, debug = BulletDebugFlow().extract(FIX.read_text(encoding="utf-8"))
    got = {r.indicator: r for r in rows}

    assert got["Tiền"].note == "5"
    assert got["Tiền"].previous == "1.249.079.279.225"
    assert got["Tiền"].current == "3.391.086.654.285"

    tax = got["Thuế và các khoản phải nộp Nhà nước"]
    assert tax.previous == "575.367.634.585"
    assert tax.current == "590.131.178.595"

    capital = got["Vốn điều lệ"]
    assert capital.previous == "8.959.336"
    assert capital.current == "10.032.190"

    total = got["Tổng số"]
    assert total.previous == "9.066.625"
    assert total.current == "10.139.266"
    assert total.unit.lower() == "triệu đồng"

    common = got["Vốn CP thường"]
    assert common.previous == "8.959.336"
    assert common.current == "10.032.190"

    pref = got["Vốn CP ưu đãi"]
    assert pref.previous == "107.289"
    assert pref.current == "107.076"

    assert debug["pattern_counts"]["P1_LABEL_CHILD_ATTRIBUTES"] == 1
    assert debug["pattern_counts"]["P2_LABEL_INLINE_PERIOD_VALUES"] == 1
    assert debug["pattern_counts"]["P3_NAMED_INDICATOR_DATE_CHILDREN"] == 1
    assert debug["pattern_counts"]["P4_PERIOD_CONTAINER_TREE"] == 3

def test_csv_columns_exact(tmp_path):
    out = tmp_path / "out.csv"
    dbg = tmp_path / "out.debug.json"
    BulletDebugFlow().run_file(FIX, out, dbg)
    header = out.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header == "Chỉ tiêu,Thuyết minh,Số năm trước,Số năm nay,Đơn vị"
    assert dbg.exists()
