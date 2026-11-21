"""Simulation view of ``.gsch`` devices, with nyancad's netlister semantics.

Mirrors ``nyancad/netlist.py`` in gdsfactoryplus (``_add_nyancad_element``,
``_select_model_entry``, ``_select_corner``, ``_eval_params``, ``_add_source`` and
the library includes of ``NyanCircuit``), resolved into the IR fields the SPICE and
Spectre writers read: circuit name, pin order, ``model_name``, expression params and
LIB/INCLUDE directives.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from kfnetlist.morphnet.morphnet_schema import (
    Directive,
    DirectiveKind,
    Macro,
    ParameterValue,
    Stimulus,
    Waveform,
    WaveformKind,
)
from kfnetlist.morphnet.netlist.expression import parameter_value, value_text
from kfnetlist.morphnet.netlist.value_utils import (
    DEVICE_PORT_TEMPLATES,
    DEVICE_PREFIX_TO_CIRCUIT,
    is_si_number,
    parse_si_number,
    to_float,
)

SIM_LANGUAGES = {"ngspice": "spice", "xyce": "spice", "vacask": "spectre"}
GROUND = "GND"  # the net nyancad writes as node 0 (case-sensitive, like nyancad)
IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*", re.ASCII)
VALID_IDENT_RE = re.compile(r"[A-Za-z_]\w*", re.ASCII)

# Mosaic built-in symbol -> device letter; their primary value prop
BUILTIN = {
    "resistor": "R",
    "capacitor": "C",
    "inductor": "L",
    "diode": "D",
    "vsource": "V",
    "isource": "I",
    "nmos": "M",
    "pmos": "M",
    "npn": "Q",
    "pnp": "Q",
}
VALUE_PROP = {"R": "resistance", "C": "capacitance", "L": "inductance"}
VACASK_MASTER = {"R": "sp_resistor", "C": "sp_capacitor", "L": "sp_inductor"}

# tran variant -> [(prop, stimulus arg, InSpice default)] in SPICE positional order;
# nyancad's _TRAN_PARAM_MAP names the props. Default None: required (InSpice fails
# without it); OMIT: may be left off at the end.
OMIT = ""
TRAN = {
    "sin": [
        ("offset", "sinedc", "0"), ("amplitude", "ampl", "1"),
        ("frequency", "freq", "50"), ("delay", "delay", "0"),
        ("damping", "theta", "0")],
    "pulse": [
        ("initial", "val0", None), ("pulsed", "val1", None),
        ("delay", "delay", "0"), ("rise", "rise", "0"), ("fall", "fall", "0"),
        ("width", "width", None), ("period", "period", None)],
    "exp": [
        ("initial", "val0", None), ("pulsed", "val1", None),
        ("rise-delay", "delay", "0"), ("rise-tau", "tau1", OMIT),
        ("fall-delay", "td2", OMIT), ("fall-tau", "tau2", OMIT)],
    "sffm": [
        ("offset", "sinedc", None), ("amplitude", "ampl", None),
        ("carrier-freq", "freq", None), ("mod-index", "modindex", None),
        ("signal-freq", "modfreq", None)],
}  # fmt: skip
WAVEFORM_KIND = {
    "sin": WaveformKind.SIN,
    "pulse": WaveformKind.PULSE,
    "exp": WaveformKind.EXP,
    "sffm": WaveformKind.SFFM,
}


def check_sim(sim: str) -> str:
    if sim.lower() not in SIM_LANGUAGES:
        raise ValueError(f"sim must be one of {sorted(SIM_LANGUAGES)}, got {sim!r}")
    return sim.lower()


def foreign_language(entry: Mapping[str, Any], sim: str) -> str | None:
    """Dialect of a SPICE library VACASK loads as foreign (``lang=``), else None."""
    if (
        sim == "vacask"
        and entry.get("library")
        and entry.get("language", "").lower() == "spice"
        and entry.get("implementation", "").lower() in ("ngspice", "xyce")
    ):
        return entry["implementation"].lower()
    return None


def select_entry(model_def: Mapping[str, Any], sim: str) -> dict[str, Any] | None:
    """Exact ``implementation``, else the sim's native language, else foreign."""
    entries = model_def.get("models") or []
    for match in (
        lambda e: e.get("implementation", "").lower() == sim,
        lambda e: e.get("language", "").lower() == SIM_LANGUAGES[sim],
        lambda e: foreign_language(e, sim),
    ):
        for entry in entries:
            if match(entry):
                return entry
    return None


