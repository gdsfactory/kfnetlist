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
# # Ports & Refs
#
# kfnetlist uses three types to identify connection points in a netlist. Each
# type is a Rust-backed, hashable, orderable value object.
#
# | Type | Use case |
# |------|----------|
# | `NetlistPort` | Cell-level port — a top-level pin visible outside the cell |
# | `PortRef` | Reference to a port on a named instance |
# | `PortArrayRef` | Reference to a port on a specific element of an array instance |
#
# All three are valid **net members** — they can be passed to `Netlist.create_net()`
# and stored inside a `Net`.

# %%
from kfnetlist import NetlistPort, PortArrayRef, PortRef

# %% [markdown]
# ## NetlistPort
#
# A `NetlistPort` represents a cell-level port identified solely by its name.

# %%
p = NetlistPort(name="in")
print(f"name: {p.name}")
print(f"hash: {hash(p)}")
print(f"equal: {p == NetlistPort(name='in')}")

# %% [markdown]
# ## PortRef
#
# A `PortRef` identifies a port on a specific instance by instance name and
# port name.

# %%
ref = PortRef(instance="mmi1", port="o2")
print(f"instance: {ref.instance}, port: {ref.port}")
print(f"hash: {hash(ref)}")

# %% [markdown]
# `as_python_str()` returns a human-readable representation, optionally using
# a custom instance variable name.

# %%
print(ref.as_python_str())
print(ref.as_python_str("splitter"))

# %% [markdown]
# ## PortArrayRef
#
# A `PortArrayRef` extends `PortRef` with array indices `ia` and `ib` to
# identify a port on a specific element of an array instance.

# %%
aref = PortArrayRef(instance="pad_array", port="p1", ia=2, ib=0)
print(f"instance: {aref.instance}, port: {aref.port}, ia: {aref.ia}, ib: {aref.ib}")
print(aref.as_python_str())

# %% [markdown]
# ## Ordering
#
# The three types have a defined ordering: `NetlistPort < PortRef < PortArrayRef`.
# Within each type, ordering is lexicographic by fields. This ordering is used
# by `Net.sort()` and `Netlist.sort()` to produce stable, reproducible output.

# %%
items = [
    PortRef(instance="b", port="o1"),
    NetlistPort(name="out"),
    PortArrayRef(instance="a", port="p1", ia=0, ib=0),
    NetlistPort(name="in"),
    PortRef(instance="a", port="o1"),
]
for item in sorted(items):
    print(f"  {type(item).__name__}: {item}")

# %% [markdown]
# ## Hashing and equality
#
# All three types are hashable and support equality comparison, so they can be
# used in sets and as dict keys.

# %%
s = {
    NetlistPort(name="in"),
    PortRef(instance="wg1", port="o1"),
    NetlistPort(name="in"),  # duplicate
}
print(f"Set size (with duplicate): {len(s)}")
assert PortRef(instance="a", port="b") == PortRef(instance="a", port="b")
print("Equality ✓")

# %% [markdown]
# ## Serialization
#
# Each type supports `to_json()` / `from_json()` and `to_dict()` / `from_dict()`.

# %%
ref = PortRef(instance="mmi1", port="o2")
print("JSON:", ref.to_json())
print("Dict:", ref.to_dict())

ref2 = PortRef.from_json(ref.to_json())
assert ref == ref2
print("Round-trip ✓")

# %% [markdown]
# ## Summary
#
# | Type | Fields | Purpose |
# |------|--------|---------|
# | `NetlistPort` | `name` | Cell-level port |
# | `PortRef` | `instance`, `port` | Port on a named instance |
# | `PortArrayRef` | `instance`, `port`, `ia`, `ib` | Port on an array element |
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Netlist data model | [Netlist Model](netlist_model.py) |
# | Serialization details | [Serialization](serialization.py) |
