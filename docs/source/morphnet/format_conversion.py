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
# # Converting between formats
#
# Every format has a parser into the morphnet `Netlist` and a writer out of it,
# so converting a netlist is one line: **parse** with one format, **write**
# with another. This page:
#
# 1. walks through conversions between pairs of formats, with full output;
# 2. converts one circuit through all 7 × 7 format pairs and checks that
#    connectivity and parameters survive;
# 3. round-trips a photonic MZI through every format, checking that its
#    waveguide nets stay waveguide;
# 4. goes from a `kfnetlist.Netlist` to every format and back.
#
# The example netlists of each format are described on
# [Parsing netlist formats](netlist_formats.py).

# %%
from kfnetlist import Netlist, NetlistPort, PortRef, morphnet
from kfnetlist.morphnet import netlist as formats

FORMATS = [
    "spice",
    "hspice",
    "xyce",
    "spectre",
    "spectre_spice",
    "vams",
    "systemverilog",
]


def convert(text: str, src: str, dst: str) -> str:
    """Convert netlist text from format `src` to format `dst`."""
    parse = getattr(formats, f"parse_{src}")
    write = getattr(formats, f"write_{dst}")
    return write(parse(text))


# %% [markdown]
# The same helper is a ten-line command-line converter
# (`docs/assets/convert_demo.py`): `python convert_demo.py spice spectre < in.sp`.
#
# ## Pairwise conversions
#
# ### SPICE → Spectre
#
# SPICE primitives (`M`, `R`, `C`, ...) become Spectre instances of the model
# or primitive; subcircuit calls keep their pin order.

# %%
SPICE = """\
* CMOS buffer
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
print(convert(SPICE, "spice", "spectre"))

# %% [markdown]
# ### Spectre → Verilog-AMS
#
# Positional Spectre terminals become named Verilog connections, using the pin
# names of the subcircuit or primitive (`d`, `g`, `s`, `b` for a MOSFET).

# %%
SPECTRE = """\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor r=1k
C1 (out gnd) capacitor c=100p
ends rc_lowpass
"""
print(convert(SPECTRE, "spectre", "vams"))

# %% [markdown]
# ### Verilog-AMS → SystemVerilog
#
# SystemVerilog has no SI suffixes, so `10k` is written as `10000`. The
# Verilog-AMS discipline (`electrical`) is kept as the port's net type.

# %%
VAMS = """\
module divider (vin, vout, gnd);
  input vin;
  output vout;
  inout gnd;
  electrical vin, vout, gnd;
  resistor #(.r(10k)) R1 (.p(vin), .n(vout));
  resistor #(.r(10k)) R2 (.p(vout), .n(gnd));
endmodule
"""
print(convert(VAMS, "vams", "systemverilog"))

# %% [markdown]
# ### SystemVerilog → SPICE
#
# Named connections are put back in definition order: modules defined in the
# same file become `.subckt` blocks and built-in devices (`mosfet`,
# `resistor`, ...) become SPICE primitives with their fixed pin order.
# Behavioral code (`always`, `assign` with logic) is not structure and is not
# written to SPICE.
#
# SPICE picks the element type from the first letter of the instance name, so
# subcircuit instances must be named `X...` and devices `M...`, `R...`, ...
# for the SPICE output to parse back.

# %%
SYSTEMVERILOG = """\
module inv (input a, output y, inout vdd, vss);
  mosfet #(.W(2e-6), .L(180e-9)) MP (.d(y), .g(a), .s(vdd), .b(vdd));
  mosfet #(.W(1e-6), .L(180e-9)) MN (.d(y), .g(a), .s(vss), .b(vss));
endmodule
module ring3 (output osc, inout vdd, vss);
  inv X1 (.a(osc), .y(n1), .*);
  inv X2 (.a(n1), .y(n2), .*);
  inv X3 (.a(n2), .y(osc), .*);
  always @(posedge osc) $display("tick");
endmodule
"""
print(convert(SYSTEMVERILOG, "systemverilog", "spice"))

# %% [markdown]
# ### HSPICE → Xyce

# %%
HSPICE = """\
* RC low-pass
.subckt rc_lowpass in_ out gnd
R1 in_ out 1k     $ series resistor
C1 out gnd 100p   $ shunt capacitor
.ends rc_lowpass
.end
"""
print(convert(HSPICE, "hspice", "xyce"))

# %% [markdown]
# ### Mixed Spectre / SPICE → SystemVerilog
#
# A deck that switches language with `simulator lang=...` comes out as one
# SystemVerilog file:

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
print(convert(SPECTRE_SPICE, "spectre_spice", "systemverilog"))

# %% [markdown]
# ## The conversion matrix
#
# The same CMOS buffer, written by hand in each of the 7 formats:

# %%
SOURCES = {
    "spice": SPICE,
    "hspice": """\
