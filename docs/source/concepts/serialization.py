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
# # Serialization
#
# Every kfnetlist type supports two serialization formats:
#
# | Method | Format | Use case |
# |--------|--------|----------|
# | `to_json()` / `from_json()` | JSON string | File I/O, network transport |
# | `to_dict()` / `from_dict()` | Python dict | In-memory manipulation, Pydantic integration |
#
# Both are fully round-trippable: `T.from_json(obj.to_json()) == obj`.

# %%
import json

from kfnetlist import (
    Net,
    Netlist,
    NetlistInstance,
    NetlistPort,
    PortArrayRef,
    PortRef,
)

# %% [markdown]
# ## Individual type serialization
#
# Each port type, net, and instance can be serialized independently.

# %% [markdown]
# ### NetlistPort

# %%
p = NetlistPort(name="in")
print("JSON:", p.to_json())
print("Dict:", p.to_dict())

# %% [markdown]
# ### PortRef

# %%
ref = PortRef(instance="wg1", port="o2")
print("JSON:", ref.to_json())
print("Dict:", ref.to_dict())

# %% [markdown]
# ### PortArrayRef

# %%
aref = PortArrayRef(instance="pad_array", port="p1", ia=2, ib=0)
print("JSON:", aref.to_json())
print("Dict:", aref.to_dict())

# %% [markdown]
# ### Net

# %%
net = Net(
    [
        NetlistPort(name="in"),
        PortRef(instance="wg1", port="o1"),
    ]
)
print("JSON:", net.to_json())
print("Dict:", net.to_dict())

# %% [markdown]
# ### NetlistInstance

# %%
inst = NetlistInstance(
    kcl="MY_PDK",
    component="straight",
    settings={"width": 500, "length": 10_000},
    name="wg1",
)
print("JSON:", inst.to_json())
print("Dict:", inst.to_dict())

# %% [markdown]
# ## Full Netlist serialization
#
# The `Netlist` itself supports JSON and dict round-trips containing all
# instances, nets, and ports.

# %%
nl = Netlist()
nl.create_inst("wg1", kcl="PDK", component="straight", settings={"width": 500})
nl.create_inst("wg2", kcl="PDK", component="straight", settings={"width": 500})
p_in = nl.create_port("in")
nl.create_net(p_in, PortRef(instance="wg1", port="o1"))
nl.create_net(PortRef(instance="wg1", port="o2"), PortRef(instance="wg2", port="o1"))
nl.sort()

json_str = nl.to_json()
print(json.dumps(json.loads(json_str), indent=2))

# %% [markdown]
# ### JSON round-trip

# %%
nl_restored = Netlist.from_json(json_str)
nl_restored.sort()
assert nl.to_dict() == nl_restored.to_dict()
print("JSON round-trip ✓")

# %% [markdown]
# ### Dict round-trip

# %%
d = nl.to_dict()
nl_from_dict = Netlist.from_dict(d)
nl_from_dict.sort()
assert nl.to_dict() == nl_from_dict.to_dict()
print("Dict round-trip ✓")

# %% [markdown]
# ## Wire format notes
#
# The JSON/dict wire format has a few conventions:
#
# - **Instance names are keys**, not stored inside the instance payload. This
#   avoids redundancy (`{"wg1": {"kcl": ..., "component": ...}}`).
# - **Net members are untagged** — the deserializer infers the type from the
#   fields present (`{"name": ...}` → `NetlistPort`, `{"instance": ..., "port": ...}`
#   → `PortRef`, add `ia`/`ib` → `PortArrayRef`).
# - **Nets auto-sort** their members on construction and mutation, so the
#   serialized order is always deterministic after `sort()`.

# %% [markdown]
# ## Pydantic integration
#
# All kfnetlist types implement `__get_pydantic_core_schema__`, so they can be
# used directly as fields in Pydantic v2 models without custom validators.
#
# ```python
# from pydantic import BaseModel
# from kfnetlist import Netlist
#
# class Design(BaseModel):
#     name: str
#     netlist: Netlist
# ```

# %% [markdown]
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Netlist data model | [Netlist Model](netlist_model.py) |
# | Port types | [Ports & Refs](ports_and_refs.py) |