def select_corner(sections: Sequence[str] | None, corners: Sequence[str]) -> str | None:
    """First of ``corners`` (caller order) the library has, else its first section."""
    if not sections:
        return None
    return next((c for c in corners if c in sections), sections[0])


def library(
    entry: Mapping[str, Any], sim: str, corners: Sequence[str]
) -> Directive | None:
    """The ``.lib``/``.include`` of a model entry; paths are passed through."""
    path = entry.get("library")
    if not path:
        return None
    lang = foreign_language(entry, sim)
    name = f"lang={lang}" if lang else ""
    section = select_corner(entry.get("sections"), corners)
    if section:
        return Directive(kind=DirectiveKind.LIB, value=f"{path} {section}", name=name)
    return Directive(kind=DirectiveKind.INCLUDE, value=path, name=name)


def macro(entry: Mapping[str, Any]) -> Macro | None:
    """The inline ``code`` of a model entry, which nyancad injects as SPICE."""
    code = (entry.get("code") or "").strip()
    if not code:
        return None
    return Macro(
        name=entry.get("name", ""), language=entry.get("language") or "spice", body=code
    )


def eval_params(
    entry_params: Mapping[str, str], props: Mapping[str, Any]
) -> dict[str, Any]:
    """nyancad ``_eval_params``: rename, or substitute props into an expression."""
    out: dict[str, Any] = {}
    for name, expr in entry_params.items():
        if VALID_IDENT_RE.fullmatch(expr.strip()):
            if expr.strip() in props:
                out[name] = props[expr.strip()]
            continue
        text = IDENTIFIER_RE.sub(
            lambda m: str(props[m[0]]) if m[0] in props else m[0], expr
        )
        out[name] = text  # bare: writers wrap expressions per dialect
    return out


def number(raw: Any) -> float | None:
    """The value of a SPICE number (``1k``, ``2.5``), None for anything else."""
    # ponytail: value_utils SI syntax, not nyancad's `meg*`-prefix leniency
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, str) and is_si_number(raw.strip()):
        return to_float(parse_si_number(raw.strip()))
    return None


def text(raw: Any) -> str:
    return raw.strip() if isinstance(raw, str) else str(raw)


def given(raw: Any) -> str | None:
    """A prop as written (numbers and expressions alike), None when unset."""
    return None if raw is None or raw == "" else text(raw)


def waveform(
    device: str, variant: str, tran: Mapping[str, Any]
) -> list[tuple[str, str]]:
    """``(VACASK name, value)`` of a ``tran`` waveform in SPICE positional order.

    Each value keeps its own slot: a missing required field is an error, as it is
    for nyancad/InSpice, and an optional one may only be left off at the end.
    """
    out: list[tuple[str, str]] = []
    gap = None
    for prop, spectre, default in TRAN[variant]:
        value = given(tran.get(prop))
        if value is None and default is None:
            raise ValueError(f"{device}: tran {variant} needs {prop!r}")
        if value is not None and gap:
            raise ValueError(f"{device}: tran {variant} has {prop!r} without {gap!r}")
        if value is None and default == OMIT:
            gap = gap or prop
            continue
        out.append((spectre, value if value is not None else str(default)))
    return out


