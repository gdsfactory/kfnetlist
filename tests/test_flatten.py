"""Tests for hierarchical netlist flattening (``Netlist.flatten``).

Flattening replaces an instance by the contents of its own cell's netlist, so
every test here builds a small ``{cell name: netlist}`` mapping — the same shape
``kfnetlist.extract.extract()`` returns — and inlines against it.
"""

from __future__ import annotations

import pytest
from kfnetlist import (
    Netlist,
    NetlistPort,
    Placement,
    PlacedNetlist,
    PortArrayRef,
    PortRef,
    flatten_netlists,
)


def _bbox(
    left: float = 0.0, bottom: float = 0.0, right: float = 1.0, top: float = 1.0
) -> dict[str, float]:
    return {"left": left, "bottom": bottom, "right": right, "top": top}


def _placement(
    x: float = 0.0,
    y: float = 0.0,
    orientation: float = 0.0,
    mirror: bool = False,
    bbox: dict[str, float] | None = None,
) -> Placement:
    return Placement(x, y, orientation, mirror, bbox if bbox is not None else _bbox())


def _leaf(*ports: str) -> Netlist:
    """A primitive: declares ports, has no instances of its own."""
    nl = Netlist()
    for port in ports:
        nl.create_port(port)
    return nl


def _chain() -> Netlist:
    """``o1 -- wg1 -- wg2 -- o2``: two straights in series."""
    nl = Netlist()
    nl.create_inst("wg1", kcl="P", component="straight")
    nl.create_inst("wg2", kcl="P", component="straight")
    o1 = nl.create_port("o1")
    o2 = nl.create_port("o2")
    nl.create_net(o1, PortRef(instance="wg1", port="o1"))
    nl.create_net(
        PortRef(instance="wg1", port="o2"), PortRef(instance="wg2", port="o1")
    )
    nl.create_net(PortRef(instance="wg2", port="o2"), o2)
    return nl


def _top_with_chain() -> Netlist:
    """``in -- sub1 -- s1``, where ``sub1`` is an instance of the chain cell."""
    nl = Netlist()
    nl.create_inst("sub1", kcl="P", component="chain")
    nl.create_inst("s1", kcl="P", component="straight")
    port_in = nl.create_port("in")
    nl.create_net(port_in, PortRef(instance="sub1", port="o1"))
    nl.create_net(
        PortRef(instance="sub1", port="o2"), PortRef(instance="s1", port="o1")
    )
    return nl


def _netlists() -> dict[str, Netlist]:
    return {"straight": _leaf("o1", "o2"), "chain": _chain(), "top": _top_with_chain()}


CELL_MAP = {"sub1": "chain", "s1": "straight"}
# Keyed by the cell that *contains* the instances, top cell included — the shape
# `extract()` hands to `flatten_netlists()`.
CELL_MAPS = {"top": CELL_MAP, "chain": {"wg1": "straight", "wg2": "straight"}}


def _net_strings(nl: Netlist) -> set[frozenset[str]]:
    """Nets as comparable sets of member names (``port`` / ``instance,port``)."""
    return {
        frozenset(
            member.name
            if isinstance(member, NetlistPort)
            else f"{member.instance},{member.port}"
            for member in net
        )
        for net in nl.nets
    }


# --- the core behaviour ----------------------------------------------------


def test_inlines_instances_and_stitches_nets() -> None:
    top = _top_with_chain()
    flat = top.flatten(
        _netlists(), instance_cell_map=CELL_MAP, sub_instance_cell_maps=CELL_MAPS
    )

    # `sub1` is gone, replaced by its own instances; the leaf `s1` stays.
    assert sorted(flat.instances) == ["s1", "sub1.wg1", "sub1.wg2"]
    assert _net_strings(flat) == {
        frozenset({"in", "sub1.wg1,o1"}),
        frozenset({"sub1.wg1,o2", "sub1.wg2,o1"}),
        frozenset({"sub1.wg2,o2", "s1,o1"}),
    }
    # Top-level ports are untouched.
    assert [p.name for p in flat.ports] == ["in"]


