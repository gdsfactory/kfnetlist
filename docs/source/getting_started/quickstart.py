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
# # 5-Minute Quickstart
#
# This page walks through the essential kfnetlist operations: creating a netlist,
# adding instances, wiring them up with nets, and serializing the result.

# %%
from kfnetlist import Netlist, NetlistPort, PortRef

# %% [markdown]
# ## Creating a netlist
#
# A `Netlist` is the top-level container. It holds instances, nets, and
# top-level ports.

# %%
nl = Netlist()

# %% [markdown]
# ## Adding instances
#
# `create_inst` registers a sub-cell instance. Each instance records its PDK
# (`kcl`), component name, and settings.

# %%
nl.create_inst(
    "wg1",
    kcl="MY_PDK",
    component="straight",
    settings={"width": 500, "length": 10_000},
)
nl.create_inst(
    "wg2",
    kcl="MY_PDK",
    component="straight",
    settings={"width": 500, "length": 10_000},
)

print("Instances:", nl.instance_names())

# %% [markdown]
# ## Adding top-level ports
#
# `create_port` adds a cell-level port — an externally visible connection point.

# %%
p_in = nl.create_port("in")
p_out = nl.create_port("out")

print("Ports:", [p.name for p in nl.ports])

# %% [markdown]
# ## Creating nets
#
# `create_net` connects two or more port members. Members can be `NetlistPort`
# (cell-level ports) or `PortRef` (instance ports).

# %%
# Cell-level "in" connects to wg1's input
nl.create_net(p_in, PortRef(instance="wg1", port="o1"))

# Internal: wg1's output connects to wg2's input
nl.create_net(
    PortRef(instance="wg1", port="o2"),
    PortRef(instance="wg2", port="o1"),
)

# wg2's output connects to cell-level "out"
nl.create_net(PortRef(instance="wg2", port="o2"), p_out)

print(f"Nets ({len(nl.nets)}):")
for i, net in enumerate(nl.nets):
    members = []
    for m in net:
        if isinstance(m, PortRef):
            members.append(f"{m.instance}.{m.port}")
        elif isinstance(m, NetlistPort):
            members.append(f"<{m.name}>")
    print(f"  net[{i}]: {' — '.join(members)}")

# %% [markdown]
# ## Sorting for stable comparison
#
# Port ordering within a net and net ordering across the netlist can vary.
# `sort()` normalises both, making equality checks reproducible.

# %%
nl.sort()
print("Sorted instance names:", nl.instance_names())

# %% [markdown]
# ## Serialization
#
# Every kfnetlist type supports `to_json()` / `from_json()` and `to_dict()` /
# `from_dict()` for round-trip serialization.

# %%
import json

json_str = nl.to_json()
print(json.loads(json_str))

# %%
# Round-trip: reconstruct from JSON
nl2 = Netlist.from_json(json_str)
nl2.sort()
assert nl.to_dict() == nl2.to_dict()
print("Round-trip ✓")

# %% [markdown]
# ## Summary
#
# | Operation | API |
# |-----------|-----|
# | Create a netlist | `Netlist()` |
# | Add an instance | `nl.create_inst(name, kcl, component, settings)` |
# | Add a top-level port | `nl.create_port(name)` |
# | Wire ports together | `nl.create_net(member1, member2, ...)` |
# | Normalise for comparison | `nl.sort()` |
# | Serialize to JSON | `nl.to_json()` / `Netlist.from_json(s)` |
# | Serialize to dict | `nl.to_dict()` / `Netlist.from_dict(d)` |
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Full data model | [Concepts: Netlist Model](../concepts/netlist_model.py) |
# | Port types | [Concepts: Ports & Refs](../concepts/ports_and_refs.py) |
# | JSON / dict details | [Concepts: Serialization](../concepts/serialization.py) |
