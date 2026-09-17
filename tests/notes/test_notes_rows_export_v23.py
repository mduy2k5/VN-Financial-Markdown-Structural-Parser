from pathlib import Path

from src.notes.pipeline import parse_notes
from src.notes.row_exporter import flatten_note_rows, export_note_rows


def _sample_ir():
    text = """
# THUYẾT MINH BÁO CÁO TÀI CHÍNH
## V.01. TIỀN VÀ CÁC KHOẢN TƯƠNG ĐƯƠNG TIỀN
| Nội dung | 31/12/2025 | 01/01/2025 |
|---|---:|---:|
| Tiền mặt | 80.000 | 65.000 |
| Tiền gửi | 1.450.000 | 1.250.000 |
| **Tổng cộng** | **1.530.000** | **1.315.000** |
"""
    return parse_notes(text, source_name="ABC.md", sector="enterprise")


def test_flatten_note_rows_one_record_per_source_row():
    rows = flatten_note_rows(_sample_ir())
    assert len(rows) == 3
    assert rows[0]["source_name"] == "ABC.md"
    assert rows[0]["note_id_normalized"] == "V.1"
    assert rows[0]["row_label"] == "Tiền mặt"
    assert rows[0]["current_normalized"] == 80000
    assert rows[0]["previous_normalized"] == 65000


def test_export_note_rows_creates_csv_json(tmp_path: Path):
    result = export_note_rows(_sample_ir(), tmp_path, stem="ABC")
    assert result["row_count"] == 3
    assert (tmp_path / "ABC.notes_rows.csv").exists()
    assert (tmp_path / "ABC.notes_rows.json").exists()
