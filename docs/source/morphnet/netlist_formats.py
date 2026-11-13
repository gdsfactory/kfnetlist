# ---
# jupyter:
#   jupytext:
#     formats: py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Parsing netlist formats
#
# `kfnetlist.morphnet` reads seven netlist formats into one schema document,
# the morphnet `Netlist` (circuits, subcircuit instances, connections,
# parameters, directives). `morphnet.to_netlists()` then turns every circuit
# into a `kfnetlist.Netlist` connectivity graph.
#
# | Format | Parser | Writer | Typical extension |
# |---|---|---|---|
# | SPICE (ngspice / generic) | `parse_spice` | `write_spice` | `.sp`, `.cir` |
# | HSPICE | `parse_hspice` | `write_hspice` | `.sp` |
# | Xyce | `parse_xyce` | `write_xyce` | `.cir` |
# | Spectre | `parse_spectre` | `write_spectre` | `.scs` |
# | Spectre with `simulator lang=spice` blocks | `parse_spectre_spice` | `write_spectre_spice` | `.scs` |
# | Verilog-AMS | `parse_vams` | `write_vams` | `.vams`, `.va` |
# | SystemVerilog (structural) | `parse_systemverilog` | `write_systemverilog` | `.sv` |
#
# This page defines one example netlist per format, parses it, and shows
# what ends up in the morphnet `Netlist` and in `kfnetlist.Netlist`. The
# [conversion page](format_conversion.py) writes them back out in other formats.
#
# **Waveguide or electrical?** Every parser applies the same rule to terminal
# names: `o1`, `o2`, ... are waveguide (optical) terminals, while `e1`, `e2`,
# ... and names without a prefix are electrical. A net that touches an `o<N>`
# terminal is a waveguide net.

# %%
from collections import defaultdict

from kfnetlist import NetlistPort, morphnet
from kfnetlist.morphnet.netlist import (
    parse_hspice,
    parse_spectre,
    parse_spectre_spice,
    parse_spice,
    parse_systemverilog,
    parse_vams,
    parse_xyce,
)
from kfnetlist.morphnet.netlist.value_utils import format_si_value


def value(param: morphnet.Parameter) -> str:
    pv = param.default_value
    if pv is not None and pv.prefixed_value is not None:
        return format_si_value(pv.prefixed_value)
    return param.properties.get("expr", "?")


def summary(netlist: morphnet.Netlist) -> None:
    """Print what a parser put into a morphnet Netlist."""
    print("top circuit:", netlist.top_circuit)
    for d in netlist.directives:
        print("directive:", d.kind.name, " ".join(filter(None, (d.name, d.value))))
    for ext in netlist.ext_circuits:
        ports = ", ".join(p.name for p in ext.ports)
        print(f"external circuit: {ext.name}({ports}) {ext.properties}")
    for c in netlist.circuits:
        print(f"\ncircuit {c.name}")
        if c.parameters:
            print(
                "  parameters:", ", ".join(f"{p.name}={value(p)}" for p in c.parameters)
            )
        print(
            "  ports:",
            ", ".join(
                f"{p.name} ({p.direction.name.lower()}, {p.domain.name.lower()})"
                for p in c.ports
            ),
        )
        for s in c.subcircuits:
            params = " ".join(f"{p.name}={value(p)}" for p in s.parameters)
            model = s.properties.get("model_name", "")
            print(f"  instance {s.name}: {s.circuit_name} {model} {params}".rstrip())
        nets: dict[str, list[str]] = defaultdict(list)
        domains = {}
        for conn in c.connections:
            for ref in (conn.source, conn.target):
                if ref is None:
                    continue
                pin = (
                    f"{ref.instance_name}.{ref.port_name}"
                    if ref.instance_name
                    else ref.port_name
                )
                if pin not in nets[conn.name]:
                    nets[conn.name].append(pin)
            domains[conn.name] = conn.domain.name.lower()
        for name, pins in nets.items():
            print(f"  net {name} [{domains[name]}]: {', '.join(pins)}")
        for key, text in c.properties.items():
            print(f"  {key}: {' '.join(text.split())}")


def show_kfnetlist(netlist: morphnet.Netlist, cell: str) -> None:
    """Print the kfnetlist.Netlist that morphnet.to_netlists() builds for `cell`."""
    nl = morphnet.to_netlists(netlist)[cell]
    nl.sort()
    print("ports:", [p.name for p in nl.ports])
    for name, inst in nl.instances.items():
        print(f"instance {name}: component={inst.component!r} settings={inst.settings}")
    for net in nl.nets:
        print(
            "net:",
            " -- ".join(
                m.name if isinstance(m, NetlistPort) else f"{m.instance}.{m.port}"
                for m in net
            ),
        )


