"""Parse a klayout LayoutToNetlist into a JSON-serializable dictionary.

Converts klayout's internal L2N circuit/net representation into a clean
JSON structure with optional hierarchy flattening and layer/instance
filtering.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from klayout import db as kdb


def _layer_display_name(info: kdb.LayerInfo) -> str:
    """Human-readable name for a LayerInfo (falls back to ``layer/datatype``)."""
    return info.name or str(info)


def _discover_layer_regions(
    l2n: kdb.LayoutToNetlist,
) -> dict[kdb.LayerInfo, kdb.Region]:
    """Map each registered LayerInfo to its L2N region handle."""
    internal_ly = l2n.internal_layout()
    regions: dict[kdb.LayerInfo, kdb.Region] = {}
    for li in range(internal_ly.layers()):
        if not internal_ly.is_valid_layer(li):
            continue
        info = internal_ly.get_info(li)
        try:
            region = l2n.layer_by_index(li)
        except RuntimeError:
            continue
        if region is not None:
            regions[info] = region
    return regions


def _net_shapes_by_layer(
    net: kdb.Net,
    l2n: kdb.LayoutToNetlist,
    layer_regions: dict[kdb.LayerInfo, kdb.Region],
) -> dict[kdb.LayerInfo, kdb.Region]:
    """Return ``{LayerInfo: shapes}`` for layers where *net* has shapes."""
    result: dict[kdb.LayerInfo, kdb.Region] = {}
    for info, region in layer_regions.items():
        shapes = l2n.shapes_of_net(net, region, True)
        if not shapes.is_empty():
            result[info] = shapes
    return result


def _serialize_net(
    net: kdb.Net,
    l2n: kdb.LayoutToNetlist | None,
    layer_regions: dict[kdb.LayerInfo, kdb.Region],
    subc_id_filter: set[int] | None,
    include_layers: set[kdb.LayerInfo] | None,
    exclude_layers: set[kdb.LayerInfo] | None,
) -> dict[str, Any] | None:
    """Serialize one net.  Returns ``None`` when filtered out."""
    net_shapes: dict[kdb.LayerInfo, kdb.Region] | None = None
    if l2n is not None and layer_regions:
        net_shapes = _net_shapes_by_layer(net, l2n, layer_regions)
        if include_layers is not None or exclude_layers is not None:
            layer_set = set(net_shapes)
            if include_layers is not None and not layer_set & include_layers:
                return None
            if (
                exclude_layers is not None
                and layer_set
                and layer_set <= exclude_layers
            ):
                return None

    pins: list[str] = [
        pr.pin().name() for pr in net.each_pin() if pr.pin().name()
    ]

    subcircuit_pins: list[dict[str, str]] = []
    for sc_pin in net.each_subcircuit_pin():
        subc = sc_pin.subcircuit()
        if subc_id_filter is not None and subc.id() not in subc_id_filter:
            continue
        pin_name = sc_pin.pin().name()
        if not pin_name:
            continue
        subcircuit_pins.append(
            {"subcircuit": subc.name or f"${subc.id()}", "pin": pin_name}
        )

    if not pins and not subcircuit_pins:
        return None

    entry: dict[str, Any] = {"name": net.name or None}
    if pins:
        entry["pins"] = pins
    if subcircuit_pins:
        entry["subcircuit_pins"] = subcircuit_pins
    if net_shapes:
        layer_to_polygons: dict[str, list[list[list[int]]]] = {}
        layer_to_holes: dict[str, list[list[list[int]]]] = {}
        for info, shapes in sorted(
            net_shapes.items(),
            key=lambda kv: _layer_display_name(kv[0]),
        ):
            name = _layer_display_name(info)
            polys: list[list[list[int]]] = []
            holes: list[list[list[int]]] = []
            for poly in shapes.each():
                polys.append([[p.x, p.y] for p in poly.each_point_hull()])
                for h in range(poly.holes()):
                    holes.append(
                        [[p.x, p.y] for p in poly.each_point_hole(h)]
                    )
            layer_to_polygons[name] = polys
            if holes:
                layer_to_holes[name] = holes
        entry["layer_to_polygons"] = layer_to_polygons
        if layer_to_holes:
            entry["layer_to_holes"] = layer_to_holes
    return entry


def _serialize_circuit(
    circuit: kdb.Circuit,
    l2n: kdb.LayoutToNetlist | None,
    layer_regions: dict[kdb.LayerInfo, kdb.Region],
    include_instances: set[str] | None,
    exclude_instances: set[str] | None,
    include_layers: set[kdb.LayerInfo] | None,
    exclude_layers: set[kdb.LayerInfo] | None,
) -> dict[str, Any]:
    """Serialize one circuit: pins, subcircuits, and nets."""
    pins = sorted(p.name() for p in circuit.each_pin() if p.name())

    has_inst_filter = (
        include_instances is not None or exclude_instances is not None
    )
    included_subc_ids: set[int] = set()
    subcircuits: list[dict[str, Any]] = []

    for subc in circuit.each_subcircuit():
        ref_name = subc.circuit_ref().name
        if include_instances is not None and ref_name not in include_instances:
            continue
        if exclude_instances is not None and ref_name in exclude_instances:
            continue
        included_subc_ids.add(subc.id())
        subcircuits.append(
            {
                "name": subc.name or f"${subc.id()}",
                "circuit_ref": ref_name,
                "transform": str(subc.trans),
            }
        )

    subc_filter = included_subc_ids if has_inst_filter else None
    nets: list[dict[str, Any]] = []
    for net in circuit.each_net():
        entry = _serialize_net(
            net, l2n, layer_regions, subc_filter, include_layers, exclude_layers
        )
        if entry is not None:
            nets.append(entry)

    result: dict[str, Any] = {}
    if pins:
        result["pins"] = pins
    if subcircuits:
        result["subcircuits"] = subcircuits
    if nets:
        result["nets"] = nets
    return result


def parse_l2n(
    l2n: kdb.LayoutToNetlist,
    *,
    flatten: bool = False,
    include_layers: Sequence[kdb.LayerInfo] | None = None,
    exclude_layers: Sequence[kdb.LayerInfo] | None = None,
    include_instances: Sequence[str] | None = None,
    exclude_instances: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Convert a :class:`kdb.LayoutToNetlist` to a JSON-serializable dict.

    Parameters
    ----------
    l2n:
        A klayout ``LayoutToNetlist`` whose extraction is complete.
    flatten:
        Collapse the full circuit hierarchy into the top-level circuit.
        Per-net layer annotation is unavailable in flat mode because the
        flattened netlist is a copy detached from the L2N shape data.
    include_layers:
        Keep only nets that touch at least one of these layers.
        Ignored when ``flatten=True``.
    exclude_layers:
        Drop nets whose shapes lie entirely on excluded layers.
        Ignored when ``flatten=True``.
    include_instances:
        Keep only subcircuits whose ``circuit_ref`` name is in this set.
        Ignored when ``flatten=True``.
    exclude_instances:
        Remove subcircuits whose ``circuit_ref`` name is in this set.
        Ignored when ``flatten=True``.

    Returns
    -------
    dict
        ``{"top_circuit": str, "layers": list[str],
        "circuits": {name: {...}, ...}}``.
    """
    top_cell_name = l2n.internal_top_cell().name
    layer_regions = _discover_layer_regions(l2n)

    incl_layers = set(include_layers) if include_layers is not None else None
    excl_layers = set(exclude_layers) if exclude_layers is not None else None
    incl_inst = (
        set(include_instances) if include_instances is not None else None
    )
    excl_inst = (
        set(exclude_instances) if exclude_instances is not None else None
    )

    filtered_infos = list(layer_regions)
    if incl_layers is not None:
        filtered_infos = [i for i in filtered_infos if i in incl_layers]
    if excl_layers is not None:
        filtered_infos = [i for i in filtered_infos if i not in excl_layers]
    reported_layers = sorted(
        _layer_display_name(info) for info in filtered_infos
    )

    if flatten:
        netlist = l2n.netlist().dup()
        for circuit in list(netlist.each_circuit_bottom_up()):
            if circuit.name != top_cell_name:
                netlist.flatten_circuit(circuit)
        circuits = {
            top_cell_name: _serialize_circuit(
                netlist.circuit_by_name(top_cell_name),
                None,
                {},
                None,
                None,
                None,
                None,
            )
        }
    else:
        circuits: dict[str, Any] = {}
        for circuit in l2n.netlist().each_circuit_top_down():
            circuits[circuit.name] = _serialize_circuit(
                circuit,
                l2n,
                layer_regions,
                incl_inst,
                excl_inst,
                incl_layers,
                excl_layers,
            )

    return {
        "top_circuit": top_cell_name,
        "dbu": l2n.internal_layout().dbu,
        "layers": reported_layers,
        "circuits": circuits,
    }


def l2n_to_json(
    l2n: kdb.LayoutToNetlist,
    *,
    flatten: bool = False,
    include_layers: Sequence[kdb.LayerInfo] | None = None,
    exclude_layers: Sequence[kdb.LayerInfo] | None = None,
    include_instances: Sequence[str] | None = None,
    exclude_instances: Sequence[str] | None = None,
    indent: int = 2,
) -> str:
    """Convenience wrapper around :func:`parse_l2n` returning a JSON string."""
    return json.dumps(
        parse_l2n(
            l2n,
            flatten=flatten,
            include_layers=include_layers,
            exclude_layers=exclude_layers,
            include_instances=include_instances,
            exclude_instances=exclude_instances,
        ),
        indent=indent,
    )
