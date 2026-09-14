from __future__ import annotations

from .models import SourceLine, TableContext
from .preprocess import is_table_separator, split_pipe_cells


def detect_tables(lines: list[SourceLine]) -> tuple[list[TableContext], dict[int, TableContext]]:
    by_no = {x.line_no: x for x in lines}
    contexts = []
    line_map = {}
    table_id = 0

    for i in range(len(lines) - 1):
        header = lines[i]
        sep = lines[i + 1]
        if not header.has_pipe or not is_table_separator(sep):
            continue

        table_id += 1
        header_cells = split_pipe_cells(header.clean)
        end_line = sep.line_no

        j = i + 2
        data_lines = []
        while j < len(lines):
            line = lines[j]
            if line.is_blank:
                break
            if not line.has_pipe:
                break
            if is_table_separator(line):
                j += 1
                continue
            data_lines.append(line)
            end_line = line.line_no
            j += 1

        ctx = TableContext(
            table_id=table_id,
            start_line=header.line_no,
            end_line=end_line,
            header_line=header.line_no,
            separator_line=sep.line_no,
            header_cells=header_cells,
        )
        contexts.append(ctx)
        line_map[header.line_no] = ctx
        line_map[sep.line_no] = ctx
        for row in data_lines:
            line_map[row.line_no] = ctx

    return contexts, line_map