def source(device: str, props: Mapping[str, Any]) -> Stimulus:
    """What drives a V/I source: its ``dc``/``ac`` props and ``tran`` waveform. Like
    nyancad, a sine or pulse source always has a DC value (0) and a sine an AC one (1)."""
    dc, ac, tran = given(props.get("dc")), given(props.get("ac")), props.get("tran")
    variant = tran.get("type") if isinstance(tran, dict) else None
    if not isinstance(tran, dict) or variant not in TRAN:
        return Stimulus(dc=_value(dc), ac_magnitude=_value(ac))
    args = {name: parameter_value(raw) for name, raw in waveform(device, variant, tran)}
    return Stimulus(
        dc=_value(dc or "0") if variant in ("sin", "pulse") else None,
        ac_magnitude=_value(ac or "1") if variant == "sin" else _value(ac),
        waveform=Waveform(kind=WAVEFORM_KIND[variant], args=args),
    )


def source_props(device: str, stim: Stimulus, props: Mapping[str, Any]) -> dict:
    """``props`` with ``stim`` written back to ``dc``/``ac``/``tran``; unchanged while
    ``stim`` is still what they describe. A value the props left to its default
    (a sine's DC 0, a pulse's rise 0, ...) stays left out while it is the default."""
    if stim.model_copy(update={"name": ""}) == source(device, props):
        return dict(props)
    out = {k: v for k, v in props.items() if k not in ("dc", "ac", "tran")}
    tran_prop = props.get("tran")
    old: Mapping[str, Any] = tran_prop if isinstance(tran_prop, dict) else {}
    implied = {"dc": "0", "ac": "1"}
    for prop, value in (("dc", stim.dc), ("ac", stim.ac_magnitude)):
        if value is None or (prop not in props and value == _value(implied[prop])):
            continue
        out[prop] = value_text(value, "gsch")
    w = stim.waveform
    if w is not None:
        variant = next((v for v, k in WAVEFORM_KIND.items() if k == w.kind), None)
        if variant is None:
            raise ValueError(f"{device}: a .gsch source has no {w.kind.name} waveform")
        tran: dict[str, Any] = {"type": variant}
        for prop, arg, default in TRAN[variant]:
            value = w.args.get(arg)
            if value is None or (
                prop not in old and default and value == _value(default)
            ):
                continue
            tran[prop] = value_text(value, "gsch")
        out["tran"] = tran
    return out


def _value(raw: str | None) -> ParameterValue | None:
    return None if raw is None else parameter_value(raw)


@dataclass
class Element:
    """How one ``.gsch`` device is simulated."""

    circuit: str  # IR circuit name
    ports: list[str]  # pin order of that circuit
    params: dict[str, Any]
    model_name: str = ""
    prefix: str = ""  # SPICE letter of the circuit
    rename: dict[str, str] = field(default_factory=dict)  # device pin.lower() -> pin
    ground: list[str] = field(default_factory=list)  # pins tied to ground if open
    # a model with `params`: the props its expressions read, and those expressions
    sources: dict[str, Any] = field(default_factory=dict)
    exprs: dict[str, str] = field(default_factory=dict)
    # model prop defaults the entry's props do not set
    defaults: dict[str, Any] = field(default_factory=dict)
    stimulus: Stimulus | None = None  # a V/I source's

    def pin(self, name: str) -> str:
        return self.rename.get(name.lower(), name)


def primitive(
    letter: str, given: Sequence[str], params: dict[str, Any], model: str = ""
) -> Element:
    """A device primitive; ``given`` device pins map onto its template in order."""
    template = DEVICE_PORT_TEMPLATES[letter]
    ports = [*template, *given[len(template) :]]
    return Element(
        DEVICE_PREFIX_TO_CIRCUIT[letter],
        ports,
        params,
        model,
        letter,
        {p.lower(): q for p, q in zip(given, ports)},
    )


