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
    EXPOSED_VARIANTS,
    INFO,
    STASH,
    entry_type,
    parameter,
    terminal_ref,
    terminal_refs,
)
from kfnetlist.morphnet.netlist.net_utils import connections_to_instance_nets
from kfnetlist.morphnet.netlist.value_utils import format_si_value

# Mosaic device symbol types (frontend/mosaic common.cljc `device-types`). Any other
# circuit is written as a `ckt` symbol whose `model` names it.
DEVICE_TYPES = frozenset(
    "pmos nmos npn pnp resistor capacitor inductor vsource isource diode led "
    "photodiode modulator ckt amp die straight bend sbend taper transition "
    "terminator crossing ring-single ring-double spiral splitter-1x2 coupler "
    "coupler-ring mmi-1x2 mmi-2x2 mzi-1x2 mzi-2x2 grating-coupler".split()
)
IDENTITY = [1, 0, 0, 1, 0, 0]
PITCH = 4  # Mosaic grid units between synthesized symbols


def prop_value(param: Parameter, stashed: dict[str, Any]) -> Any:
    """The ``props`` value of ``param``: the original JSON value while unchanged."""
    if param.name in stashed and parameter(param.name, stashed[param.name]) == param:
        return stashed[param.name]
    value = param.default_value
    if value is not None and value.prefixed_value is not None:
        pv = value.prefixed_value
        if pv.prefix != SIPrefix.UNSPECIFIED:
            return format_si_value(pv)
        return int(pv.double_value) if pv.double_value.is_integer() else pv.double_value
    return param.properties.get("expr", "")


def component_ref(terminal: Any) -> dict[str, Any]:
    """``terminal`` as ``{component_id, port_name}``."""
    if isinstance(terminal, dict) and {"component_id", "port_name"} <= terminal.keys():
        return terminal
    key, pin = terminal_ref(terminal) or ("", "")  # the caller checked it resolves
    return {"component_id": key, "port_name": pin}


def stash_of(sub: SubCircuit) -> dict[str, Any] | None:
    return json.loads(sub.properties.get(INFO) or "{}").get(STASH)


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
    inst_nets = connections_to_instance_nets(circuit.connections)
    pins: dict[str, dict[str, str]] = {}
    members: dict[str, list[tuple[str, str]]] = {}  # net -> instance pins
    for (inst, pin), net in inst_nets.items():
        pins.setdefault(inst, {})[pin] = net
        if inst:
            members.setdefault(net, []).append((inst, pin))

    stashes = {sub.name: stash_of(sub) for sub in circuit.subcircuits}
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

    out: dict[str, Any] = {}
    keys: dict[str, str] = {}  # instance name -> entry key
    for sub in circuit.subcircuits:
        stash = stashes[sub.name]
        entry: dict[str, Any] = dict(stash["entry"]) if stash else {}
        keys[sub.name] = key = stash["key"] if stash else fresh(sub.name)
        if not stash:
            entry = {"type": "", **place()}
        if not stash or sub.circuit_name != (entry.get("model") or entry.get("type")):
            builtin = sub.circuit_name in DEVICE_TYPES
            entry["type"] = sub.circuit_name if builtin else "ckt"
            if builtin:
                entry.pop("model", None)
            else:
                entry["model"] = sub.circuit_name
        entry["name"] = sub.name
        spelling = {
            pin.lower(): pin
            for pin in [
                *(entry.get("nets") or {}),
                *(p["name"] for p in entry.get("ports") or []),
            ]
        }
        entry["nets"] = {
            spelling.get(pin.lower(), pin): net
            for pin, net in pins.get(sub.name, {}).items()
        }
        stashed_props = entry.get("props") or {}
        entry["props"] = {p.name: prop_value(p, stashed_props) for p in sub.parameters}
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
            inst, pin = members[net][0]
            entry["attached_port"] = {
                "component_id": keys.get(inst, inst),
                "port_name": pin,
            }
        out[fresh(port.name)] = entry

    other = circuit_stash(circuit, "gsch_other")
    alive = set(keys.values()) | {i["key"] for i in other}
    for item in circuit_stash(circuit, "gsch_wires"):
        out[item["key"]] = item["entry"]
    for item in other:
        entry = item["entry"]
        if entry_type(entry) == "net":
            refs = terminal_refs(entry)
            kept = [
                t for t, r in zip(entry.get("ports", []), refs) if r and r[0] in alive
            ]
            entry = {**entry, "ports": kept}
        out[item["key"]] = entry
    for item in circuit_stash(circuit, "gsch_routes"):
        entry = item["entry"]
        ends = terminal_refs(entry)
        terminals = entry.get("terminals")
        if ends and all(e and e[0] in alive for e in ends):
            if isinstance(terminals, dict):  # Livewire drops {device, port} polylines
                entry = {
                    **entry,
                    "terminals": {r: component_ref(t) for r, t in terminals.items()},
                }
            out[item["key"]] = entry
    if "gsch_models" in info:
        out["models"] = info["gsch_models"]
    return json.dumps(out, indent=2)