# %% [markdown]
# ## SPICE
#
# A generic SPICE deck: device models, a CMOS inverter subcircuit, and a
# buffer built from two inverters. Primitive devices (`R`, `C`, `L`, `D`,
# `Q`, `M`, `V`, `I`) become instances of external circuits (`resistor`,
# `mosfet`, ...) with fixed pin names (`p`/`n`, `d`/`g`/`s`/`b`, ...). The
# model name is kept in the instance's `model_name` property.

# %%
SPICE = """\
* CMOS buffer
.model nch nmos level=49 vth0=0.4
.model pch pmos level=49 vth0=-0.4

.subckt inverter in out vdd vss
M1 out in vdd vdd pch W=2u L=180n
M2 out in vss vss nch W=1u L=180n
.ends inverter

.subckt buffer a y vdd vss
X1 a mid vdd vss inverter
X2 mid y vdd vss inverter
C1 y vss 10f
.ends buffer
.end
"""
spice = parse_spice(SPICE)
summary(spice)

# %% [markdown]
# `to_netlists()` returns one `kfnetlist.Netlist` per circuit. Instances keep
# their parameters as `settings`; SI values become plain floats:

# %%
show_kfnetlist(spice, "inverter")

# %%
show_kfnetlist(spice, "buffer")

# %% [markdown]
# ## HSPICE
#
# HSPICE is parsed with the SPICE grammar plus HSPICE preprocessing (for
# example, `$` comments). Here is an RC low-pass filter with an HSPICE inline
# comment:

# %%
HSPICE = """\
* RC low-pass
.subckt rc_lowpass in_ out gnd
R1 in_ out 1k     $ series resistor
C1 out gnd 100p   $ shunt capacitor
.ends rc_lowpass
.end
"""
hspice = parse_hspice(HSPICE)
summary(hspice)

# %%
show_kfnetlist(hspice, "rc_lowpass")

# %% [markdown]
# ## Xyce
#
# Xyce decks are case-insensitive and declare subcircuit parameters with
# `PARAMS:`. A resistive divider, where each resistor value is a subcircuit
# parameter:

# %%
XYCE = """\
* Xyce divider
.SUBCKT divider vin vout gnd PARAMS: rtop=10k rbot=10k
R1 vin vout 10k
R2 vout gnd 10k
.ENDS divider
.END
"""
xyce = parse_xyce(XYCE)
summary(xyce)

# %%
show_kfnetlist(xyce, "divider")

# %% [markdown]
# ## Spectre
#
# Spectre puts terminals in parentheses and names the master after them.
# A two-stage hierarchy:

# %%
SPECTRE = """\
subckt inverter (in_ out vdd vss)
MP (out in_ vdd vdd) pch w=2u l=180n
MN (out in_ vss vss) nch w=1u l=180n
ends inverter

subckt buffer (a y vdd vss)
I1 (a mid vdd vss) inverter
I2 (mid y vdd vss) inverter
ends buffer
"""
spectre = parse_spectre(SPECTRE)
summary(spectre)

# %%
show_kfnetlist(spectre, "buffer")

# %% [markdown]
# ## Spectre with SPICE blocks
#
# Spectre decks often switch language with `simulator lang=...`. The
# `spectre_spice` parser handles both halves in one file:

# %%
SPECTRE_SPICE = """\
simulator lang=spice
.subckt rdiv a b mid
R1 a mid 1k
R2 mid b 1k
.ends rdiv

simulator lang=spectre
subckt top (vin gnd)
X0 (vin gnd tap) rdiv
C0 (tap gnd) capacitor c=1p
ends top
"""
spectre_spice = parse_spectre_spice(SPECTRE_SPICE)
summary(spectre_spice)

# %%
show_kfnetlist(spectre_spice, "top")

# %% [markdown]
# ## Verilog-AMS
#
# Verilog-AMS modules declare port directions and disciplines (the discipline
# is kept as `Port.discipline`). `analog` blocks are not structure: they are
# kept as text in the circuit's `analog_block` property.

# %%
VAMS = """\
`include "disciplines.vams"
module res_model (p, n);
  inout p, n;
  electrical p, n;
  parameter real r = 1k;
  analog V(p, n) <+ r * I(p, n);
endmodule

module divider (vin, vout, gnd);
  input vin;
  output vout;
  inout gnd;
  electrical vin, vout, gnd;
  res_model #(.r(10k)) R1 (.p(vin), .n(vout));
  res_model #(.r(10k)) R2 (.p(vout), .n(gnd));
endmodule
"""
vams = parse_vams(VAMS)
summary(vams)

# %%
show_kfnetlist(vams, "divider")

# %% [markdown]
# ## SystemVerilog
#
# The SystemVerilog parser reads the structural part of the language
# (SystemVerilog 3.1a, Annex A):
#
# - ANSI headers `(input wire [3:0] a, output y)` and non-ANSI port lists with
#   body declarations;
# - `parameter`/`localparam`, also in the `#(...)` header; numbers, sized
#   literals (`4'b1010`) and expressions (kept as text in an `expr` property);
# - instances with named `.p(n)`, positional, implicit `.p`, wildcard `.*` and
#   empty `.p()` connections, several per statement;
# - `assign a = b;` and `alias a = b = c;`, which merge nets.
#
# Behavioral code (`always`, `initial`, `function`, `task`, `generate`,
# `class`, `assign` with logic on the right, ...) is kept as text in
# `behavioral_block_N` properties.