def test_inlined_instances_keep_their_identity() -> None:
    top = _top_with_chain()
    flat = top.flatten(
        _netlists(), instance_cell_map=CELL_MAP, sub_instance_cell_maps=CELL_MAPS
    )
    inner = flat.instances["sub1.wg1"]
    assert inner.name == "sub1.wg1"
    assert inner.component == "straight"
    assert inner.kcl == "P"


def test_original_netlist_is_untouched() -> None:
    top = _top_with_chain()
    top.flatten(
        _netlists(), instance_cell_map=CELL_MAP, sub_instance_cell_maps=CELL_MAPS
    )
    assert sorted(top.instances) == ["s1", "sub1"]


def test_separator_is_configurable() -> None:
    top = _top_with_chain()
    flat = top.flatten(
        _netlists(),
        instance_cell_map=CELL_MAP,
        sub_instance_cell_maps=CELL_MAPS,
        separator="/",
    )
    assert sorted(flat.instances) == ["s1", "sub1/wg1", "sub1/wg2"]


# --- selecting what to inline ---------------------------------------------


def test_cells_restricts_to_named_cells() -> None:
    top = _top_with_chain()
    flat = top.flatten(_netlists(), ["straight"], instance_cell_map=CELL_MAP)
    # `straight` is a leaf, so nothing is inlinable and `chain` is not selected.
    assert sorted(flat.instances) == ["s1", "sub1"]


def test_exclude_wins_over_the_default_selection() -> None:
    top = _top_with_chain()
    flat = top.flatten(_netlists(), instance_cell_map=CELL_MAP, exclude=["chain"])
    assert sorted(flat.instances) == ["s1", "sub1"]


def test_unresolvable_instances_are_left_alone() -> None:
    top = _top_with_chain()
    # No map at all: a plain NetlistInstance does not know its cell.
    flat = top.flatten(_netlists())
    assert sorted(flat.instances) == ["s1", "sub1"]
    assert _net_strings(flat) == _net_strings(top)


def test_warn_skipped_reports_each_instance_once() -> None:
    top = _top_with_chain()
    with pytest.warns(UserWarning) as records:
        top.flatten(_netlists(), warn_skipped=True)
    messages = [str(r.message) for r in records]
    assert any('instance "sub1"' in m and "cell name is unknown" in m for m in messages)
    assert len(messages) == 2  # one per instance, not one per pass


def test_skipping_is_silent_by_default() -> None:
    top = _top_with_chain()
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        top.flatten(_netlists())


def test_leaf_cells_are_skipped() -> None:
    """A cell with ports but no instances would lose its connectivity."""
    nl = Netlist()
    nl.create_inst("s1", kcl="P", component="straight")
    port_in = nl.create_port("in")
    nl.create_net(port_in, PortRef(instance="s1", port="o1"))

    flat = nl.flatten(
        {"straight": _leaf("o1", "o2")}, instance_cell_map={"s1": "straight"}
    )
    assert sorted(flat.instances) == ["s1"]
    assert _net_strings(flat) == {frozenset({"in", "s1,o1"})}


def test_missing_cell_netlist_is_skipped() -> None:
    top = _top_with_chain()
    flat = top.flatten({}, instance_cell_map=CELL_MAP)
    assert sorted(flat.instances) == ["s1", "sub1"]


def test_array_instances_are_skipped() -> None:
    nl = Netlist()
    nl.create_inst("arr", kcl="P", component="chain", na=2, nb=3)
    port_in = nl.create_port("in")
    nl.create_net(port_in, PortArrayRef(instance="arr", port="o1", ia=0, ib=0))

    flat = nl.flatten(
        _netlists(), instance_cell_map={"arr": "chain"}, warn_skipped=False
    )
    assert sorted(flat.instances) == ["arr"]


# --- recursion -------------------------------------------------------------


