"""Tests for the placement-aware netlist flavor.

Covers the Rust ``Placement`` / ``PlacedInstance`` / ``PlacedNetlist`` types
and the ``_placement_for`` extraction helper. The end-to-end ``extract(...,
include_placement=True)`` path needs a kfactory-shaped cell hierarchy (as the
other extraction code does) and is exercised via the helper here.
"""

from __future__ import annotations

import types

import pytest
from kfnetlist import (
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    Placement,
    PlacedInstance,
    PlacedNetlist,
    PortRef,
)

BBOX = {"left": 0.0, "bottom": 0.0, "right": 10.0, "top": 5.0}


def _placement() -> Placement:
    return Placement(x=1.0, y=2.0, orientation=90.0, mirror=False, bbox=dict(BBOX))


# --- Placement (purely geometric, no cell name) ----------------------------


def test_placement_fields_and_bbox_is_dict() -> None:
    p = _placement()
    assert (p.x, p.y, p.orientation, p.mirror) == (1.0, 2.0, 90.0, False)
    assert isinstance(p.bbox, dict)
    assert p.bbox == BBOX
    # The cell name is an instance property, not a placement one.
    assert not hasattr(p, "cell")


def test_placement_equality() -> None:
    assert _placement() == _placement()
    other = Placement(x=9.0, y=2.0, orientation=90.0, mirror=False, bbox=dict(BBOX))
    assert _placement() != other


def test_placement_round_trip_json_and_dict() -> None:
    p = _placement()
    assert Placement.from_json(p.to_json()) == p
    d = p.to_dict()
    assert d["bbox"] == BBOX
    assert "cell" not in d
    assert Placement.from_dict(d) == p


def test_placement_bbox_setter() -> None:
    p = _placement()
    p.bbox = {"left": -1.0, "bottom": -2.0, "right": 3.0, "top": 4.0}
    assert p.bbox["left"] == -1.0


# --- PlacedInstance (carries the cell name) --------------------------------


def test_placed_instance_is_netlist_instance() -> None:
    pi = PlacedInstance(
        kcl="PDK",
        component="straight_factory",
        settings={"width": 0.5},
        name="wg1",
        cell="straight",
        placement=_placement(),
    )
    assert isinstance(pi, NetlistInstance)
    assert (pi.kcl, pi.component, pi.name) == ("PDK", "straight_factory", "wg1")
    # cell (layout cell name) is distinct from component (factory name).
    assert pi.cell == "straight"
    assert pi.settings == {"width": 0.5}
    assert pi.placement == _placement()


def test_placed_instance_array() -> None:
    pi = PlacedInstance(
        kcl="PDK",
        component="c",
        array=NetlistArray(na=2, nb=3),
        cell="straight",
        placement=_placement(),
    )
    assert pi.array == NetlistArray(na=2, nb=3)


def test_placed_instance_round_trip() -> None:
    pi = PlacedInstance(
        kcl="PDK",
        component="straight_factory",
        settings={"width": 0.5},
        name="wg1",
        cell="straight",
        placement=_placement(),
    )
    pi_json = PlacedInstance.from_json(pi.to_json(), name="wg1")
    assert pi_json.placement == pi.placement
    assert (pi_json.cell, pi_json.kcl, pi_json.name) == ("straight", "PDK", "wg1")

    d = pi.to_dict()
    assert d["cell"] == "straight"
    assert d["placement"]["bbox"] == BBOX and "cell" not in d["placement"]
    pi_dict = PlacedInstance.from_dict(d, name="wg1")
    assert pi_dict.placement == pi.placement and pi_dict.cell == "straight"


# --- PlacedNetlist ---------------------------------------------------------


def test_placed_netlist_is_netlist() -> None:
    assert isinstance(PlacedNetlist(), Netlist)


def test_placed_netlist_create_inst_and_connectivity() -> None:
    pnl = PlacedNetlist()
    pnl.create_inst(
        name="wg1",
        kcl="PDK",
        component="straight_factory",
        settings={"width": 0.5},
        cell="straight",
        placement=_placement(),
    )
    pnl.create_port("o1")
    # Inherited connectivity machinery still validates against base storage.
    pnl.create_net(NetlistPort(name="o1"), PortRef(instance="wg1", port="o2"))

    inst = pnl.instances["wg1"]
    assert isinstance(inst, PlacedInstance)
    assert inst.cell == "straight"
    assert inst.placement == _placement()
    assert pnl.placements["wg1"] == _placement()
    assert len(pnl.nets) == 1


def test_placed_netlist_create_net_unknown_instance_raises() -> None:
    pnl = PlacedNetlist()
    with pytest.raises(ValueError):
        pnl.create_net(PortRef(instance="missing", port="o1"))


