"""Write a morphnet ``Netlist`` as a gdsfactory+ ``.gsch`` schematic (nyancir JSON).

Entries the parser stashed (positions, wires, polylines, port markers) are restored;
everything else is synthesized in the shape Mosaic and Livewire accept.
"""

from __future__ import annotations

import json
import math
from typing import Any

from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    Netlist,
    Parameter,
    SIPrefix,
    SignalDomain,
    SubCircuit,
)
from kfnetlist.morphnet.netlist.gsch.parser import (
    BUCKETS,
    EXPOSED_VARIANTS,
    INFO,
    STASH,
    VALUE_PROPS,
    _nets,
    entry_type,
    parameter,
    terminal_ref,
    terminal_refs,
)
from kfnetlist.morphnet.netlist.gsch.sim import GROUND, source_props
from kfnetlist.morphnet.netlist.net_utils import connections_to_instance_nets
from kfnetlist.morphnet.netlist.expression import WORD_RE, format_expression
from kfnetlist.morphnet.netlist.stimulus import stimulus_of
from kfnetlist.morphnet.netlist.value_utils import format_si_value

# Mosaic device symbol types (frontend/mosaic common.cljc `device-types`). Any other
# circuit is written as a `ckt` symbol whose `model` names it.
DEVICE_TYPES = frozenset(
    "pmos nmos npn pnp resistor capacitor inductor vsource isource diode led "
    "photodiode modulator ckt amp die straight bend sbend taper transition "
    "terminator crossing ring-single ring-double spiral splitter-1x2 coupler "
    "coupler-ring mmi-1x2 mmi-2x2 mzi-1x2 mzi-2x2 grating-coupler".split()
)
# Pins of Mosaic's built-in electrical symbols; Mosaic only connects these spellings.
MOSAIC_PINS = {
    **dict.fromkeys(
        ("resistor", "capacitor", "inductor", "diode", "vsource", "isource"), ("P", "N")
    ),
    **dict.fromkeys(("nmos", "pmos"), ("D", "G", "S", "B")),
    **dict.fromkeys(("npn", "pnp"), ("C", "B", "E")),
}
IDENTITY = [1, 0, 0, 1, 0, 0]
PITCH = 4  # Mosaic grid units between synthesized symbols


def prop_value(param: Parameter, stashed: dict[str, Any]) -> Any:
    """The ``props`` value of ``param``: the original JSON value while unchanged."""
    if param.name in stashed and same(param, stashed[param.name]):
        return stashed[param.name]
    value = param.default_value
    if value is not None and value.prefixed_value is not None:
        pv = value.prefixed_value
        if pv.prefix != SIPrefix.UNSPECIFIED:
            return format_si_value(pv)
        return int(pv.double_value) if pv.double_value.is_integer() else pv.double_value
    if value is not None and value.expression is not None:
        return format_expression(value.expression, "gsch")
    return ""


def same(param: Parameter, raw: Any) -> bool:
    """``param`` still holds the JSON value ``raw`` (its role aside)."""
    return parameter(param.name, raw).default_value == param.default_value


def check_derived(sub: SubCircuit, param: Parameter, stash: dict[str, Any]) -> None:
    """Raise unless ``param``, which is not a prop, still has its parsed value."""
    expr = stash.get("params", {}).get(param.name)
    computed = stash.get("computed", {})
    if same(param, computed[param.name] if param.name in computed else expr):
        return
    entry_props = list(stash["entry"].get("props") or {})
    if expr is not None:
        sources = {
            p.name for p in sub.parameters if p.properties.get("role") == "source"
        }
        props = [
            w
            for w in dict.fromkeys(WORD_RE.findall(expr))
            if w in sources or w in entry_props
        ]
    else:  # computed by the simulation view (waveforms, ...) from the entry's props
        props = entry_props
    origin = f"model expression {expr!r}" if expr is not None else "the device's props"
    edit = ", ".join(map(repr, props)) or "its model"
    raise ValueError(
        f"{sub.name}: {param.name!r} is derived from {origin}; edit {edit} instead"
    )


def component_ref(terminal: Any) -> dict[str, Any]:
    """``terminal`` as ``{component_id, port_name}``."""
    if isinstance(terminal, dict) and {"component_id", "port_name"} <= terminal.keys():
        return terminal
    key, pin = terminal_ref(terminal) or ("", "")  # the caller checked it resolves
    return {"component_id": key, "port_name": pin}


