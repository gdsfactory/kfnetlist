from __future__ import annotations

import re
import warnings
from collections.abc import Callable, Mapping, Sequence

from kfnetlist.morphnet.morphnet_schema import (
    Expression,
    Macro,
    Parameter,
    ParameterValue,
    PrefixedValue,
    SIPrefix,
    SubCircuit,
)

# ---------------------------------------------------------------------------
# SI suffix ↔ SIPrefix enum — O(1) lookups in both directions
# ---------------------------------------------------------------------------

SI_SUFFIX_TO_PREFIX: dict[str, SIPrefix] = {
    "a": SIPrefix.ATTO,
    "f": SIPrefix.FEMTO,
    "p": SIPrefix.PICO,
    "n": SIPrefix.NANO,
    "u": SIPrefix.MICRO,
    "m": SIPrefix.MILLI,
    "k": SIPrefix.KILO,
    "x": SIPrefix.MEGA,
    "meg": SIPrefix.MEGA,
    "g": SIPrefix.GIGA,
    "t": SIPrefix.TERA,
}

MIL_SCALE: float = 25.4e-6

PREFIX_TO_SI_SUFFIX: dict[SIPrefix, str] = {
    v: k for k, v in SI_SUFFIX_TO_PREFIX.items()
}

# ---------------------------------------------------------------------------
# Device port templates — O(1) lookup per instance line
# ---------------------------------------------------------------------------

DEVICE_PORT_TEMPLATES: dict[str, list[str]] = {
    "R": ["p", "n"],
    "C": ["p", "n"],
    "L": ["p", "n"],
    "D": ["p", "n"],
    "Q": ["c", "b", "e"],
    "M": ["d", "g", "s", "b"],
    "V": ["p", "n"],
    "I": ["p", "n"],
}

DEVICE_PREFIX_TO_CIRCUIT: dict[str, str] = {
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
    "D": "diode",
    "Q": "bjt",
    "M": "mosfet",
    "V": "vsource",
    "I": "isource",
}


SPICE_LANGUAGES = ("spice", "ngspice", "xyce", "hspice")


def macro_lines(
    macros: Sequence[Macro],
    accept: Mapping[str, tuple[str, str] | None],
    comment: str,
) -> list[str]:
    """Bodies whose ``language`` is in ``accept``, verbatim (between the pair of
    lines it maps to, if any); any other is a ``skipped macro`` comment and a
    warning, never a silent drop."""
    lines: list[str] = []
    for m in macros:
        if m.language.lower() not in accept:
            note = f"skipped macro {m.name} ({m.language})"
            warnings.warn(note, stacklevel=2)
            lines.append(f"{comment} {note}")
            continue
        wrap = accept[m.language.lower()]
        body = m.body.splitlines()
        lines.extend([wrap[0], *body, wrap[1]] if wrap else body)
    return lines


def is_skipped(ref: SubCircuit) -> bool:
    """Instances flagged ``sim_skip`` are kept in the IR but not simulated."""
    return ref.properties.get("sim_skip") == "1"


def param_text(
    param: Parameter,
    fmt: Callable[[ParameterValue], str],
    dialect: str,
    named: bool = True,
    resolve: Callable[[str], Expression | None] | None = None,
) -> str | None:
    """Written value of a parameter: its expression printed for ``dialect`` (raw text
    wrapped only when ``named``; references through ``resolve``), else its default
    formatted by ``fmt``. None when there is nothing to write (no value, or an empty
    expression)."""
    from kfnetlist.morphnet.netlist.expression import format_expression  # a cycle

    value = param.default_value
    if value is None:
        return None
    if value.expression is not None:  # empty raw text or no node: nothing to write
        text = format_expression(value.expression, dialect, resolve, named=named)
        return text or None
    return fmt(value)


def sim_params(
    ref: SubCircuit,
) -> tuple[list[Parameter], Callable[[str], Expression | None]]:
    """The params of ``ref`` a simulator sees, and the ``resolve`` that prints a
    reference to one of its source props as that prop's value.

    Source props (``properties["role"] == "source"``, e.g. a ``.gsch`` ``width``) are
    what model expressions (``w = width * 1e-6``) read; they are not device params.
    """
    sources = {
        p.name: p.default_value
        for p in ref.parameters
        if p.properties.get("role") == "source" and p.default_value is not None
    }

    def resolve(name: str) -> Expression | None:
        value = sources.get(name)
        if value is None or value.expression is not None:
            return value.expression if value else None
        if value.prefixed_value is not None:
            return Expression(literal=value.prefixed_value)
        return None

    params = [p for p in ref.parameters if p.properties.get("role") != "source"]
    return params, resolve


# Deprecated name, kept for code written before the ExternalCircuit rename.
DEVICE_PREFIX_TO_MODULE = DEVICE_PREFIX_TO_CIRCUIT

# Regex: optional sign, digits with optional decimal, optional SI suffix
SI_NUMBER_RE: re.Pattern[str] = re.compile(
    r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(meg|mil|[afpnumkgtxAFPNUMKGTX])?$",
    re.IGNORECASE,
)


