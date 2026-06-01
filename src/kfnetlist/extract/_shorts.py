"""Geometric short detection using klayout boolean Region operations.

Given a :class:`klayout.db.LayoutToNetlist` (from :func:`l2n_elec`),
detects unexpected polygon overlaps between different nets on the same
layer.  Overlap regions are computed via ``Region.__and__`` (boolean
intersection) and returned as structured results that can be converted
to a KLayout Report Database for visualisation in the marker browser.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ._parser import _discover_layer_regions, _layer_display_name, _net_shapes_by_layer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from klayout import db as kdb
    from klayout import rdb


@dataclasses.dataclass
class ShortResult:
    """A geometric short between two nets on a single layer."""

    net_a: str
    net_b: str
    layer: str
    overlap: kdb.Region


def detect_shorts(
    l2n: kdb.LayoutToNetlist,
    *,
    short_layers: Sequence[kdb.LayerInfo] | None = None,
    circuit_name: str | None = None,
) -> list[ShortResult]:
    """Detect geometric shorts between nets via polygon overlap.

    For each layer (or only the layers in *short_layers*), collects the
    shapes of every net and checks all pairs for non-empty intersection.

    Parameters
    ----------
    l2n:
        A klayout ``LayoutToNetlist`` whose extraction is complete.
    short_layers:
        Restrict detection to these layers.  ``None`` checks every layer
        registered in the L2N.
    circuit_name:
        Circuit to inspect.  Defaults to the top cell.

    Returns
    -------
    list[ShortResult]
        One entry per (net_a, net_b, layer) triple that has a non-empty
        overlap region.
    """
    layer_regions = _discover_layer_regions(l2n)
    if short_layers is not None:
        allowed = set(short_layers)
        layer_regions = {
            info: reg for info, reg in layer_regions.items() if info in allowed
        }
    if not layer_regions:
        return []

    netlist = l2n.netlist()
    cell_name = circuit_name or l2n.internal_top_cell().name
    circuit = netlist.circuit_by_name(cell_name)
    if circuit is None:
        return []

    shorts: list[ShortResult] = []
    for layer_info, layer_region in layer_regions.items():
        layer_name = _layer_display_name(layer_info)
        net_shapes: list[tuple[str, kdb.Region]] = []
        for net in circuit.each_net():
            shapes = l2n.shapes_of_net(net, layer_region, True)
            if shapes.is_empty():
                continue
            name = net.name or f"${net.cluster_id()}"
            net_shapes.append((name, shapes))

        for i, (name_a, shapes_a) in enumerate(net_shapes):
            for name_b, shapes_b in net_shapes[i + 1 :]:
                overlap = shapes_a & shapes_b
                if not overlap.is_empty():
                    shorts.append(
                        ShortResult(
                            net_a=name_a,
                            net_b=name_b,
                            layer=layer_name,
                            overlap=overlap,
                        )
                    )
    return shorts


def shorts_to_rdb(
    shorts: list[ShortResult],
    *,
    cell_name: str = "top",
    dbu: float = 0.001,
) -> rdb.ReportDatabase:
    """Convert short results to a klayout :class:`rdb.ReportDatabase`.

    Parameters
    ----------
    shorts:
        Results from :func:`detect_shorts`.
    cell_name:
        Cell name for the report database.
    dbu:
        Database unit in microns, used to convert integer coordinates to
        microns for the RDB markers.

    Returns
    -------
    rdb.ReportDatabase
        Loadable in KLayout's marker browser.
    """
    from klayout import rdb as klayout_rdb

    db = klayout_rdb.ReportDatabase("Geometric short detection")
    db.generator = "kfnetlist"
    db.top_cell_name = cell_name
    cell_id = db.create_cell(cell_name).rdb_id()

    cat = db.create_category("LVS")
    cat.description = "LVS Errors"
    short_cat = db.create_category(cat, "short")
    short_cat.description = "Geometric shorts (unexpected overlaps)"

    for s in shorts:
        n_locations = s.overlap.count()
        text = (
            f"Geometric short between '{s.net_a}' and '{s.net_b}' "
            f"on {s.layer} ({n_locations} location"
            f"{'s' if n_locations != 1 else ''})"
        )
        item = db.create_item(cell_id, short_cat.rdb_id())
        item.add_value(klayout_rdb.RdbItemValue(text))
        for poly in s.overlap.each():
            item.add_value(klayout_rdb.RdbItemValue(poly.to_dtype(dbu)))

    return db


def shorts_to_lyrdb(
    shorts: list[ShortResult],
    *,
    cell_name: str = "top",
    dbu: float = 0.001,
) -> str:
    """Convert short results to lyrdb XML string.

    This is a convenience wrapper around :func:`shorts_to_rdb` that
    serialises the result to KLayout's lyrdb XML format.  The XML can
    be loaded with ``rdb.ReportDatabase.load()`` or fed to the Rust
    filtering functions (:func:`kfnetlist.include_from_rdb_xml`, etc.).

    Parameters
    ----------
    shorts:
        Results from :func:`detect_shorts`.
    cell_name:
        Cell name for the report database.
    dbu:
        Database unit in microns.

    Returns
    -------
    str
        lyrdb XML string loadable by KLayout.
    """
    import tempfile
    from pathlib import Path

    report = shorts_to_rdb(shorts, cell_name=cell_name, dbu=dbu)
    with tempfile.NamedTemporaryFile(
        suffix=".lyrdb", delete=False, mode="w"
    ) as f:
        path = f.name
    try:
        report.save(path)
        return Path(path).read_text()
    finally:
        Path(path).unlink(missing_ok=True)
