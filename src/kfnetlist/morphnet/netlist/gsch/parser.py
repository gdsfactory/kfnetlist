"""Parse a gdsfactory+ ``.gsch`` schematic (nyancir JSON) into a morphnet ``Netlist``.

A ``.gsch`` file is a flat ``{key: entry}`` JSON map, so there is no Lark grammar.
Everything the Netlist has no field for (positions, wires, polylines, port markers)
is stashed as raw JSON so ``write_gsch`` can restore it.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping, Sequence
from itertools import chain, count
from pathlib import Path
from typing import Any

from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    Directive,
    ExternalCircuit,
    Macro,
    Netlist,
    Parameter,
    ParameterValue,
    Port,
    SignalDomain,
    Stimulus,
    SubCircuit,
)
from kfnetlist.morphnet.netlist.net_utils import (
    NetMap,
    add_port_to_net,
    domain_of,
    net_map_to_connections,
    propagate_domains,
)
from kfnetlist.morphnet.netlist.gsch.sim import (
    GROUND,
    Element,
    check_sim,
    element,
    library,
    macro,
    select_entry,
)
from kfnetlist.morphnet.netlist.expression import WORD_RE, parse_expression
from kfnetlist.morphnet.netlist.stimulus import attach, stimulus_of
from kfnetlist.morphnet.netlist.value_utils import is_si_number, parse_parameter_number

# Instance stash: ``SubCircuit.properties["__info__"]`` = ``{"__gsch__": {"key", "entry"}}``.
# The ``__`` prefix keeps it out of kfnetlist instance equality.
INFO = "__info__"
# {"key", "entry"[, "circuit": parsed circuit_name if not `model`][, "params": param
# -> the model expression it is derived from][, "computed": param -> value the
# simulation view computed from props (source waveforms, a model param named like
# a prop it reads, ...)][, "defaults": model
# prop defaults the entry does not set][, "pins": IR pin -> entry pin where they
# differ beyond case][, "tied": IR pins tied to ground, not in entry]}
STASH = "__gsch__"
MODEL = "__model__"  # the device's nyanlib model (FQN)
TOP = "__top__"  # writers write a circuit with this name flat
# Mosaic prop holding the positional `value` of a built-in
VALUE_PROPS = {
    "resistor": "resistance",
    "capacitor": "capacitance",
    "inductor": "inductance",
}

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
    """SI-prefixed numbers become values; anything else an expression (raw if unparsed)."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = repr(raw)
    if isinstance(raw, str) and is_si_number(raw):
        return Parameter(name=name, default_value=parse_parameter_number(raw))
    text = raw if isinstance(raw, str) else json.dumps(raw)
    return Parameter(
        name=name, default_value=ParameterValue(expression=parse_expression(text))
    )


def parameters(
    entry: Mapping[str, Any], device: Element | None, stash: dict[str, Any]
) -> list[Parameter]:
    """The IR params of a component, recording in ``stash`` which are not its props.

    A model with ``params`` makes each an expression over the instance's source
    props (``w = width * 1e-6``), which become ``role=source`` params; a bare rename
    of a prop (``m = m``) is that prop. Writers resolve the references (nyancad
    substitutes them textually). A model param named like a prop it reads
    (``w = w * 1e-6``) keeps its substituted value: two params of one name would not
    survive the kfnetlist bridge (settings by name). So does any expression reading
    such a prop (``ad = w * 0.5``), since ``w`` then names the device param.
    """
    if device is None:  # not simulated: the params are the props
        return [parameter(k, v) for k, v in (entry.get("props") or {}).items()]
    given = entry.get("props") or {}
    collide = {
        k for k, e in device.exprs.items() if k in device.sources and e.strip() != k
    }
    out, exprs, computed = [], {}, {}
    for k, v in device.params.items():
        expr = device.exprs.get(k)
        if expr is not None and expr.strip() != k:
            exprs[k] = expr
            if k not in device.sources and not collide & set(WORD_RE.findall(expr)):
                out.append(parameter(k, expr))
                continue
            computed[k] = v  # `w = w * 1e-6`: its value, the prop `w` has the name
        elif not (
            (k in given and given[k] == v)
            or (k in device.defaults and device.defaults[k] == v)
            or (k == "value" and entry.get("type") in VALUE_PROPS)  # resistance/...
        ):
            computed[k] = v  # source waveforms, $mfactor, ...: not props
        out.append(parameter(k, v))
    for k, v in device.sources.items():
        if k not in device.params:
            source = {"properties": {"role": "source"}}  # read by model expressions
            out.append(parameter(k, v).model_copy(update=source))
    names = {p.name for p in out}
    defaults = {k: v for k, v in device.defaults.items() if k in names}
    for field, value in (
        ("params", exprs),
        ("computed", computed),
        ("defaults", defaults),
    ):
        if value:
            stash[field] = value
    return out


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