* buffer
.subckt inverter in out vdd vss
M1 out in vdd vdd pch W=2u L=180n   $ pull-up
M2 out in vss vss nch W=1u L=180n   $ pull-down
.ends inverter
.subckt buffer a y vdd vss
X1 a mid vdd vss inverter
X2 mid y vdd vss inverter
C1 y vss 10f
.ends buffer
.end
""",
    "xyce": """\
.SUBCKT inverter in out vdd vss
M1 out in vdd vdd pch W=2u L=180n
M2 out in vss vss nch W=1u L=180n
.ENDS inverter
.SUBCKT buffer a y vdd vss
X1 a mid vdd vss inverter
X2 mid y vdd vss inverter
C1 y vss 10f
.ENDS buffer
.END
""",
    "spectre": """\
subckt inverter (in out vdd vss)
M1 (out in vdd vdd) pch W=2u L=180n
M2 (out in vss vss) nch W=1u L=180n
ends inverter
subckt buffer (a y vdd vss)
X1 (a mid vdd vss) inverter
X2 (mid y vdd vss) inverter
C1 (y vss) capacitor value=10f
ends buffer
""",
    "spectre_spice": """\
simulator lang=spice
.subckt inverter in out vdd vss
M1 out in vdd vdd pch W=2u L=180n
M2 out in vss vss nch W=1u L=180n
.ends inverter
simulator lang=spectre
subckt buffer (a y vdd vss)
X1 (a mid vdd vss) inverter
X2 (mid y vdd vss) inverter
C1 (y vss) capacitor value=10f
ends buffer
""",
    "vams": """\
module inverter (in, out, vdd, vss);
  inout in, out, vdd, vss;
  electrical in, out, vdd, vss;
  mosfet #(.W(2u), .L(180n)) M1 (.d(out), .g(in), .s(vdd), .b(vdd));
  mosfet #(.W(1u), .L(180n)) M2 (.d(out), .g(in), .s(vss), .b(vss));
endmodule
module buffer (a, y, vdd, vss);
  inout a, y, vdd, vss;
  electrical a, y, vdd, vss;
  inverter X1 (.in(a), .out(mid), .vdd(vdd), .vss(vss));
  inverter X2 (.in(mid), .out(y), .vdd(vdd), .vss(vss));
  capacitor #(.value(10f)) C1 (.p(y), .n(vss));
endmodule
""",
    "systemverilog": """\
module inverter (inout in, out, vdd, vss);
  mosfet #(.W(2e-6), .L(180e-9)) M1 (.d(out), .g(in), .s(vdd), .b(vdd));
  mosfet #(.W(1e-6), .L(180e-9)) M2 (.d(out), .g(in), .s(vss), .b(vss));
endmodule
module buffer (inout a, y, vdd, vss);
  inverter X1 (.in(a), .out(mid), .vdd, .vss);
  inverter X2 (.in(mid), .out(y), .vdd, .vss);
  capacitor #(.value(10e-15)) C1 (.p(y), .n(vss));
