from __future__ import annotations

import re
from collections.abc import Mapping

from kfnetlist.morphnet.morphnet_schema import (
    Connection,
    Netlist,
    PortReference,
    SignalDomain,
)

# Type alias: net name → list of port references on that net
NetMap = dict[str, list[PortReference]]

OPTICAL_PORT_RE: re.Pattern[str] = re.compile(r"o\d")
BIT_RE: re.Pattern[str] = re.compile(r"\[-?\d+\]$")  # `in[3]` is a bit of port `in`


def domain_of(port_name: str) -> SignalDomain:
    """``o1``, ``o2``, ... are waveguide terminals; ``e1``, ``vdd``, ... are electrical."""
    if OPTICAL_PORT_RE.match(port_name):
        return SignalDomain.WAVEGUIDE
    return SignalDomain.ELECTRICAL


PinDomains = Mapping[str, Mapping[str, SignalDomain]]  # cell -> pin -> domain


def propagate_domains(
    netlist: Netlist,
    disciplines: Mapping[str, SignalDomain] | None = None,
    pin_domains: PinDomains | None = None,
) -> None:
    """Resolve port and net domains in place.

    1. A port whose type/discipline is in ``disciplines`` gets that domain
       (e.g. ``{"connection": WAVEGUIDE, "mzmselect": ELECTRICAL}``); so does a
       net whose declared type (``discipline`` property) is in it. A cell pin
       in ``pin_domains`` (``{"MZM_1X2": {"in0": WAVEGUIDE, "R1": ELECTRICAL}}``)
       has that domain, whether the cell is defined in the netlist or a leaf;
       it takes precedence over ``disciplines``.
    2. A net touching any waveguide terminal is waveguide; untyped ports on
       it become waveguide too, across the hierarchy, until nothing changes.
    3. Terminals neither typed nor reached keep the ``o<N>`` name rule.
    """
    disciplines = disciplines or {}
    pin_domains = pin_domains or {}
    ports = {
        c.name: {p.name: p for p in c.ports}
        for c in [*netlist.ext_circuits, *netlist.circuits]
    }
    typed: set[int] = set()
    for cell, circuit_ports in ports.items():
        for p in circuit_ports.values():
            domain = pin_domains.get(cell, {}).get(
                p.name, disciplines.get(p.discipline)
            )
            if domain is not None:
                p.domain = domain
                typed.add(id(p))

    def leaf_domain(cell: str, pin: str) -> SignalDomain:
        """Domain of a pin of a cell without a definition."""
        domain = pin_domains.get(cell, {}).get(BIT_RE.sub("", pin))
        return domain_of(pin) if domain is None else domain

    changed = True
    while changed:
        changed = False
        for circuit in netlist.circuits:
            cells = {s.name: s.circuit_name for s in circuit.subcircuits}
            nets: dict[str, list[Connection]] = {}
            for conn in circuit.connections:
                nets.setdefault(conn.name, []).append(conn)
            for conns in nets.values():
                refs = [r for c in conns for r in (c.source, c.target) if r is not None]
                owner_cells = [
                    cells.get(r.instance_name, "") if r.instance_name else circuit.name
                    for r in refs
                ]
                owners = [
                    ports.get(cell, {}).get(BIT_RE.sub("", r.port_name))
                    for cell, r in zip(owner_cells, refs)
                ]
                waveguide = any(
                    disciplines.get(c.properties.get("discipline", ""))
                    == SignalDomain.WAVEGUIDE
                    for c in conns
                ) or any(
                    (p.domain if p is not None else leaf_domain(cell, r.port_name))
                    == SignalDomain.WAVEGUIDE
                    for r, p, cell in zip(refs, owners, owner_cells)
                )
                domain = (
                    SignalDomain.WAVEGUIDE if waveguide else SignalDomain.ELECTRICAL
                )
                for c in conns:
                    c.domain = domain
                for p in owners:
                    if (
                        waveguide
                        and p is not None
                        and id(p) not in typed
                        and p.domain != domain
                    ):
                        p.domain = domain
                        changed = True


def typed_connections(net_map: NetMap, types: Mapping[str, str]) -> list[Connection]:
    """``net_map_to_connections``, recording each net's declared type (``wire``,
    ``connection``, ``optical``) as the ``discipline`` property."""
    connections = net_map_to_connections(net_map)
    for conn in connections:
        net_type = types.get(BIT_RE.sub("", conn.name))
        if net_type:
            conn.properties = {**conn.properties, "discipline": net_type}
    return connections


def open_node(inst: str, pin: str) -> str:
    """The node an unconnected pin is written on: its own, never one shared by all."""
    return f"nc_{inst}_{pin}"


def net_map_to_connections(net_map: NetMap) -> list[Connection]:
    """Convert a net-based connectivity map to point-to-point Connection objects.

    For each net with N port references, produces N-1 Connection objects; a net
    with one is a source-only Connection, except an ``open_node`` (an unconnected
    pin as a writer spells it), which is no net at all.
    The first port reference (in insertion order) becomes the source for
    all connections on that net.

    Complexity: O(n) where n = total port references across all nets.
    """
    connections: list[Connection] = []
    for net_name, port_refs in net_map.items():
        if len(port_refs) == 1:  # a one-pin net, unless a writer's open-pin node
            ref = port_refs[0]
            # by instance: a parser that does not know the master's pins reads `p1`
            if not net_name.startswith(open_node(ref.instance_name, "")):
                connections.append(
                    Connection(
                        name=net_name, source=ref, domain=domain_of(ref.port_name)
                    )
                )
            continue
        if not port_refs:
            continue
        source = port_refs[0]
        domain = (
            SignalDomain.WAVEGUIDE
            if any(domain_of(r.port_name) == SignalDomain.WAVEGUIDE for r in port_refs)
            else SignalDomain.ELECTRICAL
        )
        for target in port_refs[1:]:
            connections.append(
                Connection(
                    name=net_name,
                    source=source,
                    target=target,
                    domain=domain,
                )
            )
    return connections


def connections_to_instance_nets(
    connections: list[Connection],
    ground: str = "",
) -> dict[tuple[str, str], str]:
    """Build (instance_name, port_name) → net_name lookup from Connection objects.

    Single pass over connections — O(n).  Used by writers to reconstruct
    instance lines with the correct net names in port order.  A net named
    ``ground`` (when given) is emitted as node ``0``.
    """
    mapping: dict[tuple[str, str], str] = {}
    for conn in connections:
        net_name = "0" if ground and conn.name == ground else conn.name
        if conn.source is not None:
            key = (conn.source.instance_name, conn.source.port_name)
            mapping[key] = net_name
        if conn.target is not None:
            key = (conn.target.instance_name, conn.target.port_name)
            mapping[key] = net_name
    return mapping


def add_port_to_net(
    net_map: NetMap,
    net_name: str,
    instance_name: str,
    port_name: str,
) -> None:
    """Register a port reference on a net — O(1) amortized."""
    ref = PortReference(instance_name=instance_name, port_name=port_name)
    if net_name not in net_map:
        net_map[net_name] = []
    net_map[net_name].append(ref)
