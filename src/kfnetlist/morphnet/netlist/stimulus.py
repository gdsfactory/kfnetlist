"""Source stimuli (``Simulation.stimuli``) in every dialect's native syntax.

One ``Stimulus`` per V/I element, named ``"<circuit>/<instance>"`` and pointed to by
the element's ``properties["stimulus"]``. Waveform args use SPICE semantics with
Spectre names (see ``ARGS``); each dialect renders and reads them natively:

- SPICE: ``DC 0.9 AC 1 0 PULSE(0 1.8 1n 10p 10p 1n 2n)`` (positional);
- Spectre/VACASK: ``dc=0.9 mag=1 type=pulse val0=0 ...``;
- Verilog-A/AMS: LRM Annex E Table E.1 primitives ``vpulse #(.dc(0.9), .val0(0), .td(1n))``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    ParameterValue,
    Simulation,
    Stimulus,
    SubCircuit,
    Waveform,
    WaveformKind,
)
from kfnetlist.morphnet.netlist.expression import WRAP, parameter_value, value_text
from kfnetlist.morphnet.netlist.value_utils import to_float

__all__ = [
    "ARGS",
    "attach",
    "from_primitive",
    "from_spectre",
    "parse_spice",
    "primitive",
    "spectre_params",
    "spice_text",
    "stimulus_keys",
    "stimulus_of",
]

# kind -> (SPICE function, Spectre type, args in SPICE positional order)
ARGS: dict[WaveformKind, tuple[str, str, list[str]]] = {
    WaveformKind.PULSE: ("PULSE", "pulse",
                         ["val0", "val1", "delay", "rise", "fall", "width", "period"]),
    WaveformKind.SIN: ("SIN", "sine", ["sinedc", "ampl", "freq", "delay", "theta"]),
    WaveformKind.EXP: ("EXP", "exp", ["val0", "val1", "delay", "tau1", "td2", "tau2"]),
    WaveformKind.SFFM: ("SFFM", "fm", ["sinedc", "ampl", "freq", "modindex", "modfreq"]),
    WaveformKind.PWL: ("PWL", "pwl", []),
}  # fmt: skip
BY_FUNCTION = {func: kind for kind, (func, _, _) in ARGS.items()}
BY_TYPE = {typ: kind for kind, (_, typ, _) in ARGS.items()}
GAP = "0"  # a missing positional arg before a given one (SPICE's default for all but
# val0/val1/width/period, which nyancad never leaves out)

# Verilog-AMS LRM Annex E Table E.1: primitive and its names for ours.
PRIMITIVE: dict[WaveformKind, tuple[str, dict[str, str]]] = {
    WaveformKind.PULSE: ("pulse", {"delay": "td"}),
    WaveformKind.SIN: ("sine", {"sinedc": "offset", "delay": "td", "theta": "damp"}),
    WaveformKind.EXP: ("exp", {"delay": "td0", "tau1": "tau0", "td2": "td1",
                               "tau2": "tau1"}),
    WaveformKind.SFFM: ("sine", {"sinedc": "offset", "modindex": "fmmodindex",
                                 "modfreq": "fmmodfreq"}),
    WaveformKind.PWL: ("pwl", {}),
}  # fmt: skip
VACASK_DROP_ZERO = {"delay", "theta"}  # InSpice leaves these out when 0
FUNC_RE = re.compile(r"([A-Za-z]+)\((.*)\)$", re.S)


def stimulus_of(netlist: Netlist, ref: SubCircuit) -> Stimulus | None:
    """The stimulus ``ref`` points to, None when it has none."""
    name = ref.properties.get("stimulus")
    if not name or netlist.simulation is None:
        return None
    return next((s for s in netlist.simulation.stimuli if s.name == name), None)


def attach(netlist: Netlist, circuit: str, ref: SubCircuit, stim: Stimulus) -> None:
    """Record ``stim`` as what drives ``ref`` (an element of ``circuit``)."""
    stim.name = f"{circuit}/{ref.name}"
    ref.properties = {**ref.properties, "stimulus": stim.name}
    if netlist.simulation is None:
        netlist.simulation = Simulation()
    netlist.simulation.stimuli = [
        *(s for s in netlist.simulation.stimuli if s.name != stim.name),
        stim,
    ]


def _text(value: ParameterValue, dialect: str) -> str:
    return value_text(value, dialect)


def _spice(value: ParameterValue, dialect: str) -> str:
    """A positional SPICE value: a param name is wrapped too (``PULSE(0 {vdd})``)."""
    text = value_text(value, dialect)
    if value.expression is not None and value.expression.reference is not None:
        opening, closing = WRAP[dialect]
        return f"{opening}{text}{closing}"
    return text


def _number(value: ParameterValue | None) -> float | None:
    if value is None or value.prefixed_value is None:
        return None
    return to_float(value.prefixed_value)


def _value(raw: ParameterValue | str) -> ParameterValue:
    return raw if isinstance(raw, ParameterValue) else parameter_value(str(raw))


# ── SPICE ──────────────────────────────────────────────────────────────


def spice_text(stim: Stimulus, dialect: str) -> str:
    """``DC d AC m p FUNC(args)``: the positional value of a SPICE V/I line."""
    parts: list[str] = []
    if stim.dc is not None:
        parts += ["DC", _spice(stim.dc, dialect)]
    if stim.ac_magnitude is not None or stim.ac_phase is not None:
        mag = stim.ac_magnitude or parameter_value("1")
        parts += ["AC", _spice(mag, dialect)]
        if stim.ac_phase is not None:
            parts.append(_spice(stim.ac_phase, dialect))
    if stim.waveform is not None:
        w = stim.waveform
        func, _, names = ARGS[WaveformKind(w.kind)]
        if w.kind == WaveformKind.PWL:
            args = [_spice(p, dialect) for p in w.points]
        else:
            last = max((i for i, n in enumerate(names) if n in w.args), default=-1)
            args = [
                _spice(w.args[n], dialect) if n in w.args else GAP
                for n in names[: last + 1]
            ]
        parts.append(f"{func}({' '.join(args)})")
    return " ".join(parts)


def _args(text: str) -> list[str]:
    """Args of ``FUNC(...)``: split on spaces/commas outside braces and quotes."""
    out, depth, quote, cur = [], 0, False, ""
    for ch in text:
        if ch == "'" and depth == 0:
            quote = not quote
        elif not quote and ch in "{(":
            depth += 1
        elif not quote and ch in "})":
            depth -= 1
        if not quote and depth == 0 and ch in " \t,":
            if cur:
                out.append(cur)
            cur = ""
            continue
        cur += ch
    return [*out, cur] if cur else out


def parse_spice(text: str) -> Stimulus:
    """The stimulus of a SPICE V/I value (the tokens after the nodes)."""
    stim = Stimulus()
    tokens = _args(text)
    i = 0
    while i < len(tokens):
        tok, upper = tokens[i], tokens[i].upper()
        func = FUNC_RE.match(tok)
        if func and func[1].upper() in BY_FUNCTION:
            kind = BY_FUNCTION[func[1].upper()]
            values = [parameter_value(a) for a in _args(func[2])]
            if kind == WaveformKind.PWL:
                stim.waveform = Waveform(kind=kind, points=values)
            else:
                names = ARGS[kind][2]
                stim.waveform = Waveform(kind=kind, args=dict(zip(names, values)))
        elif upper == "DC" and i + 1 < len(tokens):
            stim.dc = parameter_value(tokens[i + 1])
            i += 1
        elif upper == "AC" and i + 1 < len(tokens):
            stim.ac_magnitude = parameter_value(tokens[i + 1])
            i += 1
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            if nxt and not FUNC_RE.match(nxt) and nxt.upper() not in ("DC", "AC"):
                stim.ac_phase = parameter_value(nxt)
                i += 1
        elif stim.dc is None and i == 0:
            stim.dc = parameter_value(tok)  # `V1 a 0 1.8`: the DC value
        i += 1
    return stim


# ── Spectre / VACASK ───────────────────────────────────────────────────


def spectre_params(stim: Stimulus, dialect: str) -> list[tuple[str, str]]:
    """``(name, text)`` of a Spectre ``vsource``/``isource``. VACASK takes InSpice's
    forms: quoted ``type``, no zero ``delay``/``theta``, no ``rise <= 0``, and ``td2``
    counted from the delay."""
    vacask = dialect == "vacask"
    out: list[tuple[str, str]] = []
    for name, value in (
        ("dc", stim.dc),
        ("mag", stim.ac_magnitude),
        ("phase", stim.ac_phase),
    ):
        if value is not None:
            out.append((name, _text(value, dialect)))
    w = stim.waveform
    if w is None:
        return out
    kind = WaveformKind(w.kind)
    typ = ARGS[kind][1]
    out.append(("type", f'"{typ}"' if vacask else typ))
    if kind == WaveformKind.PWL:
        out.append(("wave", f"[{' '.join(_text(p, dialect) for p in w.points)}]"))
        return out
    for name in ARGS[kind][2]:
        value = w.args.get(name)
        if value is None:
            continue
        number = _number(value)
        if vacask and name in VACASK_DROP_ZERO and number == 0:
            continue
        if vacask and name == "rise" and number is not None and number <= 0:
            continue
        text = _text(value, dialect)
        if vacask and name == "td2" and "delay" in w.args:
            delay = w.args["delay"]
            if number is not None and _number(delay) is not None:
                text = f"{number - (_number(delay) or 0):g}"
            else:  # ponytail: an expression stays symbolic
                text = f"({text})-({_text(delay, dialect)})"
        out.append((name, text))
    return out


def from_spectre(
    params: Mapping[str, ParameterValue | str], dialect: str = "spectre"
) -> Stimulus | None:
    """The stimulus in a Spectre source's params, None when they hold none."""
    stim = Stimulus(
        dc=_value(params["dc"]) if "dc" in params else None,
        ac_magnitude=_value(params["mag"]) if "mag" in params else None,
        ac_phase=_value(params["phase"]) if "phase" in params else None,
    )
    raw = params.get("type")
    if raw is not None:
        typ = raw if isinstance(raw, str) else _text(raw, "spectre")
        kind = BY_TYPE.get(typ.strip().strip("\"'").lower())
        if kind == WaveformKind.PWL:
            text = str(params.get("wave", "")).strip()
            text = text.removeprefix("[").removesuffix("]")
            points = [parameter_value(a) for a in _args(text)]
            stim.waveform = Waveform(kind=kind, points=points)
        elif kind is not None:
            args = {n: _value(params[n]) for n in ARGS[kind][2] if n in params}
            if dialect == "vacask" and "td2" in args and "delay" in args:
                td2, delay = _number(args["td2"]), _number(args["delay"])
                if td2 is not None and delay is not None:
                    args["td2"] = parameter_value(f"{td2 + delay:g}")
            stim.waveform = Waveform(kind=kind, args=args)
    if stim == Stimulus():
        return None
    return stim


