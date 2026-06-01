from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from klayout import rdb


def error_summary(rdb: rdb.ReportDatabase) -> str:
    """Summarize LVS errors as a markdown table.

    Args:
        rdb: KLayout ReportDatabase from lvs_rdb().

    Returns:
        Markdown table string with columns: cell, error type, description.

    """
    rows = []
    for item in rdb.each_item():
        cell = rdb.cell_by_id(item.cell_id()).name()
        error_type = rdb.category_by_id(item.category_id()).path()
        description = next(
            (val.string() for val in item.each_value() if val.is_string()), ""
        )
        rows.append((cell, error_type, description))

    if not rows:
        return "| cell | error type | description |\n| --- | --- | --- |"

    col_cell = max(len("cell"), *(len(r[0]) for r in rows))
    col_error = max(len("error type"), *(len(r[1]) for r in rows))
    col_desc = max(len("description"), *(len(r[2]) for r in rows))

    def fmt(cell: str, error: str, desc: str) -> str:
        return f"| {cell:<{col_cell}} | {error:<{col_error}} | {desc:<{col_desc}} |"

    lines = [
        fmt("cell", "error type", "description"),
        f"| {'-' * col_cell} | {'-' * col_error} | {'-' * col_desc} |",
        *[fmt(*r) for r in rows],
    ]
    return "\n".join(lines)
