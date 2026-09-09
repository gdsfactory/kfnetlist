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
# # Hierarchical Flattening
#
# `Netlist.flatten()` replaces an instance by the contents of its **own cell's
# netlist**: an `mzi` instance becomes the mmis, straights and bends it is made
# of, and the parent's nets are rewired so every connection that landed on a
# port of the instance now lands on whatever that port is wired to inside the
# cell.
#
# This is what you want when a subcircuit should be dissolved into its parts —
# a containerized subcircuit, say — while a cell that has its own compact model
# stays intact. It is the opposite of
# [`remove_instances()`](instance_removal.py), which *deletes* an instance and
# merges the nets it touched.
#
# ## Finding the netlist of an instance
#
# Flattening needs to know which netlist belongs to each instance. Extraction
# returns a `{cell name: netlist}` mapping, but a plain `NetlistInstance` only
# records `component` — the *factory* name, which is not necessarily the cell
# name. So one of these has to supply the link:
#
# | Source | How |
# |--------|-----|
# | `PlacedInstance.cell` | automatic — `extract(include_placement=True)` fills it in |
# | `instance_cell_map` | `{instance name: cell name}` for the netlist being flattened |
# | `sub_instance_cell_maps` | `{cell name: {instance name: cell name}}` for the levels below |
#
# Instances whose cell cannot be resolved are left alone (pass
# `warn_skipped=True` to hear about them).

# %%
from kfnetlist import Netlist, PortRef, flatten_netlists

# %% [markdown]
# ## A two-level hierarchy
#
# `chain` is a cell containing two straights in series; `top` places one
# `chain` next to a `straight`.

# %%
straight = Netlist()  # a primitive: ports, no instances of its own
straight.create_port("o1")
straight.create_port("o2")

chain = Netlist()
chain.create_inst("wg1", kcl="PDK", component="straight")
chain.create_inst("wg2", kcl="PDK", component="straight")
chain_o1 = chain.create_port("o1")
chain_o2 = chain.create_port("o2")
chain.create_net(chain_o1, PortRef(instance="wg1", port="o1"))
chain.create_net(PortRef(instance="wg1", port="o2"), PortRef(instance="wg2", port="o1"))
chain.create_net(PortRef(instance="wg2", port="o2"), chain_o2)

top = Netlist()
top.create_inst("sub1", kcl="PDK", component="chain")
top.create_inst("s1", kcl="PDK", component="straight")
top_in = top.create_port("in")
top.create_net(top_in, PortRef(instance="sub1", port="o1"))
top.create_net(PortRef(instance="sub1", port="o2"), PortRef(instance="s1", port="o1"))

netlists = {"straight": straight, "chain": chain, "top": top}


def show(name: str, nl: Netlist) -> None:
    print(f"{name}: instances={nl.instance_names()}")
    for net in nl.nets:
        members = [
            f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
            for m in net
        ]
        print(f"    {' — '.join(members)}")


show("top", top)

# %% [markdown]
# ## Flattening one netlist
#
# The inlined instances are renamed `"{instance}.{inner instance}"`, so
# `wg1` inside `sub1` becomes `sub1.wg1`. The top-level port `in`, which used
# to reach `sub1.o1`, now reaches `sub1.wg1.o1` directly.

# %%
flat = top.flatten(
    netlists,
    instance_cell_map={"sub1": "chain", "s1": "straight"},
    sub_instance_cell_maps={"chain": {"wg1": "straight", "wg2": "straight"}},
)
show("top (flattened)", flat)

# %% [markdown]
# `s1` survived: `straight` is a primitive, and a cell with no instances of its
# own is skipped — inlining it would delete the instance and its connectivity
# with nothing to put in its place.
#
# ## Choosing what to inline
#
# `cells` restricts inlining to the named cells, `exclude` protects cells from
# it. Use `exclude` for the cells that have their own model:

# %%
show(
    "top (chain kept intact)",
    top.flatten(
        netlists,
        instance_cell_map={"sub1": "chain", "s1": "straight"},
        exclude=["chain"],
    ),
)

# %% [markdown]
# ## Flattening a whole hierarchy
#
# `flatten_netlists()` applies the same operation to every entry of the
# mapping — the shape `extract()` returns. Each netlist is flattened against
# the *original* mapping, so the result does not depend on iteration order, and
# the cells that were inlined keep their own entry.

# %%
flat_all = flatten_netlists(
    netlists,
    instance_cell_maps={
        "top": {"sub1": "chain", "s1": "straight"},
        "chain": {"wg1": "straight", "wg2": "straight"},
    },
)
for name, nl in flat_all.items():
    show(name, nl)

# %% [markdown]
# ## Straight from extraction
#
# `extract()` knows every cell name already, so no maps are needed:
#
# ```python
# from kfnetlist.extract import extract
#
# # inline the whole hierarchy
# netlists = extract(cell, wrap_kdb_instance=..., flatten=True)
#
# # or only the containers, keeping the MZI as one instance
# netlists = extract(cell, wrap_kdb_instance=..., flatten=["container_a"])
# ```
#
# With `include_placement=True` the result is a `PlacedNetlist` and each
# inlined placement is composed with the placement of the instance it came
# from, so the geometry stays in the flattened cell's coordinates.
#
# ## Edge cases
#
# | Situation | Behaviour |
# |-----------|-----------|
# | Sub-cell has no instances (a primitive) | skipped |
# | Instance's cell name unknown | skipped |
# | Array instance (`na`/`nb` > 1) | skipped — it has no single inlined copy |
# | Inner net touching no sub-cell port | stays, as a floating net |
# | Inner net touching two sub-cell ports | merges both parent nets |
# | Connected port with no net inside the sub-cell | raises; `allow_unconnected_ports=True` inlines anyway and drops that connection |
# | Inlined name already taken | raises |
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Deleting an instance instead | [Instance Removal](instance_removal.py) |
# | Placement-aware netlists | [Placement](placement.py) |
# | Extraction pipeline | [Extraction: Overview](../extraction/overview.md) |
