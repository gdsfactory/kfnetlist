"""Explicit references survive interchange without placement or side maps."""

import json

import pytest

from kfnetlist import (
    LeafNetlistInstance,
    Netlist,
    NetlistInstance,
    PlacedInstance,
    PlacedNetlist,
    PortRef,
    RefNetlistInstance,
    hierarchy_from_json,
    validate_hierarchy,
)


def _document():
    arm = Netlist()
    arm.create_inst("wg", "pdk", "straight", {"length": 10})
    arm.create_net(arm.create_port("in"), PortRef("wg", "in"))
    arm.create_net(PortRef("wg", "out"), arm.create_port("out"))
    top = Netlist()
    top.create_inst("left", "pdk", "make_arm", {"length": 10.0}, netlist_id="arm_10")
    top.create_inst("right", "pdk", "make_arm", {"length": 10}, netlist_id="arm_10")
    top.create_net(top.create_port("in"), PortRef("left", "in"))
    top.create_net(PortRef("left", "out"), PortRef("right", "in"))
    top.create_net(PortRef("right", "out"), top.create_port("out"))
    return {"top": top, "arm_10": arm}


def test_legacy_and_explicit_construction():
    legacy = NetlistInstance("pdk", "straight", {"length": 10})
    assert isinstance(legacy, LeafNetlistInstance)
    assert isinstance(legacy, NetlistInstance)
    assert not hasattr(legacy, "netlist_id")
    assert legacy.to_dict() == {
        "kcl": "pdk",
        "component": "straight",
        "settings": {"length": 10},
    }
    explicit = RefNetlistInstance("pdk", "make_arm", netlist_id="arm_10")
    assert isinstance(explicit, NetlistInstance)
    assert not isinstance(explicit, LeafNetlistInstance)
    assert explicit.netlist_id == "arm_10"
    with pytest.raises(TypeError):
        RefNetlistInstance("pdk", "make_arm")  # ty: ignore[missing-argument]
    with pytest.raises(TypeError):
        RefNetlistInstance("pdk", "make_arm", netlist_id=None)  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize(
    "cls", [NetlistInstance, LeafNetlistInstance, RefNetlistInstance]
)
def test_variant_json_and_dict(cls):
    kwargs = {"netlist_id": "arm_10"} if cls is RefNetlistInstance else {}
    instance = cls("pdk", "make_arm", name="a", info={"nested": [1]}, **kwargs)
    for method, data in [
        (cls.from_json, instance.to_json()),
        (cls.from_dict, instance.to_dict()),
    ]:
        restored = method(data, name="a")
        assert type(restored) is type(instance)
        assert restored == instance


@pytest.mark.parametrize(
    "cls", [NetlistInstance, LeafNetlistInstance, RefNetlistInstance]
)
def test_variant_pydantic(cls):
    pydantic = pytest.importorskip("pydantic")
    kwargs = {"netlist_id": "arm_10"} if cls is RefNetlistInstance else {}
    instance = cls("pdk", "make_arm", name="a", info={"nested": [1]}, **kwargs)
    parsed = pydantic.TypeAdapter(cls).validate_python(instance.to_dict())
    assert type(parsed) is type(instance)
    assert pydantic.TypeAdapter(cls).dump_python(parsed) == instance.to_dict()


@pytest.mark.parametrize("value", [None, 12, True, [], {}])
def test_invalid_reference_never_falls_back_to_leaf(value):
    wire = {"kcl": "pdk", "component": "arm", "netlist_id": value}
    with pytest.raises(ValueError):
        NetlistInstance.from_dict(wire)
    with pytest.raises(ValueError):
        NetlistInstance.from_json(json.dumps(wire))


def test_explicit_loaders_reject_wrong_variant_and_unknown_fields():
    leaf = {"kcl": "pdk", "component": "arm"}
    with pytest.raises(ValueError):
        RefNetlistInstance.from_dict(leaf)
    with pytest.raises(ValueError):
        LeafNetlistInstance.from_dict(leaf | {"netlist_id": "arm_10"})
    with pytest.raises(ValueError):
        NetlistInstance.from_dict(leaf | {"netlist_id": "arm_10", "typo": 1})


def test_hierarchy_roundtrip_shared_child_normalization_and_snapshots():
    doc = _document()
    validate_hierarchy(doc)
    encoded = json.dumps({key: nl.to_dict() for key, nl in doc.items()})
    restored = hierarchy_from_json(encoded)
    assert restored == doc
    for name in ["left", "right"]:
        instance = restored["top"].get_instance(name)
        assert isinstance(instance, RefNetlistInstance)
        assert instance.name == name
        assert instance.netlist_id == "arm_10"
    restored["top"].instances["left"].settings = {"length": 99}
    assert restored["top"].instances["left"].settings == {"length": 10}
    normalized = restored["top"].normalize()
    assert isinstance(normalized.instances["left"], RefNetlistInstance)
    assert normalized.instances["left"].netlist_id == "arm_10"
    assert type(normalized.instances["left"].settings["length"]) is int


