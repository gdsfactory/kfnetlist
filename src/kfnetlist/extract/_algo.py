"""Netlist orchestrator: combines optical-net geometry + electrical L2N."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from kfnetlist import (
    Net,
    Netlist,
    NetlistPort,
    PlacedNetlist,
    Placement,
    PortArrayRef,
    PortRef,
    flatten_netlists,
)

from ._geometry import get_optical_nets
from ._l2n import l2n_elec as _l2n_elec
from ._protocols import (
    CellLike as _CellLike,
)
from ._protocols import (
    InstanceLike as _InstanceLike,
)
from ._protocols import (
    PlaceableLike as _PlaceableLike,
)
from ._protocols import (
    RootCellLike as _RootCellLike,
)
from ._settings import serialize_setting

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from klayout import db as kdb


def _orig_cell(c: _CellLike) -> _CellLike:
    while c.is_library_cell():
        c = c.library_cell
    return c


def _gather_equivalent_ports(
    cell: _RootCellLike,
) -> dict[str, list[list[str]]]:
    eqps_all: dict[str, list[list[str]]] = {}
    for ci in [cell.cell_index(), *cell.called_cells()]:
        c_ = cell.kcl[ci]
        eqps: list[list[str]] | None = c_.lvs_equivalent_ports or None
        if c_.has_factory_name():
            if c_.is_library_cell():
                if c_.virtual:
                    eqps = (
                        _orig_cell(c_)
                        .kcl.virtual_factories[c_.factory_name]
                        .lvs_equivalent_ports
                    )
                else:
                    eqps = (
                        _orig_cell(c_)
                        .kcl.factories[c_.factory_name]
                        .lvs_equivalent_ports
                    )
            elif c_.virtual:
                eqps = c_.kcl.virtual_factories[c_.factory_name].lvs_equivalent_ports
            else:
                eqps = c_.kcl.factories[c_.factory_name].lvs_equivalent_ports
        if eqps is not None:
            eqps_all[c_.name] = eqps
    return eqps_all


def _build_port_mapping(
    equivalent_ports: dict[str, list[list[str]]],
) -> dict[str, dict[str, str]]:
    """Map every equivalent port to the first port in its group."""
    mapping: dict[str, dict[str, str]] = defaultdict(dict)
    for cell_name, groups in equivalent_ports.items():
        for group in groups:
            if group:
                mapping[cell_name].update(dict.fromkeys(group, group[0]))
    return mapping


def _placement_for(inst: _PlaceableLike) -> Placement:
    """Build a :class:`Placement` from a placed klayout instance.

    Reads the origin transform (displacement, rotation, mirror) in micrometres
    plus the transformed bounding box in the parent cell's coordinates. This is
    purely geometric; the placed cell name is captured separately onto
    :class:`~kfnetlist.PlacedInstance`.
    """
    t = inst.dcplx_trans
    bbox = inst.instance.dbbox()
    return Placement(
        x=t.disp.x,
        y=t.disp.y,
        orientation=t.angle,
        mirror=t.mirror,
        bbox={
            "left": bbox.left,
            "bottom": bbox.bottom,
            "right": bbox.right,
            "top": bbox.top,
        },
    )


def _create_inst_entry(nl: Netlist, inst: _InstanceLike) -> None:
    cell = inst.cell
    if cell.has_factory_name():
        component = cell.factory_name
    else:
        component = cell.name
    kcl_name = cell.library().name() if cell.is_library_cell() else cell.kcl.name
    settings = {k: serialize_setting(v) for k, v in cell.settings.model_dump().items()}
    # Older adapters have no info property; unnamed kfactory instances raise
    # on access. Test explicit naming, since an empty string is a valid name.
    info = getattr(inst, "info", None) if inst.is_named() else None
    nl.create_inst(
        name=inst.name,
        kcl=kcl_name,
        component=component,
        settings=settings,
        netlist_id=cell.name,
        info=info.model_dump() if info is not None else {},
        na=inst.na,
        nb=inst.nb,
    )


def _build_cell_netlist(
    cell: _CellLike,
    optical_nets: list[Net],
    l2n_elec_obj: kdb.LayoutToNetlist,
    wrap_kdb_instance: Callable[[kdb.Instance], _InstanceLike],
    *,
    ignore_unnamed: bool = False,
    exclude_purposes: list[str] | None = None,
) -> Netlist:
    """Lifted ``kfactory.kcell._get_netlist``."""
    from klayout import db as kdb

    elec_circ = l2n_elec_obj.netlist().circuit_by_name(cell.name)
    nl = Netlist()
    exclude_purposes = exclude_purposes or []

    for inst in cell.insts:
        _create_inst_entry(nl, inst)
    for port in cell.ports:
        nl.create_port(port.name)
    for net in optical_nets:
        nl.add_net(net)

    if elec_circ:
        for net in elec_circ.each_net():
            net_refs: list[NetlistPort | PortRef | PortArrayRef] = []
            for pinref in net.each_pin():
                p = nl.create_port(pinref.pin().name())
                net_refs.append(p)
            for subc_pin in net.each_subcircuit_pin():
                subc = subc_pin.subcircuit()
                circ_ref = subc.circuit_ref()
                circ = subc.circuit()
                pin = subc_pin.pin()
                recit = kdb.RecursiveInstanceIterator(
                    cell.kcl.layout,
                    cell.kcl.layout.cell(circ.name),
                    box=kdb.Box(2).transformed(
                        kdb.ICplxTrans(trans=subc.trans, dbu=cell.kcl.dbu)
                    ),
                )
                recit.max_depth = 0
                recit.targets = [
                    cell.kcl[
                        l2n_elec_obj.internal_layout().cell(circ_ref.cell_index).name
                    ].cell_index()
                ]
                recit.overlapping = True
                for it in recit.each():
                    inst_el = it.current_inst_element()
                    if (
                        inst_el.specific_cplx_trans()
                        == kdb.ICplxTrans(trans=subc.trans, dbu=cell.kcl.dbu)
                        and pin.name() != ""
                    ):
                        wrapped = wrap_kdb_instance(inst_el.inst())
                        if inst_el.ia() < 0:
                            net_refs.append(
                                PortRef(instance=wrapped.name, port=pin.name())
                            )
                        else:
                            net_refs.append(
                                PortArrayRef(
                                    instance=wrapped.name,
                                    port=pin.name(),
                                    ia=inst_el.ia(),
                                    ib=inst_el.ib(),
                                )
                            )
                        break
            if net_refs:
                nl.create_net(*net_refs)

    inst_names: set[str] = set()
    if ignore_unnamed:
        inst_names |= {inst.name for inst in cell.insts if not inst.is_named()}
    if exclude_purposes:
        inst_names |= {
            inst.name for inst in cell.insts if inst.purpose in exclude_purposes
        }
    nl.remove_instances(list(inst_names))
    nl.sort()
    return nl


def extract(
    cell: _RootCellLike,
    *,
    wrap_kdb_instance: Callable[[kdb.Instance], _InstanceLike],
    port_types: Sequence[str] = ("optical",),
    mark_port_types: Iterable[str] = ("electrical", "RF", "DC"),
    connectivity: Sequence[Sequence[kdb.LayerInfo]] | None = None,
    equivalent_ports: dict[str, list[list[str]]] | None = None,
    ignore_unnamed: bool = False,
    exclude_purposes: list[str] | None = None,
    allow_width_mismatch: bool = False,
    include_placement: bool = False,
    flatten: bool | Sequence[str] = False,
) -> dict[str, Netlist]:
    """Extract a hierarchical netlist from a cell.

    Mirrors ``ProtoTKCell.netlist`` from kfactory: gathers LVS-equivalent ports
    from cell metadata or factories (unless supplied), runs electrical L2N
    extraction once, then for each cell walks optical-port geometry plus the
    electrical circuit to assemble a :class:`Netlist`.

    The ``wrap_kdb_instance`` callable is the only required kfactory-shaped
    hook: it converts a raw :class:`klayout.db.Instance` into an object with
    ``.name`` matching the names used elsewhere in the cell hierarchy. The
    kfactory shim passes ``lambda i: Instance(kcl=cell.kcl, instance=i)``.

    When ``include_placement`` is ``True``, each returned value is a
    :class:`~kfnetlist.PlacedNetlist` (a :class:`~kfnetlist.Netlist` subclass)
    whose instances additionally carry a :class:`~kfnetlist.Placement` — the
    cell name, origin transform (x, y, orientation, mirror), and bounding box —
    read from the layout. The default (``False``) returns plain
    :class:`~kfnetlist.Netlist` objects whose instances reference child
    netlists by their extracted cell names.

    ``flatten`` inlines instances into their parent: each returned netlist has
    the selected instances replaced by the contents of their own cell's netlist
    (renamed ``"{instance}.{inner instance}"``), with the nets of both levels
    merged through the sub-cell's ports. Pass ``True`` to inline the whole
    hierarchy, or a sequence of cell names to inline only those — so a
    containerized subcircuit can be dissolved while an MZI that has its own
    model stays intact. Works with or without ``include_placement``; with it,
    each inlined placement is composed with the placement of the instance it
    came from.
    """
    if equivalent_ports is None:
        equivalent_ports = _gather_equivalent_ports(cell)

    port_mapping = _build_port_mapping(equivalent_ports)

    l2n = _l2n_elec(
        cell,
        mark_port_types=mark_port_types,
        connectivity=connectivity,
        port_mapping=port_mapping,
    )

    netlists: dict[str, Netlist] = {}
    # Per cell, `instance name -> placed cell name`. The flattener also accepts
    # this mapping for extracted layouts with instance names modified by
    # normalization.
    instance_cell_maps: dict[str, dict[str, str]] = {}

    for ci in [cell.cell_index(), *cell.called_cells()]:
        c_ = cell.kcl[ci]
        nl = _build_cell_netlist(
            c_,
            optical_nets=get_optical_nets(
                c_,
                port_types=port_types,
                allow_width_mismatch=allow_width_mismatch,
            ),
            l2n_elec_obj=l2n,
            wrap_kdb_instance=wrap_kdb_instance,
            ignore_unnamed=ignore_unnamed,
            exclude_purposes=exclude_purposes,
        )
        if equivalent_ports.get(c_.name) is not None:
            nl = nl.normalize(
                cell_name=c_.name,
                equivalent_ports=equivalent_ports,
                port_mapping=port_mapping,
            )
        nl.sort()
        if include_placement:
            # Upgrade the finished (flattened, normalized, sorted) connectivity
            # netlist to a placement-aware one, attaching the placed cell name
            # and placement only for the instances that survived flattening.
            surviving = set(nl.instance_names())
            placed = [inst for inst in c_.insts if inst.name in surviving]
            placements = {inst.name: _placement_for(inst) for inst in placed}
            cells = {inst.name: inst.cell.name for inst in placed}
            nl = PlacedNetlist.from_netlist(nl, placements, cells)
        netlists[c_.name] = nl
        instance_cell_maps[c_.name] = {inst.name: inst.cell.name for inst in c_.insts}

    if flatten:
        netlists = flatten_netlists(
            netlists,
            None if isinstance(flatten, bool) else list(flatten),
            instance_cell_maps=instance_cell_maps,
        )
    return netlists