def parse_si_number(token: str) -> PrefixedValue:
    """Parse a SPICE-style SI-prefixed number like '10k', '2.2u', '100meg'.

    Returns a PrefixedValue with the numeric part and the SIPrefix enum.
    Raises ValueError if the token is not a valid SI number.
    """
    m = SI_NUMBER_RE.match(token)
    if m is None:
        raise ValueError(f"Not a valid SI number: {token!r}")
    numeric_str, suffix = m.group(1), m.group(2)
    value = float(numeric_str)
    if suffix is None:
        prefix = SIPrefix.UNSPECIFIED
    else:
        suffix_lower = suffix.lower()
        if suffix_lower == "mil":
            return PrefixedValue(
                double_value=value * MIL_SCALE, prefix=SIPrefix.UNSPECIFIED
            )
        prefix = SI_SUFFIX_TO_PREFIX.get(suffix_lower)
        if prefix is None:
            raise ValueError(f"Unknown SI suffix: {suffix!r}")
    return PrefixedValue(double_value=value, prefix=prefix)


# Verilog-A scale factors (LRM 2.6.2): case matters, `M` is mega and `m` milli.
VERILOG_SCALE: dict[str, SIPrefix] = {
    "T": SIPrefix.TERA, "G": SIPrefix.GIGA, "M": SIPrefix.MEGA, "K": SIPrefix.KILO,
    "k": SIPrefix.KILO, "m": SIPrefix.MILLI, "u": SIPrefix.MICRO, "n": SIPrefix.NANO,
    "p": SIPrefix.PICO, "f": SIPrefix.FEMTO, "a": SIPrefix.ATTO,
}  # fmt: skip
VERILOG_NUMBER_RE = re.compile(
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([TGMKkmunpfa])?"
)


def parse_verilog_number(token: str) -> ParameterValue | None:
    """A Verilog-A number (``1M`` = 1e6, ``1m`` = 1e-3); None for anything else."""
    m = VERILOG_NUMBER_RE.fullmatch(token)
    if m is None:
        return None
    prefix = VERILOG_SCALE[m[2]] if m[2] else SIPrefix.UNSPECIFIED
    return ParameterValue(
        prefixed_value=PrefixedValue(double_value=float(m[1]), prefix=prefix)
    )


def format_verilog_value(pv: PrefixedValue) -> str:
    """``pv`` with a Verilog-A scale factor: mega is ``M``, not SPICE's ``meg``."""
    text = format_si_value(pv)
    return f"{text[:-3]}M" if text.endswith("meg") else text


def parse_parameter_number(token: str) -> ParameterValue:
    """Parse a numeric token into a ParameterValue with a PrefixedValue."""
    return ParameterValue(prefixed_value=parse_si_number(token))


SI_PREFIX_EXPONENT: dict[SIPrefix, int] = {
    SIPrefix.UNSPECIFIED: 0,
    SIPrefix.QUECTO: -30,
    SIPrefix.RONTO: -27,
    SIPrefix.YOCTO: -24,
    SIPrefix.ZEPTO: -21,
    SIPrefix.ATTO: -18,
    SIPrefix.FEMTO: -15,
    SIPrefix.PICO: -12,
    SIPrefix.NANO: -9,
    SIPrefix.MICRO: -6,
    SIPrefix.MILLI: -3,
    SIPrefix.CENTI: -2,
    SIPrefix.DECI: -1,
    SIPrefix.DECA: 1,
    SIPrefix.HECTO: 2,
    SIPrefix.KILO: 3,
    SIPrefix.MEGA: 6,
    SIPrefix.GIGA: 9,
    SIPrefix.TERA: 12,
    SIPrefix.PETA: 15,
    SIPrefix.EXA: 18,
    SIPrefix.ZETTA: 21,
    SIPrefix.YOTTA: 24,
    SIPrefix.RONNA: 27,
    SIPrefix.QUETTA: 30,
}


def to_float(pv: PrefixedValue) -> float:
    """Plain float value of a PrefixedValue (``2.2`` MICRO → ``2.2e-06``)."""
    return pv.double_value * 10.0 ** SI_PREFIX_EXPONENT[pv.prefix]


def format_si_value(pv: PrefixedValue) -> str:
    """Format a PrefixedValue as a SPICE-style string like '10k', '2.2u'.

    Produces the shortest clean representation (no trailing zeros).
    """
    num = pv.double_value
    if num == int(num):
        num_str = str(int(num))
    else:
        num_str = f"{num:g}"

    if pv.prefix == SIPrefix.UNSPECIFIED:
        return num_str

    suffix = PREFIX_TO_SI_SUFFIX.get(pv.prefix, "")
    return f"{num_str}{suffix}"


def is_si_number(token: str) -> bool:
    """Check whether a token looks like an SI-prefixed number."""
    return SI_NUMBER_RE.match(token) is not None
