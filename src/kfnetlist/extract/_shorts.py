"""Geometric short detection using klayout boolean Region operations.

Given a :class:`klayout.db.LayoutToNetlist` (from :func:`l2n_elec`),
detects unexpected polygon overlaps between different nets on the same
layer.  Overlap regions are computed via ``Region.__and__`` (boolean
intersection) and returned as structured results.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ._parser import _discover_layer_regions, _layer_display_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from klayout import db as kdb


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
            name = net.name or f"${net.cluster_id}"
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
