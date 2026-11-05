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
# # Ring oscillator: build once, export to every format
#
# A hierarchical CMOS ring oscillator built with the `kfnetlist.morphnet` builder
# API, then written as SPICE, HSPICE, Xyce, Spectre, Verilog-AMS and YAML, and
# parsed back to show the conversion is bidirectional.
#
# Adapted from morphnet's `examples/inverter.py`. The changes:
#
# - The `nfet`/`pfet` external modules declare their ports, so positional
#   formats (SPICE, Spectre) know the pin order.
# - Nets that reach a circuit terminal are named after it. A subcircuit port is
#   wired to the node with the same name.
# - Instance names follow SPICE's first-letter convention: `X` marks a
#   subcircuit or PDK-cell call. Without it, `inv1` would read as a current
#   source.

# %%
from kfnetlist import morphnet
from kfnetlist.morphnet.netlist import (
    parse_hspice,
    parse_spectre,
    parse_spice,
    parse_vams,
    parse_xyce,
    write_hspice,
    write_spectre,
    write_spice,
    write_vams,
    write_xyce,
)

# %% [markdown]
# ## Leaf inverter cell
#
# `circuit()` declares a circuit and its parameters (names only, or
# `(name, default)` tuples).
# `add_terminal()` adds the circuit's I/O, `subcircuit()` places
# sub-instances with parameter overrides as keyword arguments, and `connect()`
# names a net and lists its endpoints. `("", terminal)` is the circuit's own
# terminal.

# %%
inv = morphnet.circuit("inverter", parameters=["l", "w"])
inv.add_terminal("vdd", direction=morphnet.PortDirection.INPUT)
inv.add_terminal("gnd", direction=morphnet.PortDirection.INPUT)
inv.add_terminal("inp", direction=morphnet.PortDirection.INPUT)
inv.add_terminal("out", direction=morphnet.PortDirection.OUTPUT)

inv.add(
    morphnet.subcircuit("XMN", "nfet", l=100e-9, w=500e-9),
    morphnet.subcircuit("XMP", "pfet", l=100e-9, w=1000e-9),
)

inv.connect("out", ("XMN", "drain"), ("XMP", "drain"), ("", "out"))
inv.connect("inp", ("", "inp"), ("XMN", "gate"), ("XMP", "gate"))
inv.connect("vdd", ("", "vdd"), ("XMP", "source"))
inv.connect("gnd", ("", "gnd"), ("XMN", "source"))

# %% [markdown]
# ## Ring oscillator: three inverters in a loop
#
# One instance overrides `w` through the `parameters` list; the others use the
# defaults.

# %%
ring = morphnet.circuit("ring_osc")
ring.add_terminal("vdd", direction=morphnet.PortDirection.INPUT)
ring.add_terminal("gnd", direction=morphnet.PortDirection.INPUT)
ring.add_terminal("osc_out", direction=morphnet.PortDirection.OUTPUT)

ring.add(
    morphnet.subcircuit("Xinv1", "inverter", parameters=[("w", 600e-9)]),
    morphnet.subcircuit("Xinv2", "inverter"),
    morphnet.subcircuit("Xinv3", "inverter"),
)
ring.connect("n1", ("Xinv1", "out"), ("Xinv2", "inp"))
ring.connect("n2", ("Xinv2", "out"), ("Xinv3", "inp"))
ring.connect("osc_out", ("Xinv3", "out"), ("Xinv1", "inp"), ("", "osc_out"))
ring.connect("vdd", ("", "vdd"), ("Xinv1", "vdd"), ("Xinv2", "vdd"), ("Xinv3", "vdd"))
ring.connect("gnd", ("", "gnd"), ("Xinv1", "gnd"), ("Xinv2", "gnd"), ("Xinv3", "gnd"))

# %% [markdown]
# ## Netlist: PDK library, device models, circuits
#
# `external_library()` points at the model file, and `ext_module()` declares the
# devices it provides, including their pin order.

# %%
fet_ports = [morphnet.port(name) for name in ("drain", "gate", "source")]

ckt = morphnet.Netlist(name="ring_osc_top", top_circuit="ring_osc")
ckt.add_library(
    "tt",
    morphnet.external_library(
        "path/to/tt.lib", model_type="tt", external_model_names=["nfet", "pfet"]
    ),
)
ckt.add_ext(
    morphnet.ext_module("nfet", class_name="nmos", library_name="tt", ports=fet_ports),
    morphnet.ext_module("pfet", class_name="pmos", library_name="tt", ports=fet_ports),
)
ckt.add(ring, inv)

assert ckt.top_circuit == "ring_osc"
assert [m.name for m in ckt.circuits] == ["ring_osc", "inverter"]
assert ckt.libraries["tt"].path == "path/to/tt.lib"

# %% [markdown]
# ## Export to every format

# %%
WRITERS = {
    "SPICE": write_spice,
    "HSPICE": write_hspice,
    "Xyce": write_xyce,
    "Spectre": write_spectre,
    "Verilog-AMS": write_vams,
}
texts = {fmt: write(ckt) for fmt, write in WRITERS.items()}
for fmt, text in texts.items():
    print(f"── {fmt} ──\n{text}")

# %% [markdown]
# The same `Netlist` also serializes to YAML (and to JSON or protobuf bytes) as a
# portable interchange format:

# %%
print(ckt.to_yaml())

# %% [markdown]
# ## Parse it back
#
# Every format parses back into a morphnet `Netlist`. Converting each one to
# `kfnetlist.Netlist` graphs shows that the connectivity survived every round trip.
#
# Positional formats (the SPICE family and Spectre) record pin *order*, not pin
# names, so their instance pins come back as `p0`, `p1`, and so on. Only
# Verilog-AMS keeps the names. The check below therefore compares pins by
# position.

# %%
from kfnetlist import NetlistPort  # noqa: E402

PARSERS = {
    "SPICE": parse_spice,
    "HSPICE": parse_hspice,
    "Xyce": parse_xyce,
    "Spectre": parse_spectre,
    "Verilog-AMS": parse_vams,
}
pin_order = {m.name: [p.name for p in m.ports] for m in [*ckt.circuits, *ckt.ext_modules]}
cell_of = {r.name: r.circuit_name for m in ckt.circuits for r in m.subcircuits}


def pin(member) -> str:
    if isinstance(member, NetlistPort):
        return f"<{member.name}>"
    pins = pin_order[cell_of[member.instance]]
    index = pins.index(member.port) if member.port in pins else int(member.port[1:])
    return f"{member.instance}[{index}]"


def connectivity(netlist: morphnet.Netlist) -> dict[str, list[list[str]]]:
    return {
        name: sorted(sorted(map(pin, net)) for net in nl.nets)
        for name, nl in morphnet.to_netlists(netlist).items()
    }


reference = connectivity(ckt)
for fmt, parse in PARSERS.items():
    assert connectivity(parse(texts[fmt])) == reference, fmt
    print(f"{fmt}: connectivity preserved")

# %% [markdown]
# ## Convert between formats
#
# Conversion is a parse followed by a write, for example Spectre → Verilog-AMS:

# %%
print(write_vams(parse_spectre(texts["Spectre"])))
