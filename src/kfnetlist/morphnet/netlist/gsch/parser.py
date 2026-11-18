"""Parse a gdsfactory+ ``.gsch`` schematic (nyancir JSON) into a morphnet ``Netlist``.

A ``.gsch`` file is a flat ``{key: entry}`` JSON map, so there is no Lark grammar.
Everything the Netlist has no field for (positions, wires, polylines, port markers)
is stashed as raw JSON so ``write_gsch`` can restore it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    ExternalCircuit,
    Netlist,
    Parameter,
    Port,
    SignalDomain,
    SubCircuit,
)
from kfnetlist.morphnet.netlist.net_utils import (
    NetMap,
    add_port_to_net,
    domain_of,
    net_map_to_connections,
    propagate_domains,
)
from kfnetlist.morphnet.netlist.value_utils import is_si_number, parse_parameter_number

# Instance stash: ``SubCircuit.properties["__info__"]`` = ``{"__gsch__": {"key", "entry"}}``.
# The ``__`` prefix keeps it out of kfnetlist instance equality.
INFO = "__info__"
STASH = "__gsch__"

# entry ``type`` -> circuit-level stash list (any other type is a component)
BUCKETS = {
    "port": "gsch_ports",
    "wire": "gsch_wires",
    "text": "gsch_wires",
    "group": "gsch_wires",
    "polyline": "gsch_routes",
    "net": "gsch_other",
    "via": "gsch_other",
    "taper": "gsch_other",
}
EXPOSED_VARIANTS = {None, "emitter", "detector"}  # ground/supply/text only name nets
PORT_TYPE_DOMAIN = {
    "optical": SignalDomain.WAVEGUIDE,
    "electrical": SignalDomain.ELECTRICAL,
    "photonic": SignalDomain.WAVEGUIDE,  # nyanlib vocabulary
    "electric": SignalDomain.ELECTRICAL,
}

Node = tuple[str | None, str]  # (entry key, pin); key None = a named net, "" = top pin


def entry_type(entry: Any) -> str | None:
    return entry.get("type") if isinstance(entry, dict) else None


def master_of(entry: Mapping[str, Any]) -> str:
    """The circuit an instance entry instantiates: its ``model``, else its ``type``."""
    return entry.get("model") or entry.get("type") or "ckt"


def terminal_ref(terminal: Any) -> tuple[str, str] | None:
    """``(component key, port)`` of a PortRef in any of its three forms."""
    if isinstance(terminal, (list, tuple)) and len(terminal) == 2:
        return terminal[0], terminal[1]
    if isinstance(terminal, dict):
        key = terminal.get("component_id") or terminal.get("device")
        key = key or terminal.get("instance")
        pin = terminal.get("port_name") or terminal.get("port")
        if key is not None and pin is not None:
            return key, pin
    return None


def terminal_refs(entry: Mapping[str, Any]) -> list[tuple[str, str] | None]:
    """The ``terminals`` (polyline) or ``ports`` (net entry) of ``entry``."""
    terms = entry.get("terminals", entry.get("ports")) or []
    return [
        terminal_ref(t) for t in (terms.values() if isinstance(terms, dict) else terms)
    ]


def parameter(name: str, raw: Any) -> Parameter:
    """SI-prefixed numbers become values; anything else is kept as ``expr`` text."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = repr(raw)
    if isinstance(raw, str) and is_si_number(raw):
        return Parameter(name=name, default_value=parse_parameter_number(raw))
    expr = raw if isinstance(raw, str) else json.dumps(raw)
    return Parameter(name=name, properties={"expr": expr})


def _find(parent: dict[Node, Node], node: Node) -> Node:
    parent.setdefault(node, node)
    while parent[node] != node:
        parent[node] = parent[parent[node]]
        node = parent[node]
    return node


def _model_pins(models: Mapping[str, Any], model: str) -> list[str]:
    """Pin order from nyanlib: a model's ``port-order``, else the ``ports`` order."""
    entry = models.get(f"models:{model}") or models.get(model) or {}
    for variant in entry.get("models") or []:
        if variant.get("port-order"):
            return list(variant["port-order"])
    return [p["name"] for p in entry.get("ports") or []]


