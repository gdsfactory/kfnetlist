"""Netlist orchestrator: combines optical-net geometry + electrical L2N."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Protocol

from kfnetlist import Net, Netlist, NetlistPort, PortArrayRef, PortRef

from ._geometry import _BaseLike, get_optical_nets
from ._l2n import l2n_elec as _l2n_elec
from ._settings import serialize_setting

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from klayout import db as kdb


class _FactoryLike(Protocol):
    lvs_equivalent_ports: list[list[str]] | None


class _SettingsLike(Protocol):
    def model_dump(self) -> dict[str, object]: ...


class _LibraryLike(Protocol):
    def name(self) -> str: ...


class _PortLike(Protocol):
    name: str
    port_type: str
    layer_info: kdb.LayerInfo
    trans: kdb.Trans
    base: _BaseLike


class _CellLike(Protocol):
    name: str
    factory_name: str
    virtual: bool
    lvs_equivalent_ports: list[list[str]] | None

    # Declared as read-only properties (rather than class attributes) so that
    # implementations are free to expose narrower concrete types: protocol
    # attributes are invariant, properties are covariant on read.
    @property
    def settings(self) -> _SettingsLike: ...
    @property
    def library_cell(self) -> _CellLike: ...
    @property
    def kcl(self) -> _KCLLike: ...
    @property
    def ports(self) -> Iterable[_PortLike]: ...
    @property
    def insts(self) -> Iterable[_InstanceLike]: ...
    def has_factory_name(self) -> bool: ...
    def is_library_cell(self) -> bool: ...
    def library(self) -> _LibraryLike: ...
    def cell_index(self) -> int: ...


class _InstanceLike(Protocol):
    name: str
    na: int
    nb: int
    instance: kdb.Instance
    dcplx_trans: kdb.DCplxTrans
    purpose: str | None

    # Read-only for the same covariance reason as `_CellLike.settings`.
    @property
    def cell(self) -> _CellLike: ...
    @property
    def ports(self) -> Iterable[_PortLike]: ...
    def is_named(self) -> bool: ...


class _KCLLike(Protocol):
    name: str
    dbu: float
    layout: kdb.Layout
    connectivity: Sequence[Sequence[kdb.LayerInfo]]
    factories: Mapping[str, _FactoryLike]
    virtual_factories: Mapping[str, _FactoryLike]

    def __getitem__(self, key: int | str) -> _CellLike: ...


class _RootCellLike(_CellLike, Protocol):
    def called_cells(self) -> Iterable[int]: ...


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


def _create_inst_entry(nl: Netlist, inst: _InstanceLike) -> None:
    cell = inst.cell
    if cell.has_factory_name():
        component = cell.factory_name
    else:
        component = cell.name
    kcl_name = cell.library().name() if cell.is_library_cell() else cell.kcl.name
    settings = {k: serialize_setting(v) for k, v in cell.settings.model_dump().items()}
    nl.create_inst(
        name=inst.name,
        kcl=kcl_name,
        component=component,
        settings=settings,
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
    nl.flatten_instances(list(inst_names))
    for inst_name in inst_names:
        nl.instances.pop(inst_name, None)
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
    """
    if equivalent_ports is None:
        equivalent_ports = _gather_equivalent_ports(cell)

    port_mapping: dict[str, dict[str, str]] = defaultdict(dict)
    for cell_name, list_of_port_lists in equivalent_ports.items():
        for port_list in list_of_port_lists:
            if port_list:
                p1 = port_list[0]
                for port_name in port_list:
                    port_mapping[cell_name][port_name] = p1

    l2n = _l2n_elec(
        cell,
        mark_port_types=mark_port_types,
        connectivity=connectivity,
        port_mapping=port_mapping,
    )

    netlists: dict[str, Netlist] = {}

    # NOTE: this pass mirrors a redundant remap loop in the original
    # ProtoTKCell.netlist body; preserved for behavioural parity.
    for cell_name, eqps in equivalent_ports.items():
        for eqp_list in eqps:
            if eqp_list:
                p1 = eqp_list[0]
                for p in eqp_list:
                    port_mapping[cell_name][p] = p1

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
        netlists[c_.name] = nl
        nl.sort()
    return netlists
