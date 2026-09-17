from pathlib import Path
from flat_parser.pipeline import FlatParserPipeline

ROOT = Path(__file__).resolve().parents[2]

def pipe():
    return FlatParserPipeline(
        schema_path=ROOT/"resources/schemas/financial_position_schema.json",
        aliases_path=ROOT/"resources/schemas/financial_position_aliases.json",
        universal_guide_path=ROOT/"resources/guides/compiled/structural_guide.json",
    )

def nmap(result):
    return {n["node_id"]: n for n in result["canonical"]["nodes"]}

def test_detached_total_uses_terminal_table_row_not_nearest():
    raw = """
BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TÀI SẢN
TỔNG CỘNG TÀI SẢN (270=100+200)
| Mã số | Số cuối năm | Số đầu năm |
|---|---|---|
| 260 | 10 | 9 |
| 269 | 20 | 19 |
| 270 | 100 | 90 |
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
"""
    r=pipe().parse_text(raw)
    n=nmap(r)["TOTAL_ASSETS"]
    assert n["value"]["current"]=="100"
    assert n["value"]["previous"]=="90"

def test_detached_total_multi_period_line():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
Tại ngày 31 tháng 12 năm 2025
TỔNG NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU
1.192.344.137 triệu đồng (Năm 2025), 978.798.549 triệu đồng (Năm 2024)
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
"""
    r=pipe().parse_text(raw)
    n=nmap(r)["TOTAL_LIABILITIES_AND_EQUITY"]
    assert n["value"]["current"]=="1.192.344.137"
    assert n["value"]["previous"]=="978.798.549"

def test_detached_total_generic_keyed_pair():
    raw = """
BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
tại ngày 31 tháng 12 năm 2025
Ngày 31 tháng 12 năm 2025
Triệu đồng
Ngày 31 tháng 12 năm 2024 (Trình bày lại)
Triệu đồng
TỔNG TÀI SẢN
Số liệu: 1.260.149.596
Số liệu (Trình bày lại): 923.847.637
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG HỢP NHẤT
"""
    r=pipe().parse_text(raw)
    n=nmap(r)["TOTAL_ASSETS"]
    assert n["value"]["current"]=="1.260.149.596"
    assert n["value"]["previous"]=="923.847.637"
