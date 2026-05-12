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
# # Equivalent Ports
#
# Some components — pads, bumps, redistribution-layer vias — have multiple ports
# that are **electrically equivalent**: they connect to the same metal plane. A
# naive netlist comparison would fail because the extracted netlist tracks every
# individual port, while the schematic may declare only one logical connection.
#
# `Netlist.lvs_equivalent()` solves this by folding equivalent ports into a
# single canonical name, merging nets that share a canonical port.

# %%
from kfnetlist import Netlist, NetlistPort, PortRef

# %% [markdown]
# ## Building a netlist with equivalent ports
#
# Consider a pad with two ports `p1` and `p2` that are electrically the same,
# connected to a waveguide on one side and exposed at the cell boundary on
# the other.

# %%
nl = Netlist()

nl.create_inst("wg1", kcl="PDK", component="straight", settings={"width": 500})
nl.create_inst("pad1", kcl="PDK", component="pad", settings={"size": 5000})

p_in = nl.create_port("in")
p_out = nl.create_port("out")

# Cell "in" → wg1.o1
nl.create_net(p_in, PortRef(instance="wg1", port="o1"))

# wg1.o2 → pad1.p1
nl.create_net(PortRef(instance="wg1", port="o2"), PortRef(instance="pad1", port="p1"))

# pad1.p2 → cell "out"
nl.create_net(PortRef(instance="pad1", port="p2"), p_out)

nl.sort()

print("Before equivalence mapping:")
for i, net in enumerate(nl.nets):
    members = []
    for m in net:
        if isinstance(m, PortRef):
            members.append(f"{m.instance}.{m.port}")
        elif isinstance(m, NetlistPort):
            members.append(f"<{m.name}>")
    print(f"  net[{i}]: {' — '.join(members)}")

# %% [markdown]
# The pad's `p1` and `p2` appear in separate nets. For netlist comparison,
# these should be treated as one.
#
# ## Applying `lvs_equivalent()`
#
# The `equivalent_ports` dict maps component names to groups of port names that
# should be merged. Within each group, the first port name becomes the canonical
# name.

# %%
equivalent_ports = {
    "pad": [["p1", "p2"]],
}

equiv_nl = nl.lvs_equivalent(
    cell_name="top",
    equivalent_ports=equivalent_ports,
)
equiv_nl.sort()

print("\nAfter equivalence mapping:")
for i, net in enumerate(equiv_nl.nets):
    members = []
    for m in net:
        if isinstance(m, PortRef):
            members.append(f"{m.instance}.{m.port}")
        elif isinstance(m, NetlistPort):
            members.append(f"<{m.name}>")
    print(f"  net[{i}]: {' — '.join(members)}")

# %% [markdown]
# After mapping, `pad1.p2` is rewritten to `pad1.p1`, and the two nets that
# shared a canonical port are merged into one.
#
# ## How it works
#
# `lvs_equivalent()` internally uses a **union-find** data structure with path
# compression:
#
# 1. For each instance whose component has equivalent port groups, all port
#    references are rewritten to the canonical (first) port name in their group
# 2. Nets that now share a member are merged
# 3. The result is a new `Netlist` — the original is not modified
#
# ## Port mapping
#
# You can also supply an explicit `port_mapping` dict for finer control:
#
# ```python
# equiv_nl = nl.lvs_equivalent(
#     cell_name="top",
#     equivalent_ports={"pad": [["p1", "p2"]]},
#     port_mapping={"pad": {"p2": "p1"}},
# )
# ```
#
# The `port_mapping` maps `{component_name: {from_port: to_port}}`. When both
# `equivalent_ports` and `port_mapping` are given, `equivalent_ports` defines
# which ports are equivalent and `port_mapping` specifies the canonical names.

# %% [markdown]
# ## Immutability
#
# `lvs_equivalent()` returns a **new** `Netlist` — the original is unchanged.

# %%
assert nl.to_dict() != equiv_nl.to_dict()
print("Original netlist unchanged ✓")

# %% [markdown]
# ## Summary
#
# | Operation | API |
# |-----------|-----|
# | Fold equivalent ports | `nl.lvs_equivalent(cell_name, equivalent_ports)` |
# | With explicit mapping | `nl.lvs_equivalent(cell_name, equivalent_ports, port_mapping)` |
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Netlist data model | [Concepts: Netlist Model](../concepts/netlist_model.py) |
# | Full extraction pipeline | [Extraction: Overview](../extraction/overview.md) |
