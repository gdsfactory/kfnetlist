"""Omitted library identities keep hand-authored netlists concise."""

import pytest
from kfnetlist import (
    LeafNetlistInstance,
    Netlist,
    NetlistInstance,
    PlacedInstance,
    PlacedNetlist,
    RefNetlistInstance,
)


def test_from_dict_defaults_kcl_and_omits_empty_value_on_output() -> None:
    data = {
        "instances": {
            "a": {"component": "coupler"},
            "b": {"component": "coupler", "kcl": "PDK"},
            "child": {"component": "arm", "netlist_id": "arm_10"},
        },
        "nets": [],
        "ports": [],
    }
    netlist = Netlist.from_dict(data)
    assert netlist.instances["a"].kcl == ""
    assert netlist.instances["child"].netlist_id == "arm_10"
    assert netlist.instances["b"].kcl == "PDK"
    dumped = netlist.to_dict()["instances"]
    assert "kcl" not in dumped["a"]
    assert "kcl" not in dumped["child"]
    assert dumped["b"]["kcl"] == "PDK"
    assert Netlist.from_json(netlist.to_json()).to_dict() == netlist.to_dict()


@pytest.mark.parametrize(
    "factory,kwargs",
    [
        (NetlistInstance, {}),
        (LeafNetlistInstance, {}),
        (RefNetlistInstance, {"netlist_id": "child"}),
        (PlacedInstance, {}),
    ],
)
def test_instance_constructors_accept_component_without_kcl(factory, kwargs) -> None:
    instance = factory(component="coupler", **kwargs)
    assert instance.kcl == ""
    assert "kcl" not in instance.to_dict()
    assert factory("PDK", "coupler", **kwargs).kcl == "PDK"
    with pytest.raises(TypeError, match="component"):
        factory(**kwargs)


@pytest.mark.parametrize("factory", [Netlist, PlacedNetlist])
def test_netlist_create_inst_accepts_component_without_kcl(factory) -> None:
    netlist = factory()
    instance = netlist.create_inst("a", component="coupler")
    assert instance.kcl == ""
    assert "kcl" not in netlist.to_dict()["instances"]["a"]
    assert netlist.create_inst("b", "PDK", "coupler").kcl == "PDK"
    assert factory.from_dict(netlist.to_dict()).instances["a"].kcl == ""
    with pytest.raises(TypeError, match="component"):
        netlist.create_inst("missing")