def stimulus_keys(stim: Stimulus | None) -> set[str]:
    """The Spectre/primitive params ``stim`` was read from (not device params)."""
    if stim is None:
        return set()
    keys = {"dc", "mag", "phase", "type", "wave"}
    if stim.waveform is not None:
        kind = WaveformKind(stim.waveform.kind)
        keys |= set(ARGS[kind][2]) | set(PRIMITIVE[kind][1].values())
    return keys


# ── Verilog-A/AMS primitives (LRM Annex E Table E.1) ───────────────────


def primitive(stim: Stimulus, current: bool) -> tuple[str, list[tuple[str, str]]]:
    """``(master, [(param, text)])`` of the Table E.1 primitive for ``stim``. A DC/AC
    source is a ``vsine`` with only ``dc``/``mag``/``phase`` (LRM E.2.2.3)."""
    params = [
        (name, _text(value, "vams"))
        for name, value in (
            ("dc", stim.dc),
            ("mag", stim.ac_magnitude),
            ("phase", stim.ac_phase),
        )
        if value is not None
    ]
    w = stim.waveform
    shape, names = (
        PRIMITIVE.get(WaveformKind(w.kind), ("sine", {})) if w else ("sine", {})
    )
    if w is not None and w.kind == WaveformKind.PWL:
        params.append(("wave", f"'{{{', '.join(_text(p, 'vams') for p in w.points)}}}"))
    elif w is not None:
        for name in ARGS[WaveformKind(w.kind)][2]:
            if name in w.args:
                params.append((names.get(name, name), _text(w.args[name], "vams")))
    return ("i" if current else "v") + shape, params