def _nets(
    comps: Mapping[str, Mapping[str, Any]],
    stash: Mapping[str, list[dict[str, Any]]],
    names: Mapping[str, str],
) -> tuple[dict[str, list[Node]], dict[str, dict[str, Any]]]:
    """Nets (name -> ``(key, pin)`` members) and exposed top pins.

    Nets come from Mosaic ``nets`` maps, Livewire polylines, ``net`` entries and port
    markers; ``via``/``taper`` entries join everything that ends on them. A net is
    named by its Mosaic net name, else a polyline ``net``, else ``net_<n>``. A
    single pin is a net only under a Mosaic or net-entry name (nyancad writes it).
    """
    parent: dict[Node, Node] = {}
    hints: list[tuple[Node, str]] = []  # net names weaker than a Mosaic name

    def union(a: Node, b: Node) -> None:
        parent[_find(parent, a)] = _find(parent, b)

    def join(
        refs: list[tuple[str, str] | None], net: str | None = None, strong: bool = False
    ) -> None:
        """Merge ``refs``; ``net`` names them (``strong``: like a Mosaic net name)."""
        nodes: list[Node] = [r for r in refs if r is not None]
        for a, b in zip(nodes, nodes[1:]):
            union(a, b)
        if nodes:
            _find(parent, nodes[0])
            if net and strong:
                union(nodes[0], (None, net))
            elif net:
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
        entry = item["entry"]
        if entry_type(entry) == "net":  # the entry's key (or id) is the net name
            name = entry.get("id") or entry.get("_id") or item["key"]
            join(terminal_refs(entry), name, strong=True)
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
    strong = set(named)  # roots named by a Mosaic `nets` name or a net entry
    for node, net in hints:
        root = _find(parent, node)
        if root not in named and net not in taken:
            named[root] = net
            taken.add(net)

    nets: dict[str, list[Node]] = {}
    counter = 0
    for root, nodes in members.items():
        if len(nodes) < 2 and root not in strong:  # a lone pin keeps its label only
            continue
        if root not in named:
            while f"net_{counter + 1}" in taken:
                counter += 1
            counter += 1
            named[root] = f"net_{counter}"
            taken.add(named[root])
        nets[named[root]] = nodes
    return nets, top_pins