def test_equality_includes_variant_and_reference():
    leaf = NetlistInstance("pdk", "arm")
    ref_a = RefNetlistInstance("pdk", "arm", netlist_id="a")
    ref_b = RefNetlistInstance("pdk", "arm", netlist_id="b")
    assert leaf != ref_a and ref_a != ref_b

    def make(inst):
        return Netlist.from_dict({"instances": {"i": inst.to_dict()}})

    assert make(leaf) != make(ref_a)
    assert make(ref_a) != make(ref_b)


def test_missing_target_and_cycles_fail_at_document_boundary():
    doc = _document()
    with pytest.raises(ValueError, match="arm_10.*does not exist"):
        validate_hierarchy({"top": doc["top"]})
    doc["arm_10"].create_inst("loop", "pdk", "top", netlist_id="top")
    with pytest.raises(ValueError, match="cyclic"):
        validate_hierarchy(doc)
    with pytest.raises(ValueError, match="cyclic"):
        hierarchy_from_json(
            json.dumps({name: nl.to_dict() for name, nl in doc.items()})
        )


def test_flatten_uses_references_and_preserves_connectivity():
    doc = _document()
    flat = doc["top"].flatten(doc)
    assert list(flat.instances) == ["left.wg", "right.wg"]
    assert all(isinstance(i, LeafNetlistInstance) for i in flat.instances.values())
    members = [
        [(p.instance, p.port) if isinstance(p, PortRef) else p.name for p in n]
        for n in flat.nets
    ]
    assert any(set(net) == {("left.wg", "out"), ("right.wg", "in")} for net in members)
    assert any(set(net) == {"in", ("left.wg", "in")} for net in members)
    assert any(set(net) == {"out", ("right.wg", "out")} for net in members)
    kept = doc["top"].flatten(doc, exclude=["arm_10"])
    assert isinstance(kept.instances["left"], RefNetlistInstance)
    assert kept.normalize() == doc["top"].normalize()
    with pytest.raises(ValueError, match="conflicts"):
        doc["top"].flatten(doc, instance_cell_map={"left": "another"})
    with pytest.raises(ValueError, match="does not exist"):
        doc["top"].flatten({})


def test_nested_references_flatten_without_side_maps():
    doc = _document()
    root = Netlist()
    root.create_inst("nested", "pdk", "make_top", netlist_id="top")
    doc["root"] = root
    flat = root.flatten(doc)
    assert set(flat.instances) == {"nested.left.wg", "nested.right.wg"}


def test_placed_conversion_preserves_logical_reference_separate_from_cell():
    doc = _document()
    placed = PlacedNetlist.from_netlist(doc["top"], cells={"left": "layout_name"})
    assert isinstance(placed.instances["left"], PlacedInstance)
    assert placed.instances["left"].netlist_id == "arm_10"
    assert placed.instances["left"].cell == "layout_name"
    restored = PlacedNetlist.from_json(placed.to_json())
    assert restored.instances["left"].netlist_id == "arm_10"
    assert restored.instances["left"].cell == "layout_name"
    assert set(restored.flatten(doc).instances) == {"left.wg", "right.wg"}
    instance = restored.instances["left"]
    assert PlacedInstance.from_dict(instance.to_dict()).netlist_id == "arm_10"
    with pytest.raises(ValueError):
        PlacedInstance.from_dict(instance.to_dict() | {"netlist_id": None})


@pytest.mark.parametrize("empty_child", [False, True])
def test_full_flatten_does_not_silently_return_unexpanded_references(empty_child):
    doc = _document()
    if empty_child:
        doc["arm_10"] = Netlist()
    else:
        doc["top"].create_inst(
            "array", "pdk", "make_arm", na=2, nb=3, netlist_id="arm_10"
        )
    with pytest.raises(ValueError, match="cannot fully flatten"):
        doc["top"].flatten(doc)
    retained = doc["top"].flatten(doc, exclude=["arm_10"])
    assert all(
        isinstance(inst, RefNetlistInstance) for inst in retained.instances.values()
    )


@pytest.mark.parametrize("cls", [Netlist, PlacedNetlist])
def test_create_inst_reference_keyword_is_supported_by_both_netlist_types(cls):
    netlist = cls()
    leaf = netlist.create_inst("unit", "pdk", "arm")
    assert "netlist_id" not in leaf.to_dict()
    created = netlist.create_inst("unit", "pdk", "arm", netlist_id="arm_10")
    assert created.netlist_id == "arm_10"
    assert netlist.instances["unit"].netlist_id == "arm_10"
    assert cls.from_json(netlist.to_json()).instances["unit"].netlist_id == "arm_10"
    before = netlist.to_dict()
    with pytest.raises(ValueError):
        netlist.create_inst("unit", "pdk", "arm", na=-1, netlist_id="other")
    assert netlist.to_dict() == before


def test_old_ref_spelling_is_rejected():
    instance = RefNetlistInstance("pdk", "make_arm", netlist_id="arm_10")
    assert "netlist_id" in instance.to_dict()
    assert "ref" not in instance.to_dict()
    assert not hasattr(instance, "ref")
    with pytest.raises(ValueError):
        NetlistInstance.from_dict(
            {"kcl": "pdk", "component": "make_arm", "ref": "arm_10"}
        )
    with pytest.raises(TypeError):
        RefNetlistInstance("pdk", "make_arm", ref="arm_10")  # ty: ignore[missing-argument, unknown-argument]