def _nested() -> dict[str, Netlist]:
    """``outer`` contains one ``chain``, which contains two ``straight``s."""
    outer = Netlist()
    outer.create_inst("c1", kcl="P", component="chain")
    o1 = outer.create_port("o1")
    o2 = outer.create_port("o2")
    outer.create_net(o1, PortRef(instance="c1", port="o1"))
    outer.create_net(PortRef(instance="c1", port="o2"), o2)

    top = Netlist()
    top.create_inst("out1", kcl="P", component="outer")
    port_in = top.create_port("in")
    top.create_net(port_in, PortRef(instance="out1", port="o1"))
    return {
        "straight": _leaf("o1", "o2"),
        "chain": _chain(),
        "outer": outer,
        "top": top,
    }


NESTED_MAPS = {
    "top": {"out1": "outer"},
    "outer": {"c1": "chain"},
    "chain": {"wg1": "straight", "wg2": "straight"},
}


def test_recursive_flatten_reaches_the_leaves() -> None:
    netlists = _nested()
    flat = netlists["top"].flatten(
        netlists,
        instance_cell_map={"out1": "outer"},
        sub_instance_cell_maps=NESTED_MAPS,
    )
    assert sorted(flat.instances) == ["out1.c1.wg1", "out1.c1.wg2"]
    assert _net_strings(flat) == {
        frozenset({"in", "out1.c1.wg1,o1"}),
        frozenset({"out1.c1.wg1,o2", "out1.c1.wg2,o1"}),
        # `outer.o2` is wired out of the cell but `top` never connects to it,
        # so it stays a floating stub.
        frozenset({"out1.c1.wg2,o2"}),
    }


def test_non_recursive_stops_after_one_level() -> None:
    netlists = _nested()
    flat = netlists["top"].flatten(
        netlists,
        instance_cell_map={"out1": "outer"},
        sub_instance_cell_maps=NESTED_MAPS,
        recursive=False,
    )
    assert sorted(flat.instances) == ["out1.c1"]


def test_self_referential_mapping_raises_instead_of_hanging() -> None:
    """A real hierarchy is a DAG; a hand-built mapping need not be."""
    looping = Netlist()
    looping.create_inst("me", kcl="P", component="looping")
    port = looping.create_port("o1")
    looping.create_net(port, PortRef(instance="me", port="o1"))

    with pytest.raises(ValueError, match="contains itself"):
        looping.flatten(
            {"looping": looping},
            instance_cell_map={"me": "looping"},
            sub_instance_cell_maps={"looping": {"me": "looping"}},
        )


def test_recursion_stops_where_cell_names_run_out() -> None:
    """Without ``sub_instance_cell_maps``, only this netlist's level resolves."""
    netlists = _nested()
    flat = netlists["top"].flatten(netlists, instance_cell_map={"out1": "outer"})
    assert sorted(flat.instances) == ["out1.c1"]


# --- net rewiring edge cases ----------------------------------------------


def test_internally_shorted_ports_merge_the_parent_nets() -> None:
    """One inner net touching two sub-cell ports joins both parent nets."""
    sub = Netlist()
    sub.create_inst("w", kcl="P", component="straight")
    o1 = sub.create_port("o1")
    o2 = sub.create_port("o2")
    sub.create_net(o1, o2, PortRef(instance="w", port="o1"))

    top = Netlist()
    top.create_inst("x", kcl="P", component="sub")
    top.create_inst("a", kcl="P", component="straight")
    top.create_inst("b", kcl="P", component="straight")
    top.create_net(PortRef(instance="a", port="o1"), PortRef(instance="x", port="o1"))
    top.create_net(PortRef(instance="b", port="o1"), PortRef(instance="x", port="o2"))

    flat = top.flatten({"sub": sub}, instance_cell_map={"x": "sub"})
    assert _net_strings(flat) == {frozenset({"a,o1", "b,o1", "x.w,o1"})}


def test_floating_inner_nets_stay_floating() -> None:
    sub = Netlist()
    sub.create_inst("w", kcl="P", component="straight")
    sub.create_inst("dangling", kcl="P", component="straight")
    o1 = sub.create_port("o1")
    sub.create_net(o1, PortRef(instance="w", port="o1"))
    # Not wired to any sub-cell port.
    sub.create_net(
        PortRef(instance="w", port="o2"), PortRef(instance="dangling", port="o1")
    )

    top = Netlist()
    top.create_inst("x", kcl="P", component="sub")
    port_in = top.create_port("in")
    top.create_net(port_in, PortRef(instance="x", port="o1"))

    flat = top.flatten({"sub": sub}, instance_cell_map={"x": "sub"})
    assert _net_strings(flat) == {
        frozenset({"in", "x.w,o1"}),
        frozenset({"x.w,o2", "x.dangling,o1"}),
    }