def attached_port(keys: dict[str, str], inst: str, pin: str) -> dict[str, str]:
    return {"component_id": keys[inst], "port_name": pin}


def live_net_entry(
    entry: dict[str, Any],
    key: str,
    by_key: dict[str, str],
    junctions: set[str],
    net_of: dict[tuple[str, str], str],
    members: dict[str, list[tuple[str, str]]],
) -> dict[str, Any] | None:
    """``entry`` limited to the pins still on its net, ``None`` if none are.

    Its net is the one it names (``id``, ``_id`` or key) while that net exists, else
    the net its instance pins share. Pins of vias and tapers cannot be checked and stay.
    """
    pins = []  # (port, is a junction pin, net of an instance pin)
    for port, ref in zip(entry.get("ports", []), terminal_refs(entry)):
        if ref and ref[0] in by_key:
            pins.append((port, False, net_of.get((by_key[ref[0]], ref[1].lower()))))
        elif ref and ref[0] in junctions:
            pins.append((port, True, None))
    name = entry.get("id") or entry.get("_id") or key
    shared = {net for _, junction, net in pins if not junction}
    net = name if name in members else (shared.pop() if len(shared) == 1 else None)
    kept = [p for p, junction, n in pins if junction or (net and n == net)]
    return {**entry, "ports": kept} if kept else None