def element(
    entry: Mapping[str, Any], models: Mapping[str, Any], sim: str, key: str = ""
) -> Element | None:
    """The device nyancad netlists for ``entry``, or None when it netlists none."""
    device = _element(entry, models, sim, entry.get("name") or key)  # nyancad's name
    model_def = models.get(f"models:{entry.get('model')}")
    if device is None or not isinstance(model_def, dict):
        return device and vacask(device, sim)
    props, defaults = entry.get("props") or {}, model_defaults(model_def)
    device.defaults = {k: v for k, v in defaults.items() if k not in props}
    chosen = select_entry(model_def, sim)
    if chosen and chosen.get("params"):
        device.sources = {**defaults, **props}
        device.exprs = dict(chosen["params"])
    return vacask(device, sim)


def model_defaults(model_def: Mapping[str, Any]) -> dict[str, Any]:
    return {
        p["name"]: p["default"]
        for p in model_def.get("props") or []
        if p.get("name") and p.get("default") is not None
    }


def _element(
    entry: Mapping[str, Any], models: Mapping[str, Any], sim: str, label: str
) -> Element | None:
    if not entry.get("nets"):  # nyancad reads Mosaic `nets` only
        return None
    kind = entry.get("type")
    model_def = models.get(f"models:{entry.get('model')}")
    props = dict(entry.get("props") or {})
    chosen, name = None, None
    if isinstance(model_def, dict):
        defaults = model_defaults(model_def)
        name = model_def.get("name") or entry["model"]
        chosen = select_entry(model_def, sim)
        if chosen:
            name = chosen.get("name") or name
            props["model"] = name
            if chosen.get("params"):
                given = {**defaults, **(entry.get("props") or {})}
                props = eval_params(chosen["params"], given)
        else:
            props = {**defaults, **props}
            props.setdefault("model", name)
    props = {k: v for k, v in props.items() if v != "" and v is not None}
    model_ports = sorted(p["name"] for p in (model_def or {}).get("ports") or [])

    letter = chosen.get("spice-type", "").upper() if chosen else ""
    if chosen and letter:
        given = chosen.get("port-order") or model_ports
        model = str(props.pop("model", name))
        if letter in ("D", "M", "Q"):
            if foreign_language(chosen, sim):
                model = "m_" + model.lower()
            return primitive(letter, given, props, model)
        if letter in DEVICE_PORT_TEMPLATES:
            return primitive(letter, given, props)
        # ponytail: unknown letters are called like X/SUBCKT (nyancad: X)
        return subckt(model, given, props)

    letter = BUILTIN.get(kind or "", "")
    if letter in VALUE_PROP:
        value = props.get(VALUE_PROP[letter])
        params = {} if value is None else {"value": value}
        return primitive(letter, ["P", "N"], params)
    if letter in ("V", "I"):
        device = primitive(letter, ["P", "N"], {})
        device.stimulus = source(label, props)
        return device
    if letter:
        model = str(props.pop("model", ""))
        pins = {"D": ["P", "N"], "M": ["D", "G", "S", "B"], "Q": ["C", "B", "E"]}
        device = primitive(letter, pins[letter], props, model)
        if letter == "M" and "b" not in {p.lower() for p in entry["nets"]}:
            device.ground = ["b"]
        return device
    if model_def is not None:
        return subckt(str(props.pop("model", name)), model_ports, props)
    return None


def subckt(name: str, ports: Sequence[str], params: dict[str, Any]) -> Element:
    rename = {p.lower(): p for p in ports}
    return Element(name, list(ports), params, prefix="X", rename=rename)


def vacask(device: Element, sim: str) -> Element:
    """InSpice's VACASK forms: R/C/L are its ``sp_*`` OSDI models, and D/M/Q take
    their multiplier ``m`` as ``$mfactor``, left out when 1."""
    if sim != "vacask":
        return device
    if device.prefix in VACASK_MASTER and not device.model_name:
        device.model_name = VACASK_MASTER[device.prefix]
    # ponytail: `$mfactor` is computed from `m` here, so a later edit of a model's
    # source `m` does not reach it; make it an expression if that edit matters.
    if device.prefix in ("D", "M", "Q") and "m" in device.params:
        m = device.params.pop("m")
        if number(m) != 1:
            device.params["$mfactor"] = m
    return device