def test_connected_port_without_an_inner_net_raises() -> None:
    sub = Netlist()
    sub.create_inst("w", kcl="P", component="straight")
    sub.create_port("o1")  # declared, but wired to nothing inside

    top = Netlist()
    top.create_inst("x", kcl="P", component="sub")
    port_in = top.create_port("in")
    top.create_net(port_in, PortRef(instance="x", port="o1"))

    with pytest.raises(ValueError, match="not part of any net inside"):
        top.flatten({"sub": sub}, instance_cell_map={"x": "sub"})


def test_allow_unconnected_ports_drops_the_connection() -> None:
    sub = Netlist()
    sub.create_inst("w", kcl="P", component="straight")
    sub.create_port("o1")

    top = Netlist()
    top.create_inst("x", kcl="P", component="sub")
    top.create_inst("a", kcl="P", component="straight")
    port_in = top.create_port("in")
    top.create_net(
        port_in,
        PortRef(instance="x", port="o1"),
        PortRef(instance="a", port="o1"),
    )

    flat = top.flatten(
        {"sub": sub}, instance_cell_map={"x": "sub"}, allow_unconnected_ports=True
    )
    # The rest of the net survives; only the reference to `x.o1` is gone.
    assert _net_strings(flat) == {frozenset({"in", "a,o1"})}
    assert sorted(flat.instances) == ["a", "x.w"]


def test_name_collision_raises() -> None:
    sub = Netlist()
    sub.create_inst("wg", kcl="P", component="straight")
    o1 = sub.create_port("o1")
    sub.create_net(o1, PortRef(instance="wg", port="o1"))

    top = Netlist()
    top.create_inst("x", kcl="P", component="sub")
    top.create_inst("x.wg", kcl="P", component="straight")
    port_in = top.create_port("in")
    top.create_net(port_in, PortRef(instance="x", port="o1"))

    with pytest.raises(ValueError, match="already exists"):
        top.flatten({"sub": sub}, instance_cell_map={"x": "sub"})


def test_flatten_rejects_a_non_mapping() -> None:
    with pytest.raises(TypeError, match="must be a dict"):
        _top_with_chain().flatten([_chain()])  # ty: ignore[invalid-argument-type]


def test_flatten_rejects_non_netlist_values() -> None:
    with pytest.raises(TypeError, match="Netlist or PlacedNetlist"):
        _top_with_chain().flatten({"chain": object()})  # ty: ignore[invalid-argument-type]


# --- placed flavor ---------------------------------------------------------


def _placed_chain() -> PlacedNetlist:
    nl = PlacedNetlist()
    nl.create_inst(
        "wg1",
        kcl="P",
        component="straight",
        cell="straight",
        placement=_placement(x=10.0, bbox=_bbox(0.0, -1.0, 5.0, 1.0)),
    )
    o1 = nl.create_port("o1")
    nl.create_net(o1, PortRef(instance="wg1", port="o1"))
    return nl


def _placed_top(orientation: float = 90.0, mirror: bool = False) -> PlacedNetlist:
    nl = PlacedNetlist()
    nl.create_inst(
        "c1",
        kcl="P",
        component="chain",
        cell="chain",
        placement=_placement(x=100.0, y=50.0, orientation=orientation, mirror=mirror),
    )
    port_in = nl.create_port("in")
    nl.create_net(port_in, PortRef(instance="c1", port="o1"))
    return nl


def test_placed_flatten_returns_a_placed_netlist() -> None:
    top = _placed_top()
    flat = top.flatten({"chain": _placed_chain()})
    assert isinstance(flat, PlacedNetlist)
    assert sorted(flat.instances) == ["c1.wg1"]
    assert set(flat.placements) == {"c1.wg1"}