# %%
SYSTEMVERILOG = """\
`timescale 1ns/1ps
module nand2 (input a, b, output y, inout vdd, vss);
  pmos_t P1 (.d(y), .g(a), .s(vdd)), P2 (.d(y), .g(b), .s(vdd));
  nmos_t N1 (.d(y), .g(a), .s(mid)), N2 (.d(mid), .g(b), .s(vss));
endmodule

module latch (s_n, r_n, q, q_n, vdd, vss);
  input s_n, r_n;
  output q, q_n;
  inout vdd, vss;
  wire qi;
  nand2 U1 (.a(s_n), .b(q_n), .y(qi), .*);
  nand2 U2 (.a(r_n), .b(q), .y(q_n), .*);
  assign q = qi;
  initial $display("latch ready");
endmodule
"""
systemverilog = parse_systemverilog(SYSTEMVERILOG)
summary(systemverilog)

# %%
show_kfnetlist(systemverilog, "latch")

# %% [markdown]
# `assign q = qi;` merged `qi` into the port net `q`, and `.*` connected `vdd`
# and `vss` by name.
#
# ## Photonic circuits
#
# The same parsers read photonic netlists. Terminals named `o<N>` are
# waveguide terminals; heater and bias pins (`e1`, `vdd`, ...) stay
# electrical. A Mach-Zehnder interferometer with a thermal phase shifter, in
# SystemVerilog:

# %%
MZI_SV = """\
module mzi #(parameter real arm_length = 100e-6) (
  input o1, o2, output o3, o4,   // optical
  input e1, inout gnd            // heater drive
);
  dc #(.gap(200n)) Xdc1 (.o1(o1), .o2(o2), .o3(top_a), .o4(bot_a));
  dc #(.gap(200n)) Xdc2 (.o1(top_b), .o2(bot_b), .o3(o3), .o4(o4));
  heater_wg #(.length(arm_length)) Xtop (.o1(top_a), .o2(top_b), .e1(e1), .e2(gnd));
  wg #(.length(arm_length)) Xbot (.o1(bot_a), .o2(bot_b));
endmodule
"""
mzi_sv = parse_systemverilog(MZI_SV)
summary(mzi_sv)

# %% [markdown]
# The same MZI as a SPICE subcircuit. SPICE has no port names on subcircuit
# calls, so the instance pins of undeclared subcircuits are numbered and only
# the nets that reach an `o<N>` terminal of `mzi` itself are waveguide. Define the
# subcircuits in the deck (as here) and every net keeps its domain:

# %%
MZI_SPICE = """\
.subckt dc o1 o2 o3 o4 gap=200n
.ends dc
.subckt wg o1 o2 length=100u
.ends wg
.subckt heater_wg o1 o2 e1 e2 length=100u
.ends heater_wg
.subckt mzi o1 o2 o3 o4 e1 gnd
Xdc1 o1 o2 top_a bot_a dc
Xdc2 top_b bot_b o3 o4 dc
Xtop top_a top_b e1 gnd heater_wg
Xbot bot_a bot_b wg
.ends mzi
"""
mzi_spice = parse_spice(MZI_SPICE)
summary(mzi_spice)

# %% [markdown]
# Both describe the same graph:

# %%
show_kfnetlist(mzi_sv, "mzi")

# %% [markdown]
# Only the `o<N>` pattern counts: `out`, `osc` or `opt` stay electrical.

# %%
from kfnetlist.morphnet.netlist.net_utils import domain_of

for name in ("o1", "o12", "e1", "out", "osc", "vdd"):
    print(f"{name:>4}: {domain_of(name).name}")

# %% [markdown]
# ## Defining a netlist in Python
#
# Netlists can also be built directly with the morphnet builder API (see
# [Basic Usage](basic-usage.md)), and then written in any format:

# %%
from kfnetlist.morphnet.netlist import write_systemverilog

WG = morphnet.SignalDomain.WAVEGUIDE
ring = morphnet.circuit("ring_filter", parameters=[("radius", 10e-6)])
for name in ("o1", "o2", "o3", "o4"):
    ring.add_terminal(name, domain=WG)
ring.add(morphnet.subcircuit("Xring", "ring_coupler", gap=150e-9))
for name in ("o1", "o2", "o3", "o4"):
    ring.connect(name, ("", name), ("Xring", name), domain=WG)

doc = morphnet.Netlist(name="ring", top_circuit="ring_filter").add(ring)
summary(doc)
print()
print(write_systemverilog(doc))
