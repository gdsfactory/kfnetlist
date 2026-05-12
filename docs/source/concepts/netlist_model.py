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
# # Netlist Model
#
# The `Netlist` is the central data structure in kfnetlist. It represents the
# connectivity of a circuit cell: which sub-cell instances are placed, which of
# their ports are connected, and which ports are exposed at the cell boundary.
#
# ## Data model overview
#
# | Attribute | Type | Description |
# |-----------|------|-------------|
# | `instances` | `dict[str, NetlistInstance]` | Sub-cell instances keyed by name |
# | `nets` | `list[Net]` | Each net groups connected port members |
# | `ports` | `list[NetlistPort]` | Top-level ports exposed by this cell |
#
# A `Net` is an ordered collection of **net members** — each member is one of:
#
# | Type | Meaning |
# |------|---------|
# | `NetlistPort` | A cell-level port (top-level pin) |
# | `PortRef` | A port on a named instance |
# | `PortArrayRef` | A port on a specific element of an array instance |

# %%
from kfnetlist import (
    Net,
    Netlist,
    NetlistPort,
    PortRef,
)

# %% [markdown]
# ## Creating a Netlist
#
# Start with an empty `Netlist` and populate it with instances, ports, and nets.

# %%
nl = Netlist()

# %% [markdown]
# ### Instances
#
# `create_inst` returns the created `NetlistInstance`. Each instance records the
# PDK name (`kcl`), component name, and a settings dict.

# %%
inst1 = nl.create_inst(
    "mmi1",
    kcl="MY_PDK",
    component="mmi1x2",
    settings={"width": 500, "gap": 250},
)
inst2 = nl.create_inst(
    "wg1",
    kcl="MY_PDK",
    component="straight",
    settings={"width": 500, "length": 10_000},
)

print(f"Instances: {nl.instance_names()}")
print(f"has 'mmi1': {nl.has_instance('mmi1')}")
print(f"mmi1 component: {nl.get_instance('mmi1').component}")
print(f"mmi1 settings: {nl.get_instance('mmi1').settings}")

# %% [markdown]
# ### Array instances
#
# Pass `na` and `nb` to `create_inst` to create an array instance. Use
# `PortArrayRef` to reference ports on specific array elements.

# %%
nl2 = Netlist()
arr = nl2.create_inst(
    "pad_array",
    kcl="MY_PDK",
    component="pad",
    settings={"size": 100},
    na=4,
    nb=2,
)
print(f"Array: na={arr.array.na}, nb={arr.array.nb}")

# %% [markdown]
# ### Top-level ports

# %%
p_in = nl.create_port("in")
p_out1 = nl.create_port("out1")
p_out2 = nl.create_port("out2")

print("Ports:", [p.name for p in nl.ports])

# %% [markdown]
# ### Nets
#
# `create_net` takes two or more net members and records that they share
# electrical connectivity.

# %%
nl.create_net(p_in, PortRef(instance="mmi1", port="o1"))
nl.create_net(PortRef(instance="mmi1", port="o2"), PortRef(instance="wg1", port="o1"))
nl.create_net(PortRef(instance="wg1", port="o2"), p_out1)
nl.create_net(PortRef(instance="mmi1", port="o3"), p_out2)

print(f"\nNets ({len(nl.nets)}):")
for i, net in enumerate(nl.nets):
    members = []
    for m in net:
        if isinstance(m, PortRef):
            members.append(f"{m.instance}.{m.port}")
        elif isinstance(m, NetlistPort):
            members.append(f"<{m.name}>")
    print(f"  net[{i}]: {' — '.join(members)}")

# %% [markdown]
# ### Adding pre-built nets
#
# You can also build a `Net` object manually and add it with `add_net`.

# %%
nl3 = Netlist()
nl3.create_inst("a", kcl="X", component="comp_a")
nl3.create_inst("b", kcl="X", component="comp_b")

net = Net([PortRef(instance="a", port="out"), PortRef(instance="b", port="in")])
nl3.add_net(net)
print("Net members:", [f"{m.instance}.{m.port}" for m in nl3.nets[0]])

# %% [markdown]
# ## Sorting
#
# `sort()` normalises instance order, port order, and intra-net member order.
# This makes equality checks between two netlists deterministic.

# %%
nl.sort()
print("Sorted instances:", nl.instance_names())
print("Sorted ports:", [p.name for p in nl.ports])

# %% [markdown]
# ## Properties return snapshots
#
# The `instances`, `nets`, and `ports` properties return **fresh copies** each
# time they are accessed. This prevents accidental mutation of the internal
# state — any changes must go through the mutation API (`create_inst`,
# `create_net`, etc.).

# %%
instances_a = nl.instances
instances_b = nl.instances
assert instances_a is not instances_b
print("Properties return fresh snapshots ✓")

# %% [markdown]
# ## Summary
#
# | Operation | API |
# |-----------|-----|
# | Create empty netlist | `Netlist()` |
# | Add instance | `nl.create_inst(name, kcl, component, settings, na, nb)` |
# | Check instance | `nl.has_instance(name)` / `nl.get_instance(name)` |
# | List instance names | `nl.instance_names()` |
# | Add top-level port | `nl.create_port(name)` |
# | Create a net | `nl.create_net(member1, member2, ...)` |
# | Add pre-built net | `nl.add_net(net)` |
# | Normalise ordering | `nl.sort()` |
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Port reference types | [Ports & Refs](ports_and_refs.py) |
# | Serialization | [Serialization](serialization.py) |
# | Equivalent ports | [Guides: Equivalent Ports](../guides/equivalent_ports.py) |
