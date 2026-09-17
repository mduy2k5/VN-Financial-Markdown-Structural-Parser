from pathlib import Path
from flat_parser.pipeline import FlatParserPipeline

ROOT = Path(__file__).resolve().parents[2]

def pipe():
    return FlatParserPipeline(
        schema_path=ROOT/"resources/schemas/financial_position_schema.json",
        aliases_path=ROOT/"resources/schemas/financial_position_aliases.json",
        universal_guide_path=ROOT/"resources/guides/compiled/structural_guide.json",
    )

def test_detached_total_consumes_entire_long_table_block():
    rows = [
        "| Mã số TÀI SẢN | Thuyết minh | 31/12/2025 | 01/01/2025 |",
        "|---|---|---|---|",
    ]
    # >40 source lines between detached heading and terminal total row.
    for i in range(1, 43):
        rows.append(f"| {i}. Chi tiết {i} | | {i}.000 | {i}.100 |")
    rows.append("| TỔNG CỘNG TÀI SẢN | | 15.148.255.852.020 | 14.199.525.343.428 |")

    raw = "\n".join([
        "BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT",
        "Tại ngày 31 tháng 12 năm 2025",
        "TÀI SẢN",
        "TỔNG CỘNG TÀI SẢN",
        *rows,
        "BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH",
    ])

    r=pipe().parse_text(raw)
    nm={n["node_id"]:n for n in r["canonical"]["nodes"]}
    total=nm["TOTAL_ASSETS"]["value"]
    assert total["current"]=="15.148.255.852.020"
    assert total["previous"]=="14.199.525.343.428"