def from_primitive(
    master: str, params: Mapping[str, ParameterValue | str]
) -> Stimulus | None:
    """The stimulus of a Table E.1 source primitive, None for any other master."""
    m = master.lower()
    if len(m) < 2 or m[0] not in "vi" or m[1:] not in ("pulse", "sine", "exp", "pwl"):
        return None
    stim = Stimulus(
        dc=_value(params["dc"]) if "dc" in params else None,
        ac_magnitude=_value(params["mag"]) if "mag" in params else None,
        ac_phase=_value(params["phase"]) if "phase" in params else None,
    )
    shape = m[1:]
    if shape == "pwl":
        wave = params.get("wave", "")
        text = _text(wave, "vams") if isinstance(wave, ParameterValue) else wave
        text = text.strip().removeprefix("'").removeprefix("{").removesuffix("}")
        if text:
            points = [parameter_value(a) for a in _args(text)]
            stim.waveform = Waveform(kind=WaveformKind.PWL, points=points)
        return stim
    if shape == "sine" and any(k.startswith("fmmod") for k in params):
        kind = WaveformKind.SFFM
    elif shape == "sine":
        kind = WaveformKind.SIN
    else:
        kind = {"pulse": WaveformKind.PULSE, "exp": WaveformKind.EXP}[shape]
    names = {theirs: ours for ours, theirs in PRIMITIVE[kind][1].items()}
    args = {
        names.get(k, k): _value(v)
        for k, v in params.items()
        if names.get(k, k) in ARGS[kind][2]
    }
    if args:
        stim.waveform = Waveform(kind=kind, args=args)
    return stim