def parse_gsch(
    text: str,
    *,
    models: Mapping[str, Any] | None = None,
    sim: str = "ngspice",
    corners: str | Sequence[str] = (),
    name: str | None = None,
) -> Netlist:
    """Parse ``.gsch`` JSON text into a Netlist with one circuit (the schematic).

    Exposed port markers (no ``variant``, ``emitter``, ``detector``) are the
    circuit's ports. Devices are resolved for ``sim`` the way nyancad's netlister
    does: model entry, pins, params, and the model libraries as LIB/INCLUDE
    directives; devices nyancad would not netlist get ``sim_skip``. The net ``GND``
    is ground.

    Args:
        text: ``.gsch`` file contents.
        models: nyanlib ``{"models:<fqn>": {...}}`` (``models.nyanlib``); an inline
            top-level ``"models"`` key is merged under it.
        sim: ``ngspice``, ``xyce`` or ``vacask`` (case-insensitive).
        corners: preferred library sections; each library takes the first of these
            it has, else its first section.
        name: circuit name; defaults to ``__top__``, which writers write flat. The
            key prefix (``demo`` for ``demo:R1``) is kept as ``gsch_schema`` info.
    """
    sim = check_sim(sim)
    corners = [corners] if isinstance(corners, str) else list(corners)
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
        candidates = chain(
            [entry.get("name") or key, key], (f"{key}_{i}" for i in count(1))
        )
        names[key] = next(c for c in candidates if c not in names.values())

    devices = {key: element(entry, models, sim, key) for key, entry in comps.items()}

    def master(key: str) -> str:
        device = devices[key]
        return device.circuit if device else master_of(comps[key])

    def ir_pin(key: str, pin: str) -> str:
        device = devices.get(key)
        return device.pin(pin) if device else pin

    nets, top_pins = _nets(comps, stash, names)
    net_map: NetMap = {}
    for net, nodes in nets.items():
        for key, pin_name in nodes:
            key = key or ""
            add_port_to_net(net_map, net, names.get(key, ""), ir_pin(key, pin_name))
    tied: dict[str, list[str]] = {}  # key -> pins tied to ground, not in the entry
    for key, device in devices.items():  # open MOS bulk: nyancad ties it to ground
        connected = {ir_pin(key, p) for n in nets.values() for k, p in n if k == key}
        for pin_name in device.ground if device else ():
            if pin_name not in connected:
                add_port_to_net(net_map, GROUND, names[key], pin_name)
                tied.setdefault(key, []).append(pin_name)

    # ── the external circuits instances use; pin domains for propagate_domains
    pins_seen: dict[str, dict[str, None]] = {}  # master -> pins, in order of first use
    device_domains: dict[str, dict[str, SignalDomain]] = {}
    fqn: dict[str, str] = {}  # master -> nyanlib model of its pins
    prefix: dict[str, str] = {}  # master -> SPICE letter
    for device in filter(None, devices.values()):  # simulated: the device's pins
        pins_seen.setdefault(device.circuit, dict.fromkeys(device.ports))
        prefix.setdefault(device.circuit, device.prefix)
    fixed = set(pins_seen)
    for key, entry in comps.items():
        seen = pins_seen.setdefault(master(key), {})
        fqn.setdefault(master(key), entry.get("model") or master(key))
        open_pins = [] if master(key) in fixed else _model_pins(models, master(key))
        for p in entry.get("ports") or []:
            if p.get("port_type") in PORT_TYPE_DOMAIN:
                device_domains.setdefault(master(key), {}).setdefault(
                    ir_pin(key, p["name"]), PORT_TYPE_DOMAIN[p["port_type"]]
                )
            open_pins.append(p["name"])
        open_pins += [p for k, p in chain(*nets.values()) if k == key]
        if master(key) not in fixed:
            seen.update(dict.fromkeys(open_pins))

    pin_domains: dict[str, dict[str, SignalDomain]] = {}
    ext_circuits = []
    for cell, seen in pins_seen.items():
        nyanlib = _model_domains(models, fqn[cell])
        pin_domains[cell] = {
            pin_name: device_domains.get(cell, {}).get(pin_name)
            or nyanlib.get(pin_name)
            or domain_of(pin_name)
            for pin_name in seen
        }
        letter = prefix.get(cell)
        ext_circuits.append(
            ExternalCircuit(
                name=cell,
                ports=[Port(name=p, domain=pin_domains[cell][p]) for p in seen],
                properties={"spice_prefix": letter} if letter else {},
            )
        )

    subcircuits = []
    stimuli: list[tuple[SubCircuit, Stimulus]] = []
    for key, entry in comps.items():
        device = devices[key]
        info: dict[str, Any] = {STASH: {"key": key, "entry": entry}}
        if entry.get("model"):
            info[MODEL] = entry["model"]
        props: dict[str, str] = {}
        if device is None:
            props["sim_skip"] = "1"
        elif device.model_name:
            props["model_name"] = device.model_name
        if master(key) != master_of(entry):
            info[STASH]["circuit"] = master(key)
        entry_pins = [
            *(entry.get("nets") or {}),
            *(p["name"] for p in entry.get("ports") or []),
        ]
        renamed = {ir_pin(key, p): p for p in entry_pins}
        renamed = {q: p for q, p in renamed.items() if q.lower() != p.lower()}
        if renamed:  # SPICE pins (`p`/`n`) of a device with its own (`A`/`B`)
            info[STASH]["pins"] = renamed
        if key in tied:
            info[STASH]["tied"] = tied[key]
        ref = SubCircuit(
            name=names[key],
            circuit_name=master(key),
            parameters=parameters(entry, device, info[STASH]),
            properties={INFO: json.dumps(info), **props},
        )
        subcircuits.append(ref)
        if device is not None and device.stimulus is not None:
            stimuli.append((ref, device.stimulus))

    # ── the circuit: exposed port markers are its terminals
    prefixes = {k.split(":", 1)[0] for k in doc if ":" in k}
    schema = next(iter(prefixes)) if len(prefixes) == 1 else None
    circuit_name = name or TOP
    ports = []
    for port_name, entry in top_pins.items():
        attached = terminal_ref(entry.get("attached_port"))
        domain = {
            "photonic": SignalDomain.WAVEGUIDE,
            "electric": SignalDomain.ELECTRICAL,
        }.get(entry.get("nature"))
        if domain is None and attached and attached[0] in comps:
            domain = pin_domains[master(attached[0])].get(ir_pin(*attached))
        ports.append(Port(name=port_name, domain=domain or domain_of(port_name)))
    pin_domains[circuit_name] = {p.name: p.domain for p in ports}

    circuit_info = {"gsch_schema": schema, **stash}
    if isinstance(inline, dict):
        circuit_info["gsch_models"] = inline
    circuit = Circuit(
        name=circuit_name,
        ports=ports,
        subcircuits=subcircuits,
        connections=net_map_to_connections(net_map),  # a named single pin too
        properties={INFO: json.dumps(circuit_info)},
    )
    properties = {"ground_net": GROUND}
    if sim == "vacask":
        properties["dialect"] = "vacask"
    directives, macros = libraries(comps, models, sim, corners)
    netlist = Netlist(
        top_circuit=circuit_name,
        circuits=[circuit],
        ext_circuits=ext_circuits,
        directives=directives,
        macros=macros,
        properties=properties,
    )
    for ref, stim in stimuli:
        attach(netlist, circuit_name, ref, stim)
    propagate_domains(netlist, pin_domains=pin_domains)
    return netlist


