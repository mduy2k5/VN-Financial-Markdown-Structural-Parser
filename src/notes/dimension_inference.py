from __future__ import annotations

from .note_ir import NoteBlock
from .sectionizer import fold_text


MOVEMENT_TOKENS = (
    "dau nam", "cuoi nam", "mua trong nam", "tang trong nam", "giam trong nam",
    "thanh ly", "nhuong ban", "khau hao trong nam", "hao mon", "trich lap", "hoan nhap",
)
RECON_TOKENS = (
    "loi nhuan truoc thue", "thue suat", "thu nhap khong chiu thue",
    "chi phi khong duoc khau tru", "dieu chinh thue", "tong chi phi thue",
)
AGING_TOKENS = ("qua han", "chua qua han", "duoi 30", "30 90", "90 180", "tren 180")

MOVEMENT_ROLE_PATTERNS = (
    ("opening", ("dau nam", "dau ky", "so du dau")),
    ("addition", ("mua trong nam", "tang trong nam", "phat sinh", "bo sung", "ghi nhan", "trich lap", "tang du phong")),
    ("disposal", ("thanh ly", "nhuong ban", "giam trong nam", "giam du phong", "xoa so")),
    ("usage", ("su dung", "xu ly rui ro")),
    ("transfer", ("ket chuyen",)),
    ("depreciation", ("khau hao", "hao mon", "phan bo")),
    ("closing", ("cuoi nam", "cuoi ky", "so du cuoi")),
    ("reversal", ("hoan nhap",)),
)


def infer_movement_role(label: str | None) -> str | None:
    folded = fold_text(label or "")
    for role, tokens in MOVEMENT_ROLE_PATTERNS:
        if any(token in folded for token in tokens):
            return role
    return None


def infer_dimensions(block: NoteBlock, *, current_year: int | None = None, previous_year: int | None = None) -> NoteBlock:
    if block.form != "table":
        period_members = []
        seen = set()
        movement_members = []
        movement_seen = set()
        for row in block.rows:
            for value in row.values:
                if value.period_role and value.period_role not in seen:
                    period_members.append({"role": value.period_role, "label": value.period_label})
                    seen.add(value.period_role)
                if value.movement_role and value.movement_role not in movement_seen:
                    movement_members.append({"role": value.movement_role})
                    movement_seen.add(value.movement_role)
        block.dimensions = []
        if period_members:
            block.dimensions.append({"kind": "period", "members": period_members})
        if movement_members:
            block.dimensions.append({"kind": "movement", "members": movement_members})
        return block

    headers = [fold_text(x) for x in block.headers_raw]
    labels = [x.label_normalized for x in block.rows]
    all_text = " ".join(headers + labels)

    measure_headers = []
    period_headers = []
    category_headers = []
    for idx, h in enumerate(headers):
        if idx == 0:
            category_headers.append({"axis": "row_category", "header": block.headers_raw[idx]})
            continue
        if any(x in h for x in ("du phong", "gia goc", "gia tri", "nguyen gia", "hao mon", "con lai")):
            measure_headers.append({"column": idx, "header": block.headers_raw[idx]})
        if any(x in h for x in (str(previous_year), str(current_year), "dau nam", "cuoi nam", "nam nay", "nam truoc", "01 01", "31 12")):
            period_headers.append({"column": idx, "header": block.headers_raw[idx]})

    block.dimensions = []
    if category_headers:
        block.dimensions.append({"kind": "category", "members": category_headers})
    if period_headers:
        block.dimensions.append({"kind": "period", "members": period_headers})
    if measure_headers:
        block.dimensions.append({"kind": "measure", "members": measure_headers})

    movement_hits = sum(1 for x in MOVEMENT_TOKENS if x in all_text)
    recon_hits = sum(1 for x in RECON_TOKENS if x in all_text)
    aging_hits = sum(1 for x in AGING_TOKENS if x in all_text)

    if movement_hits >= 3:
        block.semantic_shape = "movement"
    elif recon_hits >= 3:
        block.semantic_shape = "reconciliation"
    elif aging_hits >= 2:
        block.semantic_shape = "aging"
    elif len(headers) >= 4 and (measure_headers or period_headers):
        block.semantic_shape = "matrix"
    elif len(headers) >= 2:
        block.semantic_shape = "breakdown"
    else:
        block.semantic_shape = "unknown"

    block.metadata["dimension_inference"] = {
        "movement_hits": movement_hits,
        "reconciliation_hits": recon_hits,
        "aging_hits": aging_hits,
    }
    return block
