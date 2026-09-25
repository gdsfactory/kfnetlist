"""A live Python hierarchy object with explicit document validation."""

import json
from collections.abc import Mapping

import pytest

from kfnetlist import (
    HierarchicalNetlist,
    Netlist,
    PortRef,
    flatten_netlists,
    validate_hierarchy,
)


def _document() -> dict[str, Netlist]:
    child = Netlist()
    child.create_inst("wg", "pdk", "straight")
    child.create_net(child.create_port("in"), PortRef("wg", "in"))
    child.create_net(PortRef("wg", "out"), child.create_port("out"))
    top = Netlist()
    top.create_inst("arm", "pdk", "make_arm", netlist_id="child")
    top.create_net(top.create_port("in"), PortRef("arm", "in"))
    top.create_net(PortRef("arm", "out"), top.create_port("out"))
    return {"top": top, "child": child}


def test_mapping_construction_and_live_child_edits() -> None:
    source = _document()
    doc = HierarchicalNetlist(source)
    assert list(doc) == ["top", "child"]
    assert doc["top"] is source["top"]
    assert doc.keys() == ["top", "child"]
    assert doc.items()[0][1] is source["top"]
    assert isinstance(doc, Mapping)
    assert doc.get("top") is source["top"]
    assert doc.get("missing") is None
    assert "top" in doc and len(doc) == 2
    doc["top"].create_inst("missing", "pdk", "make_other", netlist_id="other")
    with pytest.raises(ValueError, match="other.*does not exist"):
        doc.validate()
    with pytest.raises(ValueError, match="other.*does not exist"):
        doc.to_json()
    with pytest.raises(ValueError, match="other.*does not exist"):
        doc.flatten("top")
    doc["other"] = Netlist()
    doc.validate()
    validate_hierarchy(doc)
    assert list(doc) == ["top", "child", "other"]
    del doc["other"]
    with pytest.raises(ValueError, match="other.*does not exist"):
        doc.to_dict()
    with pytest.raises(KeyError):
        _ = doc["absent"]
    with pytest.raises(TypeError, match="plain Netlist"):
        doc["bad"] = {"instances": {}}


def test_json_dict_roundtrip_and_flatten() -> None:
    doc = HierarchicalNetlist(_document())
    wire = doc.to_dict()
    assert list(wire) == ["top", "child"]
    assert "arm" in wire["top"]["instances"]
    assert isinstance(HierarchicalNetlist.from_dict(wire)["top"], Netlist)
    restored = HierarchicalNetlist.from_json(doc.to_json())
    assert list(restored) == ["top", "child"]
    assert restored["top"] is not doc["top"]
    flat = restored.flatten("top")
    assert isinstance(flat, Netlist)
    assert list(flat.instances) == ["arm.wg"]
    assert list(restored["top"].flatten(restored).instances) == ["arm.wg"]
    assert list(flatten_netlists(restored)["top"].instances) == ["arm.wg"]
    all_flat = restored.flatten_all()
    assert list(all_flat) == ["top", "child"]
    assert list(all_flat["top"].instances) == ["arm.wg"]
    assert list(restored["top"].instances) == ["arm"]
    with pytest.raises(ValueError, match="Unknown netlist"):
        restored.flatten("absent")
    with pytest.raises(ValueError, match="does not exist"):
        HierarchicalNetlist.from_json(json.dumps({"top": wire["top"]}))


def test_constructor_rejects_invalid_documents() -> None:
    source = _document()
    with pytest.raises(ValueError, match="does not exist"):
        HierarchicalNetlist({"top": source["top"]})
    with pytest.raises(ValueError, match="does not exist"):
        HierarchicalNetlist.from_dict({"top": source["top"].to_dict()})
    with pytest.raises(TypeError, match="plain Netlist"):
        HierarchicalNetlist({"top": 2})
    source["child"].create_inst("cycle", "pdk", "top", netlist_id="top")
    with pytest.raises(ValueError, match="cyclic"):
        HierarchicalNetlist(source)


def test_pydantic_accepts_and_serializes_hierarchy() -> None:
    pydantic = pytest.importorskip("pydantic")
    doc = HierarchicalNetlist(_document())
    adapter = pydantic.TypeAdapter(HierarchicalNetlist)
    assert adapter.validate_python(doc) is doc
    loaded = adapter.validate_python(doc.to_dict())
    assert isinstance(loaded, HierarchicalNetlist)
    assert adapter.dump_python(loaded) == doc.to_dict()
