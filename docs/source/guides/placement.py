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
# # Placement-Aware Netlists
#
# A plain [`Netlist`](../concepts/netlist_model.py) captures **connectivity**:
# instances, nets, and ports. Some workflows — simulation setup, floorplanning,
# visualization — also need to know **where** each instance physically sits in
# the layout.
#
# `PlacedNetlist` is a second flavor for exactly that. It is a subclass of
# `Netlist` (so all connectivity behaviour is inherited unchanged) whose
# instances are `PlacedInstance` objects. Each `PlacedInstance` adds:
#
# - **`cell`** — the placed cell's name (distinct from `component`, which is the
#   factory name);
# - **`placement`** — a purely geometric `Placement`: origin `x`/`y`,
#   `orientation`, `mirror`, and `bbox`.
#
# `Placement` describes *where* an instance is; the `cell` name (what it *is*)
# lives on the instance, not inside the placement.

# %%
import json

from kfnetlist import (
    Netlist,
    NetlistPort,
    Placement,
    PlacedInstance,
    PlacedNetlist,
    PortRef,
)

# %% [markdown]
# ## Building a placed netlist directly
#
# `PlacedNetlist.create_inst()` mirrors `Netlist.create_inst()` with two extra
# trailing arguments: the placed `cell` name and a `placement`. The bounding
# box is a plain dict in klayout `left/bottom/right/top` convention (µm).

# %%
pnl = PlacedNetlist()

pnl.create_inst(
    name="wg1",
    kcl="PDK",
    component="straight_factory",  # factory / parametric-cell name
    settings={"width": 0.5},
    cell="straight",  # the actual layout cell name
    placement=Placement(
        x=0.0,
        y=0.0,
        orientation=0.0,
        mirror=False,
        bbox={"left": 0.0, "bottom": -0.25, "right": 10.0, "top": 0.25},
    ),
)

pnl.create_inst(
    name="bend1",
    kcl="PDK",
    component="bend_euler",
    cell="bend_euler",
    placement=Placement(
        x=10.0,
        y=0.0,
        orientation=90.0,
        mirror=False,
        bbox={"left": 10.0, "bottom": 0.0, "right": 15.0, "top": 5.0},
    ),
)

# Connectivity works exactly as on a plain Netlist.
pnl.create_port("o1")
pnl.create_net(NetlistPort(name="o1"), PortRef(instance="wg1", port="o1"))
pnl.create_net(PortRef(instance="wg1", port="o2"), PortRef(instance="bend1", port="o1"))
pnl.sort()

# %% [markdown]
# A `PlacedNetlist` *is* a `Netlist`, so connectivity tooling keeps working:

# %%
print("isinstance(pnl, Netlist):", isinstance(pnl, Netlist))
print("instance names:", pnl.instance_names())
print("nets:")
for net in pnl.nets:
    members = [
        f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
        for m in net
    ]
    print("  -", " — ".join(members))

# %% [markdown]
# ## Inspecting placement
#
# `instances` returns `PlacedInstance` objects (cell + placement); `placements`
# is a convenience map of just the geometry, keyed by instance name.

# %%
for name, inst in pnl.instances.items():
    p = inst.placement
    print(f"{name}: cell={inst.cell!r} component={inst.component!r}")
    print(
        f"    origin=({p.x}, {p.y}) µm, orientation={p.orientation}°, mirror={p.mirror}"
    )
    print(f"    bbox={p.bbox}")

# %% [markdown]
# ## Serialization
#
# `PlacedNetlist` round-trips through JSON and dicts like every other type. The
# `cell` sits alongside the connectivity fields, and `placement` is a nested
# block per instance.

# %%
d = pnl.to_dict()
print(json.dumps(d["instances"]["bend1"], indent=2))

# %%
restored = PlacedNetlist.from_json(pnl.to_json())
assert restored.instances["bend1"].placement == pnl.instances["bend1"].placement
assert restored.instances["bend1"].cell == "bend_euler"
print("round-trip OK")

# %% [markdown]
# ## Upgrading an existing netlist
#
# If you already have a plain `Netlist` (e.g. from another tool), attach
# placement with `from_netlist()`. It takes the netlist plus two name-keyed
# maps — `placements` and `cells` — and keeps only entries for instances that
# actually exist. Instances without an entry get empty defaults.

# %%
nl = Netlist()
nl.create_inst(name="mmi1", kcl="PDK", component="mmi1x2")
nl.create_port("in")
nl.create_net(NetlistPort(name="in"), PortRef(instance="mmi1", port="o1"))

placed = PlacedNetlist.from_netlist(
    nl,
    placements={
        "mmi1": Placement(
            x=2.0,
            y=1.0,
            orientation=180.0,
            mirror=True,
            bbox={"left": 0.0, "bottom": 0.0, "right": 6.0, "top": 2.0},
        )
    },
    cells={"mmi1": "mmi1x2"},
)

mmi = placed.instances["mmi1"]
assert isinstance(mmi, PlacedInstance)
print("cell:", mmi.cell, "| placement:", mmi.placement)
# Connectivity carried over unchanged.
print("nets preserved:", [list(n) == list(o) for n, o in zip(placed.nets, nl.nets)])

# %% [markdown]
# ## From extraction
#
# When extracting from a layout, pass `include_placement=True` to `extract()`.
# Each returned value is then a `PlacedNetlist` instead of a `Netlist`, with the
# placed cell name and placement read from the layout for every surviving
# instance:
#
# ```python
# from kfnetlist.extract import extract
#
# netlists = extract(
#     cell,
#     wrap_kdb_instance=lambda i: Instance(kcl=cell.kcl, instance=i),
#     include_placement=True,
# )
# placed = netlists[cell.name]          # a PlacedNetlist
# placed.instances["wg1"].placement.x   # origin x in µm
# placed.instances["wg1"].cell          # the placed cell name
# ```
#
# The default (`include_placement=False`) returns plain `Netlist` objects,
# identical to before — placement never changes connectivity, and is excluded
# from equality so LVS comparisons are unaffected.
#
# See [Extraction Overview](../extraction/overview.md) for the full pipeline.