def edited_pins(
    out: dict[str, Any],
    keys: dict[str, str],
    pins: dict[str, dict[str, str]],
    pending: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """The pins of ``pending`` (entries that had no Mosaic ``nets``) whose net the
    written polylines, net entries and markers no longer join: an edit in the IR.

    Adding ``nets`` to every Livewire entry would make nyancad (and the simulation
    view) netlist devices it skipped. A pin joins its net by name: when part of
    the net already carries that name (Mosaic ``nets``, a marker, a net entry),
    only the pins outside it get ``nets``; otherwise all its pending pins do.
    """
    if not pending:
        return {}
    by_key = {k: n for n, k in keys.items()}
    comps: dict[str, dict[str, Any]] = {}
    buckets: dict[str, list[dict[str, Any]]] = {b: [] for b in set(BUCKETS.values())}
    for key, entry in out.items():
        kind = entry_type(entry)
        if key in by_key:
            comps[key] = entry
        else:
            buckets[BUCKETS.get(kind or "", "gsch_other")].append(
                {"key": key, "entry": entry}
            )
    found, _ = _nets(comps, buckets, by_key)
    group = {
        (by_key.get(key or "", ""), pin.lower()): name
        for name, nodes in found.items()
        for key, pin in nodes
    }
    named: set[str] = set()  # names that bind on their own (weak hints do not)
    for key, entry in out.items():
        kind = entry_type(entry)
        if key in by_key or (kind == "port" and not entry.get("attached_port")):
            named |= set((entry.get("nets") or {}).values())
        elif kind == "net":
            named.add(entry.get("id") or entry.get("_id") or key)
    members: dict[str, set[tuple[str, str]]] = {}
    for inst, inst_pins in pins.items():
        for pin, net in inst_pins.items():
            members.setdefault(net, set()).add((inst, pin.lower()))
    add: dict[str, dict[str, str]] = {}
    for inst, nets in pending.items():
        for pin, net in nets.items():
            on_net = {m for m, g in group.items() if g == net}
            if on_net == members[net]:
                continue  # the file still says exactly this, name included
            if net in named and group.get((inst, pin.lower())) == net:
                continue  # already on the part that carries the name
            add.setdefault(inst, {})[pin] = net
    # ponytail: an exposed marker without `nets` on an edited, otherwise unnamed
    # net is not named; name the marker too if that edit shows up
    return add


def symbol_of(sub: SubCircuit, stash: dict[str, Any] | None) -> str:
    """The Mosaic symbol ``sub`` is written as (before any master change)."""
    return stash["entry"].get("type", "") if stash else sub.circuit_name


def stash_of(sub: SubCircuit) -> dict[str, Any] | None:
    return json.loads(sub.properties.get(INFO) or "{}").get(STASH)


def parsed_master(stash: dict[str, Any]) -> str | None:
    """The ``circuit_name`` the parser gave the instance of ``stash``."""
    return stash.get(
        "circuit", stash["entry"].get("model") or stash["entry"].get("type")
    )


def circuit_stash(circuit: Circuit, field: str) -> list[dict[str, Any]]:
    return json.loads(circuit.properties.get(INFO) or "{}").get(field) or []


def write_gsch(netlist: Netlist) -> str:
    """Write the top circuit of ``netlist`` as ``.gsch`` JSON text.

    Instances and port markers parsed from a ``.gsch`` keep their keys and layout
    fields; others get ``type``, ``name``, ``x``, ``y`` on a grid and the key
    ``name``. Wires and ``net``/``via``/``taper`` entries are restored, polylines
    whose endpoints survive are restored in ``{component_id, port_name}`` form.
    """
    if not netlist.circuits:
        raise ValueError("netlist has no circuit to write")
    circuit = next(
        (c for c in netlist.circuits if c.name == netlist.top_circuit),
        netlist.circuits[-1],
    )
    info = json.loads(circuit.properties.get(INFO) or "{}")
    # ponytail: files written from non-gsch sources have no Mosaic wires, so Mosaic
    # recomputes `nets` on its first edit; Livewire keeps them.
    stashes = {sub.name: stash_of(sub) for sub in circuit.subcircuits}
    symbols = {  # built-in symbols: instance -> Mosaic pins
        sub.name: MOSAIC_PINS.get(symbol_of(sub, stashes[sub.name]), ())
        for sub in circuit.subcircuits
    }
    parsed = {  # instances still on their parsed master: their device pins apply
        sub.name: stash
        for sub in circuit.subcircuits
        if (stash := stashes[sub.name]) and sub.circuit_name == parsed_master(stash)
    }
    pins: dict[str, dict[str, str]] = {}
    for (inst, pin), net in connections_to_instance_nets(circuit.connections).items():
        device = parsed.get(inst, {})
        if net == GROUND and pin in device.get("tied", ()):
            continue  # the parser tied this open pin to ground
        pin = device.get("pins", {}).get(pin, pin)  # SPICE `p` -> the entry's `A`
        if pin.upper() in symbols.get(inst, ()):  # `p` -> `P`
            pin = pin.upper()
        pins.setdefault(inst, {})[pin] = net

    taken = {s["key"] for s in stashes.values() if s}
    taken |= {
        i["key"]
        for f in info
        if f.startswith("gsch_") and isinstance(info[f], list)
        for i in info[f]
    }
    cols = math.ceil(math.sqrt(len(circuit.subcircuits) + len(circuit.ports))) or 1
    placed = 0

    def fresh(base: str) -> str:
        key = base
        while key in taken:
            key += "_"
        taken.add(key)
        return key

    def place() -> dict[str, Any]:
        nonlocal placed
        x, y = (placed % cols) * PITCH, (placed // cols) * PITCH
        placed += 1
        return {"x": x, "y": y, "transform": IDENTITY}

    def synthesized(entry: dict[str, Any], name: str) -> str:
        """Key for a new entry: its name, else a free variant plus an ``id``."""
        key = fresh(name)
        if key != name:
            entry["id"] = key  # gfp matches `id` before `name`
        return key

    out: dict[str, Any] = {}
    pending: dict[str, dict[str, str]] = {}  # instances written without `nets`
    keys: dict[str, str] = {}  # instance name -> entry key
    members: dict[str, list[tuple[str, str]]] = {}  # net -> (instance name, pin)
    net_of: dict[tuple[str, str], str] = {}  # (instance name, pin.lower()) -> net
    for sub in circuit.subcircuits:
        stash = stashes[sub.name]
        entry: dict[str, Any] = dict(stash["entry"]) if stash else {}
        if not stash:
            entry = {"type": "", **place()}
        key = stash["key"] if stash else synthesized(entry, sub.name)
        keys[sub.name] = key
        new_master = sub.name not in parsed  # synthesized, or master changed
        if new_master:
            builtin = sub.circuit_name in DEVICE_TYPES
            entry["type"] = sub.circuit_name if builtin else "ckt"
            if builtin:
                entry.pop("model", None)
            else:
                entry["model"] = sub.circuit_name
        if not stash or "name" in stash["entry"] or sub.name != key:
            entry["name"] = sub.name  # a parsed entry without `name` is named by key
        spelling = {
            pin.lower(): pin
            for pin in [
                *(entry.get("nets") or {}),
                *(p["name"] for p in entry.get("ports") or []),
            ]
        }
        nets = {
            spelling.get(pin.lower(), pin): net
            for pin, net in pins.get(sub.name, {}).items()
        }
        if stash and "nets" not in stash["entry"]:  # Livewire: wired by polylines
            pending[sub.name] = nets
        else:
            entry["nets"] = nets
        for pin, net in nets.items():
            members.setdefault(net, []).append((sub.name, pin))
            net_of[sub.name, pin.lower()] = net
        stashed_props = entry.get("props") or {}
        simulated = stash and not new_master and sub.properties.get("sim_skip") != "1"
        sim = stash if simulated else {}
        derived = {*sim.get("params", {}), *sim.get("computed", {})}
        defaults = sim.get("defaults", {})
        # a simulated instance keeps the props its params do not show (`model`,
        # `tran` strings, ...); otherwise the params are the props
        entry["props"] = dict(stashed_props) if simulated else {}
        for p in sub.parameters:
            if p.name in derived and p.properties.get("role") != "source":
                check_derived(sub, p, sim)  # no prop to go back to
                continue
            unset = p.name not in stashed_props and p.name in defaults
            if unset and same(p, defaults[p.name]):
                continue  # still the model's default
            prop = (
                VALUE_PROPS.get(entry["type"], p.name) if p.name == "value" else p.name
            )
            p = p.model_copy(update={"name": prop})
            entry["props"][prop] = prop_value(p, stashed_props)
        stim = stimulus_of(netlist, sub) if simulated else None
        if stim is not None:
            entry["props"] = source_props(sub.name, stim, entry["props"])
        if stash and "props" not in stash["entry"] and not entry["props"]:
            del entry["props"]
        # ponytail: a param removed from a simulated instance keeps its prop; drop
        # props without a param once instances can say which props they show.
        out[key] = entry

    markers: dict[str, dict[str, Any]] = {}
    for item in circuit_stash(circuit, "gsch_ports"):
        if item["entry"].get("variant") not in EXPOSED_VARIANTS:
            out[item["key"]] = item["entry"]  # ground/supply/text: names a net
        else:
            markers.setdefault(item["entry"].get("name") or item["key"], item)
    for port in circuit.ports:
        net = pins.get("", {}).get(port.name, port.name)
        if port.name in markers:
            item = markers[port.name]
            entry = dict(item["entry"])
            if "nets" in entry:
                entry["nets"] = {"P": net}
            attached = terminal_ref(entry.get("attached_port"))
            on_net = {(keys[i], p.lower()) for i, p in members.get(net, [])}
            if attached and (attached[0], attached[1].lower()) not in on_net:
                entry.pop("attached_port")  # edited away: rebind to the net's pin
                if members.get(net):
                    entry["attached_port"] = attached_port(keys, *members[net][0])
            out[item["key"]] = entry
            continue
        entry = {
            "type": "port",
            "name": port.name,
            **place(),
            "nets": {"P": net},
            "nature": "photonic"
            if port.domain == SignalDomain.WAVEGUIDE
            else "electric",
        }
        if members.get(net):
            entry["attached_port"] = attached_port(keys, *members[net][0])
        out[synthesized(entry, port.name)] = entry

    other = circuit_stash(circuit, "gsch_other")
    junctions = {i["key"] for i in other}
    alive = set(keys.values()) | junctions
    by_key = {k: n for n, k in keys.items()}
    for item in circuit_stash(circuit, "gsch_wires"):
        out[item["key"]] = item["entry"]
    for item in other:
        entry = item["entry"]
        if entry_type(entry) == "net":
            live = live_net_entry(
                entry, item["key"], by_key, junctions, net_of, members
            )
            if live is None:
                continue
            entry = live
        out[item["key"]] = entry
    for item in circuit_stash(circuit, "gsch_routes"):
        entry = item["entry"]
        ends = terminal_refs(entry)
        refs = [e for e in ends if e]
        pin_nets = [net_of.get((by_key[k], p.lower())) for k, p in refs if k in by_key]
        # a polyline joins its pins: drop it once they are on different nets
        joined = None not in pin_nets and len(set(pin_nets)) <= 1
        if (
            ends
            and len(refs) == len(ends)
            and joined
            and all(k in alive for k, _ in refs)
        ):
            terminals = entry.get("terminals")
            if isinstance(terminals, dict):  # Livewire drops {device, port} polylines
                entry = {
                    **entry,
                    "terminals": {r: component_ref(t) for r, t in terminals.items()},
                }
            out[item["key"]] = entry
    for inst, nets in edited_pins(out, keys, pins, pending).items():
        out[keys[inst]]["nets"] = nets
    if "gsch_models" in info:
        out["models"] = info["gsch_models"]
    return json.dumps(out, indent=2)
