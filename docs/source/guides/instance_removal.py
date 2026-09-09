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
# # Instance Removal
#
# `Netlist.remove_instances()` deletes named instances from the netlist and
# merges any nets that were connected through the removed instances' ports.
# This is used during extraction to absorb unnamed or excluded instances into
# the parent cell's netlist.
#
# Nothing of the removed instance's own cell is kept. To *replace* an instance
# by the contents of its cell instead, see
# [Hierarchical Flattening](hierarchical_flattening.py).
#
# !!! note
#     This method used to be called `flatten_instances()`. That name still
#     works but raises a `DeprecationWarning`, because `Netlist.flatten()` now
#     means hierarchical flattening.

# %%
from kfnetlist import Netlist, PortRef

# %% [markdown]
# ## Example: removing a helper instance
#
# Consider a netlist where `helper` is an intermediate instance we want to
# absorb into its parent.

# %%
nl = Netlist()

nl.create_inst("src", kcl="PDK", component="source")
nl.create_inst("helper", kcl="PDK", component="passthrough")
nl.create_inst("sink", kcl="PDK", component="sink")

# src.out → helper.in
nl.create_net(
    PortRef(instance="src", port="out"), PortRef(instance="helper", port="in")
)

# helper.out → sink.in
nl.create_net(
    PortRef(instance="helper", port="out"), PortRef(instance="sink", port="in")
)

nl.sort()

print("Before removal:")
print(f"  Instances: {nl.instance_names()}")
for i, net in enumerate(nl.nets):
    members = [
        f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
        for m in net
    ]
    print(f"  net[{i}]: {' — '.join(members)}")

# %% [markdown]
# ## Applying `remove_instances()`
#
# Pass a list of instance names to remove. The instances are deleted, and any
# nets that shared a port on a removed instance are merged.

# %%
nl.remove_instances(["helper"])
nl.sort()

print("\nAfter removing 'helper':")
print(f"  Instances: {nl.instance_names()}")
for i, net in enumerate(nl.nets):
    members = [
        f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
        for m in net
    ]
    print(f"  net[{i}]: {' — '.join(members)}")

# %% [markdown]
# The `helper` instance is gone, and `src.out` is now directly connected to
# `sink.in` in a single merged net.
#
# ## When is this used?
#
# During netlist extraction, `remove_instances()` is called to:
#
# - **Remove unnamed instances** (`ignore_unnamed=True`) — instances that were
#   not given explicit names during placement
# - **Remove excluded instances** (`exclude_purposes=["routing"]`) — instances
#   whose purpose tag marks them as infrastructure (routing waveguides, etc.)
#   rather than functional components
#
# After removal, the netlist reflects only the named, functional instances
# and their direct connectivity.
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Netlist data model | [Concepts: Netlist Model](../concepts/netlist_model.py) |
# | Replacing an instance by its cell | [Hierarchical Flattening](hierarchical_flattening.py) |
# | Extraction pipeline | [Extraction: Overview](../extraction/overview.md) |
