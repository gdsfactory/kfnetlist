"""``.gsch`` -> every SPICE dialect and Verilog-A, read back with that format's parser.

A conversion passes only when nothing the ``.gsch`` circuit carries goes missing:
model libraries, inline code, subcircuit definitions with their pins and params, and
per element its master, nets and the values the simulator sees. Values compare as
numbers when they evaluate to one (``{0.13 * 1e-6}`` == ``130n``), else as text.
Spelling a format chooses is not a loss: case, the element letter SPICE adds
(``M1`` -> ``XM1``), ``GND``/``0``, quoting and pin names (nets compare per element).
"""

import json
import operator
import re
import warnings
from pathlib import Path

import pytest

from kfnetlist.morphnet.morphnet_schema import (
    Expression,
    Netlist,
    Operator,
    WaveformKind,
)
from kfnetlist.morphnet.netlist import (
    parse_hspice,
    parse_spectre,
    parse_spectre_spice,
    parse_spice,
    parse_vams,
    parse_xyce,
    read_gsch,
    write_hspice,
    write_spectre,
    write_spectre_spice,
    write_spice,
    write_vams,
    write_xyce,
)
from kfnetlist.morphnet.netlist.expression import format_expression
from kfnetlist.morphnet.netlist.net_utils import connections_to_instance_nets
from kfnetlist.morphnet.netlist.stimulus import stimulus_of
from kfnetlist.morphnet.netlist.value_utils import is_skipped, sim_params, to_float

FIXTURES = Path(__file__).parent / "netlists" / "gsch"
CORNERS = {"ihp_hier_top": ["mos_ff"]}  # as in golden/regen.py
FORMATS = {
    "ngspice": (write_spice, parse_spice),
    "hspice": (write_hspice, parse_hspice),
    "xyce": (write_xyce, parse_xyce),
    "spectre": (write_spectre, parse_spectre),
    "spectre_spice": (write_spectre_spice, parse_spectre_spice),
    "verilog-a": (write_vams, parse_vams),
}
FLAT = {"ngspice", "hspice", "xyce", "spectre", "spectre_spice"}  # top is the deck
GROUND = {"gnd", "0"}
BINARY = {
    Operator.ADD: operator.add,
    Operator.SUB: operator.sub,
    Operator.MUL: operator.mul,
    Operator.DIV: operator.truediv,
    Operator.POW: operator.pow,
}


def evaluate(expr: Expression | None, resolve) -> float | None:
    """The number an arithmetic expression comes to, None if it reads anything else."""
    if expr is None:
        return None
    if expr.literal is not None:
        return to_float(expr.literal)
    if expr.reference is not None:
        target = resolve(expr.reference) if resolve else None
        return evaluate(target, None) if target is not None else None
    if expr.unary is not None and expr.unary.op == Operator.NEG:
        x = evaluate(expr.unary.operand, resolve)
        return None if x is None else -x
    if expr.binary is not None and expr.binary.op in BINARY:
        lhs = evaluate(expr.binary.lhs, resolve)
        rhs = evaluate(expr.binary.rhs, resolve)
        if lhs is not None and rhs is not None:
            return BINARY[expr.binary.op](lhs, rhs)
    return None


def value(param, resolve) -> object:
    return number_or_text(param.default_value, resolve)


def number_or_text(v, resolve=None) -> object:
    if v is None:
        return None
    if v.prefixed_value is not None:
        return float(f"{to_float(v.prefixed_value):.9g}")
    if v.expression is not None:
        number = evaluate(v.expression, resolve)
        if number is not None:
            return float(f"{number:.9g}")
        text = format_expression(v.expression, "spectre", resolve)
        return re.sub(r"\s+", "", text.strip("{}'\"")).lower()
    return str(v)


def net(name: str) -> str:
    return "0" if name.lower() in GROUND else name.lower()


def element_nets(circuit) -> dict[str, list[str]]:
    nets: dict[str, list[str]] = {}
    for (inst, _), name in connections_to_instance_nets(circuit.connections).items():
        if inst:
            nets.setdefault(inst.lower(), []).append(net(name))
    return nets


def stimulus(stim) -> dict | None:
    """A source's DC/AC values and waveform, as numbers where they are numbers."""
    if stim is None:
        return None
    w = stim.waveform
    return {
        "dc": number_or_text(stim.dc),
        "mag": number_or_text(stim.ac_magnitude),
        "phase": number_or_text(stim.ac_phase),
        "waveform": None
        if w is None
        else {
            "kind": WaveformKind(w.kind).name,
            "args": {k: number_or_text(v) for k, v in w.args.items()},
            "points": [number_or_text(v) for v in w.points],
        },
    }


