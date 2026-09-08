"""Compatibility at the boundary between core values and Python classes."""

from __future__ import annotations

import json

import pytest
from kfnetlist import (
    Net,
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    Placement,
    PlacedInstance,
    PlacedNetlist,
    PortArrayRef,
    PortRef,
)


def test_array_reference_inherited_mutation_reaches_serialization_and_nets() -> None:
    ref = PortArrayRef("old", "old", 0, 0)
    ref.instance = "new"
    ref.port = "p"
    ref.ia = 2
    ref.ib = 3
    expected = {"instance": "new", "port": "p", "ia": 2, "ib": 3}
    assert isinstance(ref, PortRef)
    assert ref.name == "p"
    assert ref.to_dict() == expected
    assert json.loads(ref.to_json()) == expected
    assert Net([ref])[0] == ref


def test_placed_instance_mutable_fields_and_inherited_normalization() -> None:
    instance = PlacedInstance("old", "old")
    instance.kcl = "pdk"
    instance.component = "cell"
    instance.name = "unit"
    instance.cell = "placed_cell"
    instance.settings = {"nested": [1.0, 1.5]}
    array = NetlistArray(1, 1)
    array.na = 2
    array.nb = 3
    instance.array = array
    placement = Placement(0, 0, 0, False, dict(left=0, bottom=0, right=1, top=1))
    placement.x, placement.y = 4, 5
    placement.orientation, placement.mirror = 90, True
    instance.placement = placement
    instance.normalize()
    restored = PlacedInstance.from_json(instance.to_json(), name="unit")
    assert isinstance(restored, NetlistInstance)
    assert restored == instance
    assert restored.array == NetlistArray(2, 3)
    assert restored.placement == placement
    assert restored.cell == "placed_cell"
    assert type(restored.settings["nested"][0]) is int
    # Historical equality compares inherited connectivity only.
    restored.cell = "different"
    restored.placement = Placement(9, 9, 0, False, placement.bbox)
    assert restored == instance


@pytest.mark.parametrize("netlist_type", [Netlist, PlacedNetlist])
def test_netlist_snapshots_are_independent(netlist_type: type[Netlist]) -> None:
    nl = netlist_type()
    created = nl.create_inst("unit", "pdk", "cell", settings={"nested": [1]})
    top = nl.create_port("in")
    nl.create_net(top, PortRef("unit", "p"))
    before = nl.to_json()
    created.component = "changed"
    instances = nl.instances
    instances["unit"].settings = {"changed": True}
    instances.clear()
    nl.get_instance("unit").name = "changed"
    nl.ports[0].name = "changed"
    nl.nets[0].append(PortRef("unit", "extra"))
    if isinstance(nl, PlacedNetlist):
        nl.instances["unit"].cell = "changed"
        nl.placements["unit"].x = 9
    assert nl.to_json() == before


def test_placed_failed_creation_restores_both_layers() -> None:
    nl = PlacedNetlist()
    nl.create_inst("unit", "pdk", "cell", cell="placed_cell")
    nl.create_port("in")
    nl.create_net(NetlistPort("in"), PortRef("unit", "p"))
    before = nl.to_json()
    with pytest.raises(ValueError, match="must be >= 1"):
        nl.create_inst("unit", "pdk", "replacement", na=-1, nb=1, cell="changed")
    assert nl.to_json() == before
    nl.flatten_instances(["unit"])
    assert nl.instance_names() == []
    assert nl.placements == {}
    assert nl.nets == [Net([NetlistPort("in")])]


def test_core_errors_keep_python_exception_types_and_messages() -> None:
    nl = Netlist()
    with pytest.raises(KeyError) as lookup:
        nl.get_instance("absent")
    assert lookup.value.args == ("absent",)
    with pytest.raises(ValueError, match="^Unknown instance absent$"):
        nl.create_net(PortRef("absent", "p"))
    with pytest.raises(ValueError, match="^create_net expects"):
        nl.create_net(object())  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="^expected NetlistPort"):
        Net([object()])  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="^deserialize:"):
        Netlist.from_json("invalid")
    nl.create_inst("unit", "pdk", "cell", na=0, nb=0)
    with pytest.raises(ValueError) as array:
        nl.create_net(PortArrayRef("unit", "p", 0, 0))
    assert str(array.value) == (
        "Instance unit is not an array instance. But an array portref was requested "
        'PortArrayRefData { instance: "unit", port: "p", ia: 0, ib: 0 }'
    )


def test_placed_normalization_still_returns_plain_connectivity() -> None:
    nl = PlacedNetlist()
    nl.create_inst("unit", "pdk", "cell", cell="placed", settings={"width": 1.0})
    normalized = nl.normalize()
    assert type(normalized) is Netlist
    assert type(normalized.instances["unit"]) is NetlistInstance
    assert normalized.instances["unit"].settings == {"width": 1}
    assert nl.instances["unit"].cell == "placed"


@pytest.mark.parametrize(
    "value",
    [
        NetlistPort("p"),
        PortRef("unit", "p"),
        PortArrayRef("unit", "p", 0, 1),
        NetlistArray(2, 3),
        NetlistInstance("pdk", "cell"),
        Net([PortRef("unit", "p")]),
        Netlist(),
        Placement(1, 2, 90, False, dict(left=0, bottom=0, right=1, top=1)),
        PlacedInstance("pdk", "cell", cell="placed"),
        PlacedNetlist(),
    ],
)
def test_pydantic_accepts_instances_and_wire_values(value: object) -> None:
    pydantic = pytest.importorskip("pydantic")
    adapter = pydantic.TypeAdapter(type(value))
    assert adapter.validate_python(value) is value
    wire = value.to_dict()  # type: ignore[attr-defined]
    if isinstance(value, Net):
        # The existing generic schema accepts dicts and instances, not net lists.
        with pytest.raises(pydantic.ValidationError):
            adapter.validate_python(wire)
        assert json.loads(adapter.dump_json(value)) == wire
        return
    restored = adapter.validate_python(wire)
    assert type(restored) is type(value)
    assert restored.to_dict() == wire
    assert json.loads(adapter.dump_json(restored)) == wire
    with pytest.raises(pydantic.ValidationError):
        adapter.validate_python(42)