def _model_domains(models: Mapping[str, Any], model: str) -> dict[str, SignalDomain]:
    entry = models.get(f"models:{model}") or models.get(model) or {}
    return {
        p["name"]: PORT_TYPE_DOMAIN[p["type"]]
        for p in entry.get("ports") or []
        if p.get("type") in PORT_TYPE_DOMAIN
    }


def parse_gsch(
    text: str,
    *,
    models: Mapping[str, Any] | None = None,
    name: str | None = None,
) -> Netlist:
    """Parse ``.gsch`` JSON text into a Netlist with one circuit (the schematic).

    Nets come from Mosaic ``nets`` maps, Livewire polylines, ``net`` entries and port
    markers; ``via``/``taper`` entries join everything that ends on them. A net is
    named by its Mosaic net name, else a polyline ``net``, else ``net_<n>``. Exposed
    port markers (no ``variant``, ``emitter``, ``detector``) are the circuit's ports.

    Args:
        text: ``.gsch`` file contents.
        models: nyanlib ``{"models:<fqn>": {...}}`` for device port order and domains;
            an inline top-level ``"models"`` key is merged under it.
        name: circuit name; defaults to the key prefix (``demo`` for ``demo:R1``).
    """
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise ValueError(".gsch must be a JSON object")
    inline = doc.pop("models", None)
    models = {**(inline if isinstance(inline, dict) else {}), **(models or {})}

    stash: dict[str, list[dict[str, Any]]] = {b: [] for b in set(BUCKETS.values())}
    comps: dict[str, dict[str, Any]] = {}
    for key, entry in doc.items():
        kind = entry_type(entry)
        if kind in BUCKETS:
            stash[BUCKETS[kind]].append({"key": key, "entry": entry})
        elif isinstance(entry, dict):
            comps[key] = entry
        else:
            stash["gsch_other"].append({"key": key, "entry": entry})

    # instance name = `name` else key; the key stays the reference id
    names: dict[str, str] = {}
    for key, entry in comps.items():
        n = entry.get("name") or key
        names[key] = key if n in names.values() else n

    # ── connectivity: union-find over (key, pin) nodes and named-net nodes
    parent: dict[Node, Node] = {}
    hints: list[tuple[Node, str]] = []  # net names weaker than a Mosaic name

    def union(a: Node, b: Node) -> None:
        parent[_find(parent, a)] = _find(parent, b)

    def join(refs: list[tuple[str, str] | None], net: str | None = None) -> None:
        nodes: list[Node] = [r for r in refs if r is not None]
        for a, b in zip(nodes, nodes[1:]):
            union(a, b)
        if nodes:
            _find(parent, nodes[0])
            if net:
                hints.append((nodes[0], net))

    for key, entry in comps.items():
        for pin, net in (entry.get("nets") or {}).items():
            if net:
                union((key, pin), (None, net))
    top_pins: dict[str, dict[str, Any]] = {}  # exposed marker name -> entry
    for item in stash["gsch_ports"]:
        entry = item["entry"]
        if entry.get("variant") not in EXPOSED_VARIANTS:
            net = (entry.get("nets") or {}).get("P")
            if net:
                _find(parent, (None, net))
            continue
        pin: Node = ("", entry.get("name") or item["key"])
        top_pins.setdefault(pin[1], entry)
        net = (entry.get("nets") or {}).get("P")
        attached = terminal_ref(entry.get("attached_port"))
        if attached:  # attached_port wins; `nets` only names the net
            join([pin, attached], net)
        elif net:
            union(pin, (None, net))
        else:
            _find(parent, pin)
    for item in stash["gsch_routes"]:
        join(terminal_refs(item["entry"]), item["entry"].get("net"))
    for item in stash["gsch_other"]:
        if entry_type(item["entry"]) == "net":
            join(terminal_refs(item["entry"]))
    junctions = {
        i["key"]
        for i in stash["gsch_other"]
        if entry_type(i["entry"]) in ("via", "taper")
    }
    for key in junctions:  # everything ending on a via/taper is one net
        touching = [n for n in list(parent) if n[0] == key]
        for a, b in zip(touching, touching[1:]):
            union(a, b)

    members: dict[Node, list[Node]] = {}
    named: dict[Node, str] = {}
    for node in list(parent):
        root = _find(parent, node)
        if node[0] is None:
            named.setdefault(root, node[1])
        elif node[0] in names or node[0] == "":
            members.setdefault(root, []).append(node)
    taken = set(named.values())
    for node, net in hints:
        root = _find(parent, node)
        if root not in named and net not in taken:
            named[root] = net
            taken.add(net)

    net_map: NetMap = {}
    counter = 0
    for root, nodes in members.items():
        if len(nodes) < 2:
            continue
        if root not in named:
            while f"net_{counter + 1}" in taken:
                counter += 1
            counter += 1
            named[root] = f"net_{counter}"
            taken.add(named[root])
        for key, pin_name in nodes:
            add_port_to_net(net_map, named[root], names.get(key or "", ""), pin_name)

    # ── instances and the external circuits they use
    pins_seen: dict[str, dict[str, None]] = {}  # master -> pins, in order of first use
    device_domains: dict[str, dict[str, SignalDomain]] = {}
    for key, entry in comps.items():
        master = master_of(entry)
        pins_seen.setdefault(master, {})
        for p in entry.get("ports") or []:
            if p.get("port_type") in PORT_TYPE_DOMAIN:
                device_domains.setdefault(master, {}).setdefault(
                    p["name"], PORT_TYPE_DOMAIN[p["port_type"]]
                )
            pins_seen[master].setdefault(p["name"])
    for node in parent:
        if node[0] in comps:
            entry = comps[node[0]]
            pins_seen[master_of(entry)].setdefault(node[1])

    pin_domains: dict[str, dict[str, SignalDomain]] = {}
    ext_circuits = []
    for master, seen in pins_seen.items():
        order = list(dict.fromkeys([*_model_pins(models, master), *seen]))
        nyanlib = _model_domains(models, master)
        pin_domains[master] = {
            pin_name: device_domains.get(master, {}).get(pin_name)
            or nyanlib.get(pin_name)
            or domain_of(pin_name)
            for pin_name in order
        }
        ext_circuits.append(
            ExternalCircuit(
                name=master,
                ports=[Port(name=p, domain=pin_domains[master][p]) for p in order],
            )
        )

    subcircuits = [
        SubCircuit(
            name=names[key],
            circuit_name=master_of(entry),
            parameters=[parameter(k, v) for k, v in (entry.get("props") or {}).items()],
            properties={INFO: json.dumps({STASH: {"key": key, "entry": entry}})},
        )
        for key, entry in comps.items()
    ]

    # ── top circuit: exposed port markers are its terminals
    prefixes = {k.split(":", 1)[0] for k in doc if ":" in k}
    schema = next(iter(prefixes)) if len(prefixes) == 1 else None
    circuit_name = name or schema or "top"
    ports = []
    for port_name, entry in top_pins.items():
        attached = terminal_ref(entry.get("attached_port"))
        domain = {
            "photonic": SignalDomain.WAVEGUIDE,
            "electric": SignalDomain.ELECTRICAL,
        }.get(entry.get("nature"))
        if domain is None and attached and attached[0] in comps:
            master = master_of(comps[attached[0]])
            domain = pin_domains[master].get(attached[1])
        ports.append(Port(name=port_name, domain=domain or domain_of(port_name)))
    pin_domains[circuit_name] = {p.name: p.domain for p in ports}

    info = {"gsch_schema": schema, **stash}
    if isinstance(inline, dict):
        info["gsch_models"] = inline
    circuit = Circuit(
        name=circuit_name,
        ports=ports,
        subcircuits=subcircuits,
        connections=net_map_to_connections(net_map),
        properties={INFO: json.dumps(info)},
    )
    netlist = Netlist(
        top_circuit=circuit_name, circuits=[circuit], ext_circuits=ext_circuits
    )
    propagate_domains(netlist, pin_domains=pin_domains)
    return netlist