def test_placed_netlist_round_trip_json_and_dict() -> None:
    pnl = PlacedNetlist()
    pnl.create_inst(
        name="wg1", kcl="PDK", component="c", cell="straight", placement=_placement()
    )
    pnl.create_port("o1")
    pnl.create_net(NetlistPort(name="o1"), PortRef(instance="wg1", port="o2"))

    pnl_json = PlacedNetlist.from_json(pnl.to_json())
    assert pnl_json.instances["wg1"].placement == _placement()
    assert pnl_json.instances["wg1"].cell == "straight"
    assert [n for n in pnl_json.nets] == [n for n in pnl.nets]

    pnl_dict = PlacedNetlist.from_dict(pnl.to_dict())
    assert pnl_dict.placements["wg1"] == _placement()


def test_from_netlist_upgrades_plain_netlist() -> None:
    nl = Netlist()
    nl.create_inst(name="wg1", kcl="PDK", component="c", settings={"width": 0.5})
    nl.create_inst(name="wg2", kcl="PDK", component="c")
    nl.create_port("o1")
    nl.create_net(NetlistPort(name="o1"), PortRef(instance="wg1", port="o2"))

    pnl = PlacedNetlist.from_netlist(nl, {"wg1": _placement()}, {"wg1": "straight"})
    assert isinstance(pnl, PlacedNetlist)
    # Connectivity is preserved verbatim.
    assert [n for n in pnl.nets] == [n for n in nl.nets]
    assert pnl.instances["wg1"].placement == _placement()
    assert pnl.instances["wg1"].cell == "straight"
    # Instances without supplied placement/cell get empty defaults.
    assert pnl.instances["wg2"].cell == ""
    zero_bbox = {"left": 0.0, "bottom": 0.0, "right": 0.0, "top": 0.0}
    assert pnl.instances["wg2"].placement == Placement(
        x=0.0, y=0.0, orientation=0.0, mirror=False, bbox=zero_bbox
    )
    assert "wg2" not in pnl.placements


def test_from_netlist_drops_entries_for_absent_instance() -> None:
    nl = Netlist()
    nl.create_inst(name="wg1", kcl="PDK", component="c")
    pnl = PlacedNetlist.from_netlist(
        nl,
        {"wg1": _placement(), "ghost": _placement()},
        {"wg1": "straight", "ghost": "straight"},
    )
    assert set(pnl.placements) == {"wg1"}


def test_flatten_instances_drops_placement() -> None:
    pnl = PlacedNetlist()
    pnl.create_inst(name="a", kcl="p", component="c", cell="a", placement=_placement())
    pnl.create_inst(
        name="flat", kcl="p", component="c", cell="flat", placement=_placement()
    )
    pnl.create_inst(name="b", kcl="p", component="c", cell="b", placement=_placement())
    pnl.create_net(
        PortRef(instance="a", port="o1"), PortRef(instance="flat", port="o1")
    )
    pnl.create_net(
        PortRef(instance="flat", port="o2"), PortRef(instance="b", port="o1")
    )

    pnl.flatten_instances(["flat"])
    assert not pnl.has_instance("flat")
    assert "flat" not in pnl.placements
    assert set(pnl.placements) == {"a", "b"}


# --- backward compatibility ------------------------------------------------


def test_plain_netlist_serialization_unchanged() -> None:
    nl = Netlist()
    nl.create_inst(name="wg1", kcl="PDK", component="straight", settings={"width": 1})
    d = nl.to_dict()
    # No placement/cell leaks into the plain wire format.
    assert "placement" not in d["instances"]["wg1"]
    assert "cell" not in d["instances"]["wg1"]


# --- extraction helper -----------------------------------------------------


def test_placement_for_reads_transform_and_bbox() -> None:
    from kfnetlist.extract._algo import _placement_for
    from klayout import db as kdb

    bbox = types.SimpleNamespace(left=-1.0, bottom=-2.0, right=3.0, top=4.0)
    inst = types.SimpleNamespace(
        name="wg1",
        cell=types.SimpleNamespace(name="straight"),
        dcplx_trans=kdb.DCplxTrans(1.0, 90.0, False, 1.5, 2.5),
        instance=types.SimpleNamespace(dbbox=lambda: bbox),
    )

    p = _placement_for(inst)
    # The helper builds geometry only; the cell name is captured separately.
    assert (p.x, p.y) == (1.5, 2.5)
    assert p.orientation == 90.0
    assert p.mirror is False
    assert p.bbox == {"left": -1.0, "bottom": -2.0, "right": 3.0, "top": 4.0}