def libraries(
    comps: Mapping[str, Mapping[str, Any]],
    models: Mapping[str, Any],
    sim: str,
    corners: Sequence[str],
) -> tuple[list[Directive], list[Macro]]:
    """Library directives and inline-code macros (equal ones once) of the models
    nyancad counts as used (devices with nets)."""
    out: list[Directive] = []
    macros: list[Macro] = []
    for entry in comps.values():
        model_def = models.get(f"models:{entry.get('model')}")
        if not entry.get("nets") or not isinstance(model_def, dict):
            continue
        chosen = select_entry(model_def, sim)
        if not chosen:
            continue
        directive = library(chosen, sim, corners)
        if directive is not None and directive not in out:
            out.append(directive)
        code = macro(chosen)
        if code is not None:
            add_macro(macros, code)
    return out, macros


def add_macro(macros: list[Macro], code: Macro) -> None:
    """Append ``code`` unless an equal macro is there; warn on a same-named one."""
    if code in macros:
        return
    if code.name and any(m.name == code.name for m in macros):
        warnings.warn(
            f"macro {code.name!r} has different code in two models; both are kept",
            stacklevel=3,
        )
    macros.append(code)


def read_gsch(
    path: str | Path,
    *,
    project_root: str | Path | None = None,
    models: Mapping[str, Any] | None = None,
    sim: str = "ngspice",
    corners: str | Sequence[str] = (),
) -> Netlist:
    """Read a ``.gsch`` file and the ``.gsch`` schematics its devices instantiate.

    Each child becomes a circuit named by its nyanlib ``name`` (else the file stem),
    with the model's ports sorted by name as pins and its prop defaults as header
    parameters, like nyancad's subcircuits. Only wired devices (with Mosaic ``nets``)
    whose ``model`` ends in ``.gsch`` and is not a library model (no nyanlib
    ``models`` entries) are followed, resolved against ``project_root``. Libraries
    and inline-code macros of the whole hierarchy are gathered on the netlist, top
    first.


    Args:
        path: the top ``.gsch`` file.
        project_root: defaults to the file's directory.
        models: defaults to ``build/models.nyanlib``, else ``models.nyanlib``, of
            the project root.
        sim: as for :func:`parse_gsch`.
        corners: as for :func:`parse_gsch`.

    Raises:
        ValueError: a child file is missing, or two children share a circuit name.
    """
    path = Path(path)
    root = Path(project_root) if project_root is not None else path.parent
    if models is None:
        found = [p for p in (root / "build", root) if (p / "models.nyanlib").is_file()]
        models = json.loads((found[0] / "models.nyanlib").read_text()) if found else {}
    models = dict(models)
    children: dict[str, Circuit] = {}  # fqn -> circuit, children before parents
    netlists: list[Netlist] = []

    def load(file: Path, fqn: str | None, stack: tuple[str, ...]) -> Netlist:
        text = file.read_text()
        doc = json.loads(text)
        for entry in doc.values() if isinstance(doc, dict) else ():
            model = entry.get("model") if isinstance(entry, dict) else None
            key = f"models:{model}"
            if (
                isinstance(model, str)
                and model.endswith(".gsch")
                and entry.get("nets")  # nyancad netlists only wired devices
                and not (models.get(key) or {}).get("models")  # else a library model
                and model not in children
                and model not in stack
            ):
                child = root / model
                if not child.is_file():
                    raise ValueError(f"{file}: child schematic {child} not found")
                circuit = load(child, model, (*stack, model)).circuits[0]
                model_def = models.get(key) or {}
                ports = model_def.get("ports") or [
                    {"name": p.name} for p in circuit.ports
                ]
                name = model_def.get("name") or Path(model).stem
                for other, c in children.items():
                    if c.name == name:
                        raise ValueError(
                            f"{child} and {root / other} are both circuit {name!r}"
                        )
                models[key] = {**model_def, "name": name, "ports": ports}
                by_name = {p.name: p for p in circuit.ports}
                circuit.name = name
                circuit.ports = [
                    by_name.get(n) or Port(name=n, domain=domain_of(n))
                    for n in sorted(p["name"] for p in ports)
                ]
                circuit.parameters = [
                    parameter(
                        p["name"], "0" if p.get("default") is None else p["default"]
                    )
                    for p in model_def.get("props") or []
                    if p.get("name")
                ]
                children[model] = circuit
        netlist = parse_gsch(text, models=models, sim=sim, corners=corners, name=fqn)
        netlists.append(netlist)
        return netlist

    top = load(
        path,
        None,
        (path.relative_to(root).as_posix(),) if path.is_relative_to(root) else (),
    )
    circuits = [*children.values(), top.circuits[0]]
    defined = {c.name for c in circuits}
    ext_circuits = {}
    directives: list[Directive] = []
    macros: list[Macro] = []
    for netlist in [top, *netlists[:-1]]:  # top first
        for ext in netlist.ext_circuits:
            if ext.name not in defined:
                ext_circuits.setdefault(ext.name, ext)
        directives += [d for d in netlist.directives if d not in directives]
        for m in netlist.macros:
            add_macro(macros, m)
    sources = [  # named again after the children's circuit names
        (netlist.circuits[0].name, ref, stim)
        for netlist in netlists
        for ref in netlist.circuits[0].subcircuits
        if (stim := stimulus_of(netlist, ref)) is not None
    ]
    top.simulation = None
    for circuit_name, ref, stim in sources:
        attach(top, circuit_name, ref, stim)
    top.circuits = circuits
    top.ext_circuits = list(ext_circuits.values())
    top.directives = directives
    top.macros = macros
    return top
