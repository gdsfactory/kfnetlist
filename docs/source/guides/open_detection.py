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
# # Open Detection
#
# kfnetlist provides two methods on `Netlist` for detecting open circuits —
# missing or incomplete connections that indicate wiring problems.
#
# ## Methods
#
# | Method | Returns | Purpose |
# |--------|---------|---------|
# | `detect_opens()` | `dict` | Find unconnected ports and singleton nets in a single netlist |
# | `find_open_nets(reference)` | `list[Net]` | Find nets present in `reference` but missing from `self` |

# %% [markdown]
# ## `detect_opens()`
#
# Inspects a single netlist for signs of incomplete wiring.

# %%
from kfnetlist import Netlist, NetlistPort, PortRef

nl = Netlist()
nl.create_inst("a", kcl="pdk", component="other", settings={})
nl.create_port("VDD")
nl.create_port("VSS")

# Only VDD is wired — VSS is an unconnected port
nl.create_net(
    NetlistPort(name="VDD"),
    PortRef(instance="a", port="p1"),
)

# A singleton net (only one member — dangling stub)
nl.create_net(
    PortRef(instance="a", port="p2"),
)

result = nl.detect_opens()
print("Unconnected ports:", result["unconnected_ports"])
print("Singleton nets:", len(result["singleton_nets"]))

# %% [markdown]
# The returned dict has two keys:
#
# - **`unconnected_ports`** — a sorted list of top-level port names that are
#   not referenced by any net.
# - **`singleton_nets`** — nets with exactly one member.  A single-member net
#   is a dangling stub that often indicates an accidental open.

# %% [markdown]
# ## `find_open_nets(reference)`
#
# Compares two netlists by set-difference on their nets.  Returns nets that
# exist in the *reference* (typically a schematic netlist) but are absent
# from `self` (typically the extracted/layout netlist).

# %%
schematic = Netlist()
schematic.create_inst("a", kcl="pdk", component="other", settings={})
schematic.create_inst("b", kcl="pdk", component="other", settings={})
schematic.create_port("VDD")
schematic.create_port("VSS")
schematic.create_net(NetlistPort(name="VDD"), PortRef(instance="a", port="p1"))
schematic.create_net(NetlistPort(name="VSS"), PortRef(instance="b", port="p1"))

# Extracted netlist is missing the VSS net
extracted = Netlist()
extracted.create_inst("a", kcl="pdk", component="other", settings={})
extracted.create_inst("b", kcl="pdk", component="other", settings={})
extracted.create_port("VDD")
extracted.create_port("VSS")
extracted.create_net(NetlistPort(name="VDD"), PortRef(instance="a", port="p1"))

missing = extracted.find_open_nets(schematic)
print(f"Missing nets: {len(missing)}")
for net in missing:
    members = list(net)
    print(f"  Net members: {[str(m) for m in members]}")

# %% [markdown]
# Net equality is based on sorted member content, so insertion order does
# not matter.
#
# ## Typical workflow
#
# ```python
# # 1. Check extracted netlist for internal issues
# opens = extracted_nl.detect_opens()
# if opens["unconnected_ports"]:
#     print(f"Warning: unconnected ports: {opens['unconnected_ports']}")
#
# # 2. Compare against schematic for missing nets
# missing = extracted_nl.find_open_nets(schematic_nl)
# if missing:
#     print(f"Error: {len(missing)} nets missing from layout")
# ```
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Short detection | [Short Detection](../extraction/short_detection.py) |
# | Netlist data model | [Concepts: Netlist Model](../concepts/netlist_model.py) |