def test_placed_flatten_needs_no_maps() -> None:
    """``PlacedInstance.cell`` is the dict key, so resolution is automatic."""
    top = _placed_top()
    flat = top.flatten({"chain": _placed_chain()})
    assert flat.instances["c1.wg1"].cell == "straight"


def test_placement_is_composed_with_the_parent_transform() -> None:
    flat = _placed_top(orientation=90.0).flatten({"chain": _placed_chain()})
    placement = flat.instances["c1.wg1"].placement
    # (10, 0) rotated 90° about the origin, then moved to (100, 50).
    assert (placement.x, placement.y) == (100.0, 60.0)
    assert placement.orientation == 90.0
    assert placement.mirror is False
    # The child bbox (0, -1)-(5, 1) rotates into (-1, 0)-(1, 5).
    assert placement.bbox == {
        "left": 99.0,
        "bottom": 50.0,
        "right": 101.0,
        "top": 55.0,
    }


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (0.0, (110.0, 50.0)),
        (90.0, (100.0, 60.0)),
        (180.0, (90.0, 50.0)),
        (270.0, (100.0, 40.0)),
    ],
)
def test_right_angle_composition_is_exact(
    orientation: float, expected: tuple[float, float]
) -> None:
    flat = _placed_top(orientation=orientation).flatten({"chain": _placed_chain()})
    placement = flat.instances["c1.wg1"].placement
    assert (placement.x, placement.y) == expected


def test_mirror_composes_as_an_xor() -> None:
    chain = PlacedNetlist()
    chain.create_inst(
        "wg1",
        kcl="P",
        component="straight",
        cell="straight",
        placement=_placement(x=10.0, y=4.0, mirror=True),
    )
    o1 = chain.create_port("o1")
    chain.create_net(o1, PortRef(instance="wg1", port="o1"))

    flat = _placed_top(orientation=0.0, mirror=True).flatten({"chain": chain})
    placement = flat.instances["c1.wg1"].placement
    # Parent mirrors, child mirrors -> no mirror; the child y is flipped.
    assert placement.mirror is False
    assert (placement.x, placement.y) == (110.0, 46.0)


def test_mirror_only_on_the_parent_is_kept() -> None:
    flat = _placed_top(orientation=0.0, mirror=True).flatten({"chain": _placed_chain()})
    placement = flat.instances["c1.wg1"].placement
    assert placement.mirror is True
    assert (placement.x, placement.y) == (110.0, 50.0)


def test_placed_flatten_composes_across_two_levels() -> None:
    inner = PlacedNetlist()
    inner.create_inst(
        "wg",
        kcl="P",
        component="straight",
        cell="straight",
        placement=_placement(x=1.0),
    )
    port = inner.create_port("o1")
    inner.create_net(port, PortRef(instance="wg", port="o1"))

    middle = PlacedNetlist()
    middle.create_inst(
        "i1", kcl="P", component="inner", cell="inner", placement=_placement(x=10.0)
    )
    middle_port = middle.create_port("o1")
    middle.create_net(middle_port, PortRef(instance="i1", port="o1"))

    top = PlacedNetlist()
    top.create_inst(
        "m1", kcl="P", component="middle", cell="middle", placement=_placement(x=100.0)
    )
    top_port = top.create_port("in")
    top.create_net(top_port, PortRef(instance="m1", port="o1"))

    flat = top.flatten({"inner": inner, "middle": middle})
    assert sorted(flat.instances) == ["m1.i1.wg"]
    assert flat.instances["m1.i1.wg"].placement.x == 111.0


def test_placed_flatten_survives_plain_sub_netlists() -> None:
    """A plain sub-netlist has no placement to compose; connectivity still works."""
    top = _placed_top()
    flat = top.flatten({"chain": _chain()}, sub_instance_cell_maps=CELL_MAPS)
    assert isinstance(flat, PlacedNetlist)
    assert sorted(flat.instances) == ["c1.wg1", "c1.wg2"]
    # No placement to inherit, but the cell name from the map is recorded.
    assert flat.instances["c1.wg1"].cell == "straight"
    # A child without a placement of its own lands on the parent's transform.
    placement = flat.instances["c1.wg1"].placement
    assert (placement.x, placement.y, placement.orientation) == (100.0, 50.0, 90.0)


