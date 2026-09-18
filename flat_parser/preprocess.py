from __future__ import annotations

import re

from .models import SourceLine
from .textnorm import fold


PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")
TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")


LLM_PREAMBLE_PREFIXES = (
    "tuyet voi",
    "duoi day la",
    "sau day la",
    "toi se",
    "mình sẽ",
)


def is_noise_line(line: SourceLine) -> bool:
    text = line.clean.strip()
    if not text:
        return False

    # Bullet gốc chỉ gồm số trang có khả năng cao.
    if line.is_bullet and line.indent == 0 and PAGE_NUMBER_RE.fullmatch(text):
        return True

    f = fold(text)
    if line.indent == 0 and any(f.startswith(x) for x in LLM_PREAMBLE_PREFIXES):
        return True

    return False


def split_pipe_cells(text: str) -> list[str]:
    t = text.strip()
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|"):
        t = t[:-1]
    return [x.strip() for x in t.split("|")]


def is_table_separator(line: SourceLine) -> bool:
    if not line.has_pipe:
        return False
    cells = split_pipe_cells(line.clean)
    return len(cells) >= 2 and all(
        (not c) or TABLE_SEPARATOR_CELL_RE.fullmatch(c)
        for c in cells
    )


def filter_noise(lines: list[SourceLine]) -> list[SourceLine]:
    return [x for x in lines if not is_noise_line(x)]
