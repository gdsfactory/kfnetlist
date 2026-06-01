"""Filtering helpers for ``klayout.rdb.ReportDatabase`` objects.

The Rust core operates on lyrdb XML strings; these wrappers handle the
round-trip through ``klayout.rdb``.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from kfnetlist._native import (
    exclude_from_rdb as _exclude_from_rdb_xml,
)
from kfnetlist._native import (
    filter_rdb as _filter_rdb_xml,
)
from kfnetlist._native import (
    include_from_rdb as _include_from_rdb_xml,
)

if TYPE_CHECKING:
    from klayout import rdb


def _to_xml(rdb: rdb.ReportDatabase) -> str:
    with tempfile.NamedTemporaryFile(suffix=".lyrdb", delete=False, mode="w") as f:
        path = f.name
    try:
        rdb.save(path)
        return Path(path).read_text()
    finally:
        Path(path).unlink(missing_ok=True)


def _from_xml(xml: str) -> rdb.ReportDatabase:
    from klayout import rdb as klayout_rdb

    out = klayout_rdb.ReportDatabase("")
    with tempfile.NamedTemporaryFile(suffix=".lyrdb", delete=False, mode="w") as f:
        f.write(xml)
        path = f.name
    try:
        out.load(path)
    finally:
        Path(path).unlink(missing_ok=True)
    return out


def include_from_rdb(
    rdb: rdb.ReportDatabase,
    paths: Sequence[str],
) -> rdb.ReportDatabase:
    """Return a new ReportDatabase with only those items whose category path matches.

    Paths are matched with dot-boundary prefix semantics: ``"LVS.net"``
    matches both ``"LVS.net.missing_in_layout"`` and
    ``"LVS.net.missing_in_schematic"``, but not ``"LVS.network"``.

    An empty ``paths`` sequence drops every item.
    """
    return _from_xml(_include_from_rdb_xml(_to_xml(rdb), list(paths)))


def exclude_from_rdb(
    rdb: rdb.ReportDatabase,
    paths: Sequence[str],
) -> rdb.ReportDatabase:
    """Return a new ReportDatabase with items whose category path matches removed.

    Uses the same dot-boundary prefix semantics as :func:`include_from_rdb`.
    An empty ``paths`` sequence keeps every item.
    """
    return _from_xml(_exclude_from_rdb_xml(_to_xml(rdb), list(paths)))


def filter_rdb(
    rdb: rdb.ReportDatabase,
    predicate: Callable[[str], bool],
) -> rdb.ReportDatabase:
    """Return a new RDB keeping only items whose category path satisfies ``predicate``.

    Example::

        filtered = filter_rdb(rdb, lambda path: path == "LVS.short")

    """
    return _from_xml(_filter_rdb_xml(_to_xml(rdb), predicate))