endmodule
""",
}

# %% [markdown]
# Two netlists are "the same" when every circuit has the same ports, the same
# nets and the same instances with the same component and settings, as seen by
# `kfnetlist.Netlist`:


# %%
def graph(netlist: morphnet.Netlist) -> dict:
    out = {}
    for name, nl in morphnet.to_netlists(netlist).items():
        nl.sort()
        nets = sorted(
            sorted(
                m.name if isinstance(m, NetlistPort) else f"{m.instance}.{m.port}"
                for m in net
            )
            for net in nl.nets
        )
        instances = {
            k: (v.component, {s: float(f"{x:.9g}") for s, x in v.settings.items()})
            for k, v in nl.instances.items()
        }
        out[name] = (sorted(p.name for p in nl.ports), nets, instances)
    return out


reference = graph(formats.parse_spice(SPICE))
for name, (ports, nets, instances) in reference.items():
    print(f"{name}: ports={ports}")
    print(f"  nets={nets}")
    print(f"  instances={instances}")

# %% [markdown]
# All 7 sources parse to that graph:

# %%
for src, text in SOURCES.items():
    parsed = getattr(formats, f"parse_{src}")(text)
    print(f"{src:>14}: {'same' if graph(parsed) == reference else 'DIFFERENT'}")

# %% [markdown]
# Now convert each source (rows) to each target format (columns), parse the
# result back, and compare it with the reference:

# %%
width = max(map(len, FORMATS)) + 1
print(" " * width + "".join(f"{dst:>{width}}" for dst in FORMATS))
for src, text in SOURCES.items():
    row = []
    for dst in FORMATS:
        back = getattr(formats, f"parse_{dst}")(convert(text, src, dst))
        row.append("✓" if graph(back) == reference else "✗")
    print(f"{src:>{width}}" + "".join(f"{cell:>{width}}" for cell in row))

# %% [markdown]
# Connectivity and parameter values survive all 49 conversions. Some
# information is format-specific and does not:
#
# | Information | Kept by | Lost when written to |
# |---|---|---|
# | Device model name (`pch`, `nch`) | SPICE, HSPICE, Xyce, Spectre, Spectre-SPICE | Verilog-AMS, SystemVerilog |
# | `analog` blocks | Verilog-AMS | every other format |
# | Behavioral blocks (`always`, `initial`, ...) | SystemVerilog | every other format |
# | Port directions | Verilog-AMS, SystemVerilog | SPICE family and Spectre (all `inout`) |
# | SI suffixes (`10k`) | all but SystemVerilog | SystemVerilog writes `10000` |
# | Pin names of undefined cells | Verilog-AMS, SystemVerilog (named connections) | SPICE family and Spectre (positional) |
#
# For example, the model names are gone after a trip through Verilog-AMS:

# %%
print(convert(convert(SPICE, "spice", "vams"), "vams", "spice"))

# %% [markdown]
# ## A photonic MZI through every format
#
# Terminals named `o1`, `o2`, ... are waveguide terminals in every format, so
# a photonic circuit keeps its waveguide nets through any conversion. The leaf
# cells are declared as empty modules so that every format knows their pin
# names:

# %%
MZI = """\
module dc #(parameter real gap = 200e-9) (inout o1, o2, o3, o4);
endmodule
module wg #(parameter real length = 100e-6) (inout o1, o2);
endmodule
module heater_wg #(parameter real length = 100e-6) (inout o1, o2, e1, e2);
endmodule

module mzi (input o1, o2, output o3, o4, input e1, inout gnd);
  dc #(.gap(200e-9)) Xdc1 (.o1(o1), .o2(o2), .o3(top_a), .o4(bot_a));
  dc #(.gap(200e-9)) Xdc2 (.o1(top_b), .o2(bot_b), .o3(o3), .o4(o4));
  heater_wg Xtop (.o1(top_a), .o2(top_b), .e1(e1), .e2(gnd));
  wg Xbot (.o1(bot_a), .o2(bot_b));
endmodule
"""
mzi = formats.parse_systemverilog(MZI)


def net_domains(netlist: morphnet.Netlist) -> dict[str, str]:
    top = next(c for c in netlist.circuits if c.name == "mzi")
    return {c.name: c.domain.name.lower() for c in top.connections}


expected = net_domains(mzi)
print(expected)

# %%
for dst in FORMATS:
    text = getattr(formats, f"write_{dst}")(mzi)
    back = getattr(formats, f"parse_{dst}")(text)
    assert net_domains(back) == expected, dst
    assert graph(back) == graph(mzi), dst
    print(
        f"{dst:>14}: waveguide nets {sorted(n for n, d in expected.items() if d == 'waveguide')}"
    )

# %% [markdown]
# The MZI in Spectre and in Verilog-AMS:

# %%
print(formats.write_spectre(mzi))

# %%
print(formats.write_vams(mzi))

# %% [markdown]
# ## From `kfnetlist.Netlist` to any format and back
#
# `morphnet.from_netlists()` turns `{cell name: kfnetlist.Netlist}` into a
# morphnet `Netlist`. Instances of built-in devices (`resistor`,
# `capacitor`, `mosfet`, ...) get the same pin declarations the SPICE parser
# creates, so positional formats write their pins in device order.

# %%
rc = Netlist()
rc.create_inst("R1", kcl="", component="resistor", settings={"value": 1000.0})
rc.create_inst("C1", kcl="", component="capacitor", settings={"value": 1e-10})
for port in ("vin", "vout", "gnd"):
    rc.create_port(port)
rc.create_net(NetlistPort("vin"), PortRef("R1", "p"))
rc.create_net(PortRef("R1", "n"), PortRef("C1", "p"), NetlistPort("vout"))
rc.create_net(PortRef("C1", "n"), NetlistPort("gnd"))
rc.sort()

doc = morphnet.from_netlists({"rc": rc}, "rc")
for dst in FORMATS:
    text = getattr(formats, f"write_{dst}")(doc)
    back = getattr(formats, f"parse_{dst}")(text)
    print(f"{dst:>14}: {'same graph' if graph(back) == graph(doc) else 'DIFFERENT'}")

# %% [markdown]
# Ports, nets, components and settings come back unchanged. kfnetlist-only
# instance data (instance arrays, placement) has no place in the text
# formats; use `to_json()` / protobuf for a lossless copy.

# %%
print(formats.write_systemverilog(doc))