def test_placed_flatten_leaves_cell_blank_when_unknown() -> None:
    top = _placed_top()
    flat = top.flatten({"chain": _chain()})
    assert flat.instances["c1.wg1"].cell == ""


# --- the dict-level helper -------------------------------------------------


def test_flatten_netlists_flattens_every_entry() -> None:
    flat = flatten_netlists(_nested(), instance_cell_maps=NESTED_MAPS)
    # Same keys: inlining a parent does not invalidate the child's netlist.
    assert set(flat) == {"straight", "chain", "outer", "top"}
    assert sorted(flat["top"].instances) == ["out1.c1.wg1", "out1.c1.wg2"]
    assert sorted(flat["outer"].instances) == ["c1.wg1", "c1.wg2"]
    assert sorted(flat["chain"].instances) == ["wg1", "wg2"]  # leaves stay


def test_flatten_netlists_is_order_independent() -> None:
    netlists = _nested()
    reversed_order = dict(reversed(list(netlists.items())))
    assert _net_strings(
        flatten_netlists(netlists, instance_cell_maps=NESTED_MAPS)["top"]
    ) == _net_strings(
        flatten_netlists(reversed_order, instance_cell_maps=NESTED_MAPS)["top"]
    )


def test_flatten_netlists_passes_the_selection_through() -> None:
    flat = flatten_netlists(_nested(), ["chain"], instance_cell_maps=NESTED_MAPS)
    # Only `chain` instances are inlined, so `outer` keeps its own instance.
    assert sorted(flat["top"].instances) == ["out1"]
    assert sorted(flat["outer"].instances) == ["c1.wg1", "c1.wg2"]


def test_flatten_netlists_keeps_the_placed_flavor() -> None:
    netlists = {"chain": _placed_chain(), "top": _placed_top()}
    flat = flatten_netlists(netlists)
    assert isinstance(flat["top"], PlacedNetlist)
    assert flat["top"].instances["c1.wg1"].placement.y == 60.0


def test_flatten_netlists_accepts_a_non_dict_mapping() -> None:
    from types import MappingProxyType

    flat = flatten_netlists(MappingProxyType(_nested()), instance_cell_maps=NESTED_MAPS)
    assert sorted(flat["top"].instances) == ["out1.c1.wg1", "out1.c1.wg2"]


def test_plain_flatten_on_a_placed_netlist_drops_placement() -> None:
    """The base implementation returns the plain flavor.

    It also cannot see ``PlacedInstance.cell`` (that lives on the subclass
    layer), so resolution has to be spelled out.
    """
    top = _placed_top()
    flat = Netlist.flatten(
        top, {"chain": _placed_chain()}, instance_cell_map={"c1": "chain"}
    )
    assert type(flat) is Netlist
    assert sorted(flat.instances) == ["c1.wg1"]
    assert not hasattr(flat, "placements")


def test_flatten_is_substitutable_on_the_subclass() -> None:
    """`PlacedNetlist.flatten` must accept everything the base accepts."""
    import inspect

    base = inspect.signature(Netlist.flatten)
    override = inspect.signature(PlacedNetlist.flatten)
    # Same names, kinds and defaults; only the return type narrows.
    assert base.parameters == override.parameters


def test_instance_cell_map_overrides_placed_instance_cell() -> None:
    chain = _placed_chain()
    top = PlacedNetlist()
    top.create_inst(
        "c1",
        kcl="P",
        component="chain",
        cell="stale_name",  # e.g. renamed cell, or a hand-built netlist
        placement=_placement(x=100.0),
    )
    port_in = top.create_port("in")
    top.create_net(port_in, PortRef(instance="c1", port="o1"))

    # `stale_name` is not in the mapping, so nothing resolves...
    assert sorted(top.flatten({"chain": chain}).instances) == ["c1"]
    # ...until the map says otherwise.
    flat = top.flatten({"chain": chain}, instance_cell_map={"c1": "chain"})
    assert sorted(flat.instances) == ["c1.wg1"]
    assert flat.instances["c1.wg1"].placement.x == 110.0
