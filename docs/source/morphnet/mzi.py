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
# 1. converts it to `kfnetlist.Netlist` graphs,
# 2. flattens the coupler sub-cells with kfnetlist,
# 3. exports the flat netlist to Verilog-AMS, Spectre and SPICE.
#
# Adapted from morphnet's `examples/mzi.py`. The changes:
#
# - Each delay arm now sits *between* the couplers (`o1`, then `o2`); the
#   original wired the arm input and the next coupler to the same net.
# - Optical terminals follow the gdsfactory naming `o1`, `o2`, ... (inputs
#   first), which every netlist parser reads as waveguide terminals.
# - The external circuits declare their ports.
# - Nets that reach a circuit terminal are named after it.
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
dc = morphnet.circuit("dc_coupler", parameters=[("gap", 200e-9), ("length", 10e-6)])
for name in ("o1", "o2", "o3", "o4"):
    dc.add_terminal(name, direction=IN if name in ("o1", "o2") else OUT, domain=WG)

dc.add(morphnet.subcircuit("Xcoupler", "wg_directional_coupler"))
for name in ("o1", "o2", "o3", "o4"):
    dc.connect(name, ("", name), ("Xcoupler", name), domain=WG)

# %% [markdown]
# ## MZI top cell
#
# Two couplers, with a delay arm on each path between them.

# %%
mzi = morphnet.circuit("mzi", parameters=[("arm_length", 100e-6)])
for name in ("o1", "o2", "o3", "o4"):
    mzi.add_terminal(name, direction=IN if name in ("o1", "o2") else OUT, domain=WG)

mzi.add(
    morphnet.subcircuit("Xdc1", "dc_coupler"),
    morphnet.subcircuit("Xdc2", "dc_coupler"),
    morphnet.subcircuit("Xarm_top", "wg_delay"),
    morphnet.subcircuit("Xarm_bot", "wg_delay"),
)
for net, *ends in [
    ("o1", ("", "o1"), ("Xdc1", "o1")),
    ("o2", ("", "o2"), ("Xdc1", "o2")),
    ("top_a", ("Xdc1", "o3"), ("Xarm_top", "o1")),
    ("top_b", ("Xarm_top", "o2"), ("Xdc2", "o1")),
    ("bot_a", ("Xdc1", "o4"), ("Xarm_bot", "o1")),
    ("bot_b", ("Xarm_bot", "o2"), ("Xdc2", "o2")),
    ("o3", ("Xdc2", "o3"), ("", "o3")),
    ("o4", ("Xdc2", "o4"), ("", "o4")),
]:
    mzi.connect(net, *ends, domain=WG)

# %% [markdown]
# ## Netlist with a photonic PDK library

# %%
ckt = morphnet.Netlist(name="mzi_chip", top_circuit="mzi")
ckt.add_library(
    "photonic_pdk",
    morphnet.external_library(
        "path/to/photonic_pdk.lib",
        model_type="photonic",
        external_model_names=["wg_directional_coupler", "wg_delay"],
    ),
)
ckt.add_ext(
    morphnet.ext_circuit(
        "wg_directional_coupler",
        class_name="dc",
        library_name="photonic_pdk",
        ports=[morphnet.port(p, domain=WG) for p in ("o1", "o2", "o3", "o4")],
    ),
    morphnet.ext_circuit(
        "wg_delay",
        class_name="delay_line",
        library_name="photonic_pdk",
        ports=[morphnet.port(p, domain=WG) for p in ("o1", "o2")],
    ),
)
ckt.add(mzi, dc)

mzi_module = next(m for m in ckt.circuits if m.name == "mzi")
assert all(t.domain == WG for t in mzi_module.ports)
print(write_vams(ckt))

# %% [markdown]
# ## Into kfnetlist
#
# `to_netlists` gives one `kfnetlist.Netlist` per circuit, so all of kfnetlist's
# tooling applies: open detection, LVS diffs, flattening.

# %%
netlists = morphnet.to_netlists(ckt)
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
# `from_netlists` turns the flat `kfnetlist.Netlist` back into a morphnet `Netlist`. The
# external circuits are declared again so the positional formats keep the pin order.

# %%
flat_ckt = morphnet.from_netlists({"mzi_flat": flat}, "mzi_flat")
flat_ckt.add_ext(*ckt.ext_circuits)
print(write_vams(flat_ckt))
print(write_spectre(flat_ckt))
print(write_spice(flat_ckt))
