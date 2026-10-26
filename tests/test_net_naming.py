"""Native optional net names: wire format, identity, and merge policy."""

from __future__ import annotations

import json

import pytest

from kfnetlist import Net, Netlist, NetlistPort, PortRef

# Captured from `Netlist.to_json()` on the base commit, before nets could carry
# a name: an all-unnamed netlist must still serialize to exactly this.
GOLDEN_UNNAMED_NETLIST = (
    '{"instances":{"R1":{"array":{"na":1,"nb":1},"component":"res","kcl":"pdk",'
    '"settings":{}},"R2":{"array":{"na":1,"nb":1},"component":"res","kcl":"pdk",'
    '"settings":{}}},"nets":[[{"name":"in"},{"instance":"R1","port":"p"}],'
    '[{"instance":"R1","port":"n"},{"instance":"R2","port":"p"}]],'
    '"ports":[{"name":"in"},{"name":"out"}]}'
)


def _netlist(*, named: bool) -> Netlist:
    nl = Netlist()
    nl.create_port("in")
    nl.create_port("out")
    nl.create_inst("R1", kcl="pdk", component="res")
    nl.create_inst("R2", kcl="pdk", component="res")
    if named:
        nl.create_net(NetlistPort("in"), PortRef("R1", "p"), name="in")
    else:
        nl.create_net(NetlistPort("in"), PortRef("R1", "p"))
    nl.create_net(PortRef("R1", "n"), PortRef("R2", "p"))
    return nl


def test_unnamed_net_serializes_as_a_bare_array() -> None:
    net = Net([PortRef("R1", "p")])
    assert net.name is None
    assert net.to_json() == '[{"instance":"R1","port":"p"}]'
    assert net.to_dict() == [{"instance": "R1", "port": "p"}]
    assert repr(net) == "Net([PortRef(instance='R1', port='p')])"


def test_named_net_serializes_as_an_object_and_round_trips() -> None:
    net = Net([PortRef("R1", "p")], name="GND")
    assert net.name == "GND"
    assert json.loads(net.to_json()) == {
        "name": "GND",
        "members": [{"instance": "R1", "port": "p"}],
    }
    assert Net.from_json(net.to_json()).name == "GND"
    assert Net.from_json(net.to_json()) == net
    assert Net.from_dict(net.to_dict()).name == "GND"


def test_reading_accepts_both_shapes() -> None:
    plain = Net.from_json('[{"name":"in"}]')
    assert plain.name is None
    assert plain == Net([NetlistPort("in")])

    named = Net.from_json('{"name":"GND","members":[{"name":"in"}]}')
    assert named.name == "GND"
    # A name is not part of identity.
    assert named == Net([NetlistPort("in")])

    assert Net.from_json('{"members":[]}') == Net()
    assert Net.from_json('{"name":null,"members":[]}') == Net()
    assert Net.from_json('{"name":"floating","members":[]}').to_json() == (
        '{"name":"floating","members":[]}'
    )


def test_netlist_round_trip_keeps_names_and_leaves_unnamed_nets_unchanged() -> None:
    nl = _netlist(named=True)
    document = json.loads(nl.to_json())
    assert document["nets"][0] == {
        "name": "in",
        "members": [{"name": "in"}, {"instance": "R1", "port": "p"}],
    }
    assert document["nets"][1] == [
        {"instance": "R1", "port": "n"},
        {"instance": "R2", "port": "p"},
    ]

    back = Netlist.from_json(nl.to_json())
    assert [net.name for net in back.nets] == ["in", None]
    assert back == nl
    # The unnamed net's JSON is still exactly its member list.
    assert back.nets[1].to_json() == Net(back.nets[1].members()).to_json()

    # An all-unnamed netlist is byte-identical to the pre-name output.
    assert _netlist(named=False).to_json() == GOLDEN_UNNAMED_NETLIST


def test_add_net_keeps_the_name() -> None:
    nl = _netlist(named=True)
    copy = Netlist()
    copy.create_port("in")
    copy.create_inst("R1", kcl="pdk", component="res")
    copy.add_net(nl.nets[0])
    assert copy.nets[0].name == "in"


def test_removing_an_instance_keeps_the_lowest_indexed_name() -> None:
    def touching() -> Netlist:
        nl = Netlist()
        for name in ["a", "mid", "b"]:
            nl.create_inst(name, kcl="pdk", component="leaf")
        return nl

    # Both contributing nets named differently: the lower index wins.
    nl = touching()
    nl.create_net(PortRef("a", "p"), PortRef("mid", "in"), name="first")
    nl.create_net(PortRef("mid", "out"), PortRef("b", "p"), name="second")
    nl.remove_instances(["mid"])
    assert len(nl.nets) == 1
    assert nl.nets[0].name == "first"
    assert len(nl.nets[0]) == 2

    # Only the higher-indexed net is named: the merged net takes that name.
    nl = touching()
    nl.create_net(PortRef("a", "p"), PortRef("mid", "in"))
    nl.create_net(PortRef("mid", "out"), PortRef("b", "p"), name="second")
    nl.remove_instances(["mid"])
    assert nl.nets[0].name == "second"

    # Neither named: the merged net stays unnamed.
    nl = touching()
    nl.create_net(PortRef("a", "p"), PortRef("mid", "in"))
    nl.create_net(PortRef("mid", "out"), PortRef("b", "p"))
    nl.remove_instances(["mid"])
    assert nl.nets[0].name is None


def test_names_are_not_identity() -> None:
    a = Net([PortRef("R1", "p")], name="A")
    b = Net([PortRef("R1", "p")], name="B")
    unnamed = Net([PortRef("R1", "p")])

    assert a == b
    assert a == unnamed
    assert hash(a) == hash(b)
    assert len({a, b, unnamed}) == 1
    assert named_netlist("A") == named_netlist("B")


def named_netlist(name: str) -> Netlist:
    nl = Netlist()
    nl.create_inst("R1", kcl="pdk", component="res")
    nl.create_net(PortRef("R1", "p"), name=name)
    return nl


def test_name_is_keyword_only_and_mutable() -> None:
    with pytest.raises(TypeError):
        Net([PortRef("R1", "p")], "GND")  # ty: ignore[too-many-positional-arguments]

    net = Net([PortRef("R1", "p")])
    net.name = "GND"
    assert net.name == "GND"
    assert json.loads(net.to_json())["name"] == "GND"
    net.name = None
    assert net.to_json() == '[{"instance":"R1","port":"p"}]'
