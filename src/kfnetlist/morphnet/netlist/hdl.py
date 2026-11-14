"""Shared Verilog-family helpers (SystemVerilog, Verilog-AMS).

- ``apply_defines``: `` `ifdef `` / `` `define `` handling before parsing.
- Bit-level nets: a bus ``in[3:0]`` is the nets ``in[3]`` … ``in[0]``. Port
  connection expressions resolve to ordered (msb-first) bit lists, so a
  bit-select ``in[0]`` meets bit 0 of port ``in``.
- ``format_bits``: the writers' inverse, bits back to ``bus[m:l]`` / ``{…}``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

# `ifdef NAME / `define NAME value / ...
COND_RE: re.Pattern[str] = re.compile(
    r"^[ \t]*`(ifdef|ifndef|elsif|else|endif|define|undef)\b[ \t]*(\w*)[ \t]*(.*?)\s*$"
)
MACRO_RE: re.Pattern[str] = re.compile(r"`(\w+)")
BIT_RE: re.Pattern[str] = re.compile(r"^(.*)\[(-?\d+)\]$")

Range = tuple[int, int]  # (msb, lsb) as declared
Buses = Mapping[str, Range]


def apply_defines(text: str, defines: Mapping[str, str] | None = None) -> str:
    """Keep only the active `` `ifdef `` branches and expand object-like macros.

    ``defines`` are the predefined macros (``{"IS_SIM": "1"}``); with none, an
    `` `ifdef X ... `else ... `endif`` takes the `` `else `` branch, like a
    compiler. `` `define `` lines in active code register a macro and are kept
    (they are recorded as directives).
    """
    macros = dict(defines or {})
    out: list[str] = []
    stack: list[list[bool]] = []  # [parent active, branch already taken]
    active = True
    for line in text.splitlines(keepends=True):
        m = COND_RE.match(line)
        kw = m.group(1) if m else None
        if kw in ("elsif", "else", "endif") and not stack:
            raise ValueError(f"`{kw} without `ifdef")
        if m and kw in ("ifdef", "ifndef"):
            hit = (m.group(2) in macros) == (kw == "ifdef")
            stack.append([active, hit])
            active = active and hit
        elif m and kw == "elsif":
            parent, taken = stack[-1]
            hit = not taken and m.group(2) in macros
            stack[-1][1] = taken or hit
            active = parent and hit
        elif kw == "else":
            parent, taken = stack[-1]
            stack[-1][1] = True
            active = parent and not taken
        elif kw == "endif":
            active = stack.pop()[0]
        elif not active:
            continue
        elif m and kw == "define":
            macros[m.group(2)] = m.group(3)
            out.append(line)
        elif m and kw == "undef":
            macros.pop(m.group(2), None)
            out.append(line)
        else:
            out.append(MACRO_RE.sub(lambda t: macros.get(t.group(1), t.group(0)), line))
    if stack:
        raise ValueError("`ifdef without `endif")
    return "".join(out)


# ── Expressions ──────────────────────────────────────────────────────────


class NetRef(str):
    """Expression text naming a net: ``a``, ``a[3]``, ``a[3:0]``.

    ``sel`` is the select: ``()`` whole net, ``(i,)`` bit, ``(msb, lsb)`` slice.
    """

    name: str
    sel: tuple[str, ...]

    @classmethod
    def make(cls, name: str, sel: Sequence[str] = ()) -> NetRef:
        ref = cls(name + (f"[{':'.join(sel)}]" if sel else ""))
        ref.name, ref.sel = name, tuple(sel)
        return ref


class Literal(str):
    """Numeric literal text (``0``, ``1'b0``) — a constant tie when used as a net."""


class Concat(str):
    """``{a, b[1:0]}`` — parts in source (msb-first) order."""

    parts: list[str]

    @classmethod
    def make(cls, parts: Sequence[str]) -> Concat:
        concat = cls("{" + ", ".join(parts) + "}")
        concat.parts = list(parts)
        return concat


class Dim(tuple[str, ...]):
    """``[3:0]`` -> ``("3", "0")``; ``[3]`` -> ``("3",)``."""

    def __str__(self) -> str:
        return f"[{':'.join(self)}]"


def to_int(text: object) -> int | None:
    try:
        return int(str(text).replace("_", ""))
    except ValueError:
        return None


def to_range(sel: Sequence[str]) -> Range | None:
    """``(msb, lsb)`` of a declared ``[msb:lsb]``; ``None`` if not constant."""
    if len(sel) != 2:
        return None
    msb, lsb = to_int(sel[0]), to_int(sel[1])
    return None if msb is None or lsb is None else (msb, lsb)


def decl_range(name: str, dims: Sequence[Sequence[str]]) -> Range | None:
    """``(msb, lsb)`` of a one-dimensional declaration; ``None`` when scalar.

    A non-constant range (``[N-1:0]``) is treated as scalar.
    """
    if len(dims) > 1:
        raise ValueError(f"{name}: multi-dimensional buses are not supported")
    return to_range(dims[0]) if dims else None


def range_width(rng: Range) -> int:
    return abs(rng[0] - rng[1]) + 1


def bits(name: str, msb: int, lsb: int) -> list[str]:
    """``name[msb]`` … ``name[lsb]``."""
    step = -1 if msb >= lsb else 1
    return [f"{name}[{i}]" for i in range(msb, lsb + step, step)]


def resolve(expr: object, buses: Buses, width: int = 1) -> list[str]:
    """Bit nets (msb first) of a connection expression.

    A literal is a constant tie repeated over ``width`` bits. Raises
    ``ValueError`` for selects of undeclared buses or out-of-range bits.
    """
    if isinstance(expr, Concat):
        return [b for part in expr.parts for b in resolve(part, buses)]
    if isinstance(expr, Literal):
        return [str(expr)] * width
    if not isinstance(expr, NetRef):
        raise ValueError(f"unsupported net expression {expr!r}")
    bus = buses.get(expr.name)
    if not expr.sel:
        return bits(expr.name, *bus) if bus else [expr.name]
    if bus is None:
        # ponytail: integer ranges only; evaluate `[N-1:0]` against parameters if needed
        raise ValueError(
            f"{expr}: select of {expr.name!r}, which is not a bus with a constant range"
        )
    idx = [i for s in expr.sel if (i := to_int(s)) is not None]
    lo, hi = sorted(bus)
    if len(idx) != len(expr.sel) or not all(lo <= i <= hi for i in idx):
        raise ValueError(f"{expr}: select outside {expr.name}[{bus[0]}:{bus[1]}]")
    return bits(expr.name, idx[0], idx[-1])


def split_array(nets: list[str], count: int, width: int | None) -> list[list[str]]:
    """Per-instance bits of one port connection of an instance array (IEEE 1800 23.3.3.5).

    ``count * width`` bits are sliced msb-first over the instances (leftmost
    instance first); exactly ``width`` bits go to every instance. ``width`` is
    ``None`` for a module without a definition.
    """
    n = len(nets)
    if width is None:  # undefined module: slice evenly, or broadcast a single bit
        width = n // count if n % count == 0 else 1
    if n == count * width:
        return [nets[i * width : (i + 1) * width] for i in range(count)]
    if n == width:
        return [nets] * count
    raise ValueError(f"{n} bits for {count} instance(s) of a {width}-bit port")


def connect(
    instances: list[str],
    port: str,
    expr: object,
    buses: Buses,
    port_ranges: Mapping[str, Range | None] | None,
) -> list[tuple[str, str, str]]:
    """``(instance, port bit, net)`` triples for one port connection.

    ``port_ranges`` are the target module's port ranges (``None`` = scalar), or
    ``None`` when the module is not defined: its port then takes the width of
    the expression, with bits ``port[n-1]`` … ``port[0]``.
    """
    known = port_ranges is not None and port in port_ranges
    rng = port_ranges.get(port) if port_ranges is not None else None
    width = (range_width(rng) if rng else 1) if known else None
    try:
        chunks = split_array(resolve(expr, buses, width or 1), len(instances), width)
    except ValueError as e:
        raise ValueError(f"{instances[0]}.{port}({expr}): {e}") from None
    triples = []
    for inst, chunk in zip(instances, chunks):
        if rng:
            pins = bits(port, *rng)
        elif len(chunk) == 1:
            pins = [port]
        else:
            pins = bits(port, len(chunk) - 1, 0)
        triples += [(inst, pin, net) for pin, net in zip(pins, chunk)]
    return triples


def instance_names(name: str, rng: Range | None) -> list[str]:
    """``I[3]`` … ``I[0]`` for an instance array ``I[3:0]``, else ``[name]``."""
    return bits(name, *rng) if rng else [name]


# ── Writers ──────────────────────────────────────────────────────────────


def declared_range(width: int, rng_text: str | None) -> Range | None:
    """Range of a schema ``Port`` (``width`` + ``range`` property); ``None`` if scalar."""
    rng = to_range(rng_text.split(":")) if rng_text else None
    return rng if rng is not None or width <= 1 else (width - 1, 0)


def port_pins(name: str, width: int, rng_text: str | None) -> list[str]:
    """Bit pins of a (possibly bus) port, as registered by the parsers."""
    rng = declared_range(width, rng_text)
    return bits(name, *rng) if rng else [name]


def format_bits(nets: list[str], buses: Buses, escape: Callable[[str], str]) -> str:
    """Connection expression for bit nets: ``a``, ``a[2]``, ``a[3:1]`` or ``{…}``."""
    parts: list[tuple[str, list[int]] | str] = []
    for net in nets:
        m = BIT_RE.match(net)
        if m and m.group(1) in buses:
            base, i = m.group(1), int(m.group(2))
            last = parts[-1] if parts else None
            if isinstance(last, tuple) and last[0] == base:
                run = last[1]
                step = run[-1] - run[-2] if len(run) > 1 else i - run[-1]
                if abs(step) == 1 and i == run[-1] + step:
                    run.append(i)
                    continue
            parts.append((base, [i]))
        else:
            parts.append(escape(net))
    text = []
    for part in parts:
        if isinstance(part, str):
            text.append(part)
            continue
        base, run = part
        if (run[0], run[-1]) == buses[base] and len(run) == range_width(buses[base]):
            text.append(escape(base))
        elif len(run) == 1:
            text.append(f"{escape(base)}[{run[0]}]")
        else:
            text.append(f"{escape(base)}[{run[0]}:{run[-1]}]")
    return text[0] if len(text) == 1 else "{" + ", ".join(text) + "}"


def connection_expr(
    where: str, nets: list[str | None], buses: Buses, escape: Callable[[str], str]
) -> str:
    """``format_bits`` for one instance port; empty when it is unconnected."""
    connected = [n for n in nets if n is not None]
    if not connected:
        return ""
    if len(connected) != len(nets):
        # ponytail: no dummy wires for partly connected buses; add if needed
        raise ValueError(f"{where}: bus port is partly connected")
    return format_bits(connected, buses, escape)


def net_buses(names: list[str]) -> dict[str, Range]:
    """``{base: (max, min)}`` of every ``base[i]`` net name."""
    found: dict[str, list[int]] = {}
    for name in names:
        m = BIT_RE.match(name)
        if m:
            found.setdefault(m.group(1), []).append(int(m.group(2)))
    return {b: (max(ix), min(ix)) for b, ix in found.items()}


def bus_pins(ports: list[str]) -> list[tuple[str, list[str]]]:
    """Group pins ``in0[0], in0[1], en`` into ``[("in0", [in0[1], in0[0]]), ("en", [en])]``."""
    groups: dict[str, list[str]] = {}
    for pin in ports:
        m = BIT_RE.match(pin)
        groups.setdefault(m.group(1) if m else pin, []).append(pin)

    def index(pin: str) -> int:
        m = BIT_RE.match(pin)
        return int(m.group(2)) if m else 0

    return [
        (base, sorted(pins, key=index, reverse=True)) for base, pins in groups.items()
    ]
