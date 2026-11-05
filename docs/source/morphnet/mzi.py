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
# # Photonic MZI: builder API, kfnetlist round trip, export
#
# A Mach-Zehnder interferometer built hierarchically with the
# `kfnetlist.morphnet` builder API. The notebook then:
#
# 1. converts it to kfnetlist `Netlist`s,
# 2. flattens the coupler sub-cells with kfnetlist,
# 3. exports the flat netlist to Verilog-AMS, Spectre and SPICE.
#
# Adapted from morphnet's `examples/mzi.py`. The changes:
#
# - Each delay arm now sits *between* the couplers (`inp`, then `out`); the
#   original wired the arm input and the next coupler to the same net.
# - The external modules declare their ports.
# - Nets that reach a module terminal are named after it.
# - Instance names start with `X`, SPICE's prefix for subcircuit calls, so the
#   SPICE export is valid.

# %%
from kfnetlist import morphnet
from kfnetlist.morphnet.netlist import write_spectre, write_spice, write_vams

WG = morphnet.SignalDomain.WAVEGUIDE
IN, OUT = morphnet.PortDirection.INPUT, morphnet.PortDirection.OUTPUT

# %% [markdown]
# ## Directional coupler sub-cell
#
# Parameter defaults are given as `(name, value)` tuples. The terminals are in
# the waveguide domain.

# %%
dc = morphnet.module("dc_coupler", parameters=[("gap", 200e-9), ("length", 10e-6)])
for name in ("i1", "i2", "o1", "o2"):
    dc.add_terminal(name, direction=IN if name[0] == "i" else OUT, domain=WG)

dc.add(morphnet.module_reference("Xcoupler", "wg_directional_coupler"))
for name in ("i1", "i2", "o1", "o2"):
    dc.connect(name, ("", name), ("Xcoupler", name))

# %% [markdown]
# ## MZI top cell
#
# Two couplers, with a delay arm on each path between them.

# %%
mzi = morphnet.module("mzi", parameters=[("arm_length", 100e-6)])
for name in ("in1", "in2", "out1", "out2"):
    mzi.add_terminal(name, direction=IN if name.startswith("in") else OUT, domain=WG)

mzi.add(
    morphnet.module_reference("Xdc1", "dc_coupler"),
    morphnet.module_reference("Xdc2", "dc_coupler"),
    morphnet.module_reference("Xarm_top", "wg_delay"),
    morphnet.module_reference("Xarm_bot", "wg_delay"),
)
mzi.connect("in1", ("", "in1"), ("Xdc1", "i1"))
mzi.connect("in2", ("", "in2"), ("Xdc1", "i2"))
mzi.connect("top_a", ("Xdc1", "o1"), ("Xarm_top", "inp"))
mzi.connect("top_b", ("Xarm_top", "out"), ("Xdc2", "i1"))
mzi.connect("bot_a", ("Xdc1", "o2"), ("Xarm_bot", "inp"))
mzi.connect("bot_b", ("Xarm_bot", "out"), ("Xdc2", "i2"))
mzi.connect("out1", ("Xdc2", "o1"), ("", "out1"))
mzi.connect("out2", ("Xdc2", "o2"), ("", "out2"))

# %% [markdown]
# ## Circuit with a photonic PDK library

# %%
ckt = morphnet.circuit("mzi_chip", top_module="mzi")
ckt.add_library(
    "photonic_pdk",
    morphnet.external_library(
        "path/to/photonic_pdk.lib",
        model_type="photonic",
        external_model_names=["wg_directional_coupler", "wg_delay"],
    ),
)
ckt.add_ext(
    morphnet.ext_module(
        "wg_directional_coupler",
        class_name="dc",
        library_name="photonic_pdk",
        ports=[morphnet.port(p, domain=WG) for p in ("i1", "i2", "o1", "o2")],
    ),
    morphnet.ext_module(
        "wg_delay",
        class_name="delay_line",
        library_name="photonic_pdk",
        ports=[morphnet.port(p, domain=WG) for p in ("inp", "out")],
    ),
)
ckt.add(mzi, dc)

mzi_module = next(m for m in ckt.modules if m.name == "mzi")
assert all(t.domain == WG for t in mzi_module.ports)
print(write_vams(ckt))

# %% [markdown]
# ## Into kfnetlist
#
# `circuit_to_netlists` gives one `Netlist` per module, so all of kfnetlist's
# tooling applies: open detection, LVS diffs, flattening.

# %%
netlists = morphnet.circuit_to_netlists(ckt)
print({name: nl for name, nl in netlists.items()})
print("opens:", netlists["mzi"].detect_opens())

# %% [markdown]
# Flatten the two coupler instances into their contents:

# %%
flat = netlists["mzi"].flatten(
    netlists,
    instance_cell_map={"Xdc1": "dc_coupler", "Xdc2": "dc_coupler"},
    separator="_",  # keeps flattened names valid identifiers in every format
)
flat.sort()
print("instances:", flat.instance_names())

# %% [markdown]
# ## And back out, in any format
#
# `circuit_from_netlists` turns the flat `Netlist` back into a `Circuit`. The
# external modules are declared again so the positional formats keep the pin order.

# %%
flat_ckt = morphnet.circuit_from_netlists({"mzi_flat": flat}, "mzi_flat")
flat_ckt.add_ext(*ckt.ext_modules)
print(write_vams(flat_ckt))
print(write_spectre(flat_ckt))
print(write_spice(flat_ckt))