def view(nl: Netlist, flat_top: bool) -> dict:
    """Everything a simulator needs from ``nl``, spelled format-neutrally."""
    directives = [*nl.directives, *(d for c in nl.circuits for d in c.directives)]
    out: dict = {
        "libraries": {
            (d.kind.name, *d.value.replace('"', "").replace("section=", "").split())
            for d in directives
            if d.kind.name in ("LIB", "INCLUDE")
        },
        "circuits": {},
    }
    for circuit in nl.circuits:
        top = circuit.name == nl.top_circuit
        nets = element_nets(circuit)
        elements = {}
        for ref in circuit.subcircuits:
            if is_skipped(ref):
                continue
            params, resolve = sim_params(ref)
            elements[ref.name.lower()] = {
                # a model name, when it has one: Spectre and Verilog-A call a SPICE
                # `.model` device and an `X` subcircuit model alike
                "master": (
                    ref.properties.get("model_name") or ref.circuit_name
                ).lower(),
                "nets": sorted(nets.get(ref.name.lower(), [])),
                "params": {p.name.lower(): value(p, resolve) for p in params},
                "stimulus": stimulus(stimulus_of(nl, ref)),
            }
        content = {
            "ports": []
            if top and flat_top
            else [p.name.lower() for p in circuit.ports],
            "params": {p.name.lower(): value(p, None) for p in circuit.parameters},
            "elements": elements,
        }
        if any(content.values()):  # an all-skipped top writes an empty deck
            out["circuits"]["<top>" if top else circuit.name.lower()] = content
    return out


def letterless(written: dict, expected: dict) -> dict:
    """Map ``XM1`` back to ``M1`` where SPICE added the element letter."""
    out = {}
    for name, element in written.items():
        if name not in expected and name[1:] in expected:
            name = name[1:]
        out[name] = element
    return out


def missing(expected: dict, got: dict, path: str = "") -> list[str]:
    """Every field of ``expected`` absent from or different in ``got``."""
    if isinstance(expected, dict) and isinstance(got, dict):
        out = []
        for key, want in expected.items():
            where = f"{path}/{key}"
            if key not in got:
                out.append(f"{where}: missing")
            else:
                out += missing(want, got[key], where)
        return out
    if isinstance(expected, set):
        return [f"{path}: missing {x}" for x in sorted(expected - got)]
    return [] if expected == got else [f"{path}: {expected!r} became {got!r}"]


def convert(stem: str, fmt: str) -> tuple[Netlist, str, Netlist]:
    write, parse = FORMATS[fmt]
    nl = read_gsch(FIXTURES / f"{stem}.gsch", corners=CORNERS.get(stem, ()))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a skipped macro must show up as missing
        text = write(nl)
    return nl, text, parse(text)


@pytest.mark.parametrize("fmt", list(FORMATS))
@pytest.mark.parametrize("stem", sorted(p.stem for p in FIXTURES.glob("*.gsch")))
def test_conversion_loses_nothing(stem, fmt):
    nl, text, back = convert(stem, fmt)
    expected = view(nl, flat_top=fmt in FLAT)
    got = view(back, flat_top=fmt in FLAT)
    circuits = got["circuits"]
    if back.top_circuit and back.top_circuit.lower() in circuits:
        circuits["<top>"] = circuits.pop(back.top_circuit.lower())
    for name, circuit in circuits.items():
        if name in expected["circuits"]:
            want = expected["circuits"][name]["elements"]
            circuit["elements"] = letterless(circuit["elements"], want)
    lost = missing(expected, got)
    lost += [
        f"/macros/{m.name}: missing"
        for m in [*nl.macros, *(m for c in nl.circuits for m in c.macros)]
        if not all(line.strip() in text for line in m.body.splitlines())
    ]
    assert not lost, "\n".join(lost) + f"\n--- {fmt} ---\n{text}"


def test_the_complete_fixture_uses_every_device_kind():
    """``ihp_hier_top`` is the one fixture that has it all: keep it that way."""
    doc = json.loads((FIXTURES / "ihp_hier_top.gsch").read_text())
    kinds = {e.get("type") for e in doc.values() if isinstance(e, dict)}
    assert {"capacitor", "inductor", "vsource", "isource", "ckt"} <= kinds
    assert {"nmos", "pmos", "npn", "diode"} <= kinds
