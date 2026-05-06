from __future__ import annotations

import pytest
from kfnetlist import (
    Net,
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    PortArrayRef,
    PortRef,
)


def test_portref_hash_equality() -> None:
    a = PortRef(instance="i", port="p")
    b = PortRef(instance="i", port="p")
    c = PortRef(instance="i", port="q")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    assert hash(a) != hash(c)


def test_portarrayref_hash_equality() -> None:
    a = PortArrayRef(instance="i", port="p", ia=0, ib=1)
    b = PortArrayRef(instance="i", port="p", ia=0, ib=1)
    c = PortArrayRef(instance="i", port="p", ia=1, ib=1)
    d = PortRef(instance="i", port="p")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    # Sibling types are never equal even with matching shared fields.
    assert a != d


def test_portref_ordering() -> None:
    pr = PortRef(instance="i", port="p")
    par = PortArrayRef(instance="i", port="p", ia=0, ib=0)
    np_ = NetlistPort(name="x")
    assert pr < par
    assert (par < pr) is False
    assert (pr < np_) is False
    assert (par < np_) is False


def test_netlistport_ordering() -> None:
    a = NetlistPort(name="a")
    b = NetlistPort(name="b")
    pr = PortRef(instance="i", port="p")
    assert a < b
    assert (b < a) is False
    assert a < pr  # NetlistPort < PortRef


def test_netlistport_hash() -> None:
    a = NetlistPort(name="x")
    b = NetlistPort(name="x")
    assert hash(a) == hash(b)


def test_net_sorts_on_construction() -> None:
    np_ = NetlistPort(name="z")
    pr = PortRef(instance="i", port="p")
    par = PortArrayRef(instance="i", port="p", ia=0, ib=0)
    n = Net([par, np_, pr])
    assert isinstance(n[0], NetlistPort)
    assert isinstance(n[1], PortRef) and not isinstance(n[1], PortArrayRef)
    assert isinstance(n[2], PortArrayRef)
    assert len(n) == 3


def test_net_iter_and_membership() -> None:
    pr = PortRef(instance="i", port="p")
    n = Net([pr])
    items = list(n)
    assert len(items) == 1
    assert items[0] == pr
    assert pr in n
    assert PortRef(instance="i", port="q") not in n


def test_netlist_create_inst_array_validation() -> None:
    nl = Netlist()
    inst = nl.create_inst(
        name="inst1", kcl="pdk", component="comp", settings={}, na=2, nb=3
    )
    assert isinstance(inst.array, NetlistArray)
    assert inst.array.na == 2
    assert inst.array.nb == 3


def test_netlist_create_inst_invalid_array() -> None:
    nl = Netlist()
    with pytest.raises(ValueError):
        nl.create_inst(
            name="inst1", kcl="pdk", component="comp", settings={}, na=-1, nb=2
        )


def test_netlist_create_net_unknown_instance_raises() -> None:
    nl = Netlist()
    pr = PortRef(instance="missing", port="o1")
    with pytest.raises(ValueError):
        nl.create_net(pr)


def test_netlist_create_net_unknown_top_port_raises() -> None:
    nl = Netlist()
    np_ = NetlistPort(name="o1")
    with pytest.raises(ValueError):
        nl.create_net(np_)


def test_netlist_create_net_with_top_port() -> None:
    nl = Netlist()
    nl.create_port("o1")
    nl.create_net(NetlistPort(name="o1"))
    assert len(nl.nets) == 1


def test_netlist_create_net_with_array_portref_collapses_when_1_1() -> None:
    nl = Netlist()
    nl.create_inst("i", kcl="pdk", component="c", settings={}, na=1, nb=1)
    nl.create_net(PortArrayRef(instance="i", port="o1", ia=1, ib=1))
    assert len(nl.nets) == 1
    member = nl.nets[0][0]
    assert isinstance(member, PortRef)
    assert not isinstance(member, PortArrayRef)


def test_netlist_create_net_array_oob() -> None:
    nl = Netlist()
    nl.create_inst("i", kcl="pdk", component="c", settings={}, na=2, nb=2)
    with pytest.raises(ValueError):
        nl.create_net(PortArrayRef(instance="i", port="o1", ia=5, ib=1))


def test_netlist_create_net_array_portref_oob_on_unit_array() -> None:
    nl = Netlist()
    nl.create_inst("i", kcl="pdk", component="c", settings={}, na=1, nb=1)
    # ia=2 is out of bounds for a 1x1 array (and ia=1, ib=1 would collapse
    # to a plain PortRef).
    with pytest.raises(ValueError):
        nl.create_net(PortArrayRef(instance="i", port="o1", ia=2, ib=1))


def test_netlist_round_trip_json() -> None:
    nl = Netlist()
    nl.create_port("p1")
    nl.create_inst(
        "i1", kcl="pdk", component="comp", settings={"width": 1}, na=1, nb=1
    )
    nl.create_net(NetlistPort(name="p1"), PortRef(instance="i1", port="o1"))
    s = nl.to_json()
    nl2 = Netlist.from_json(s)
    assert nl2 == nl


def test_netlist_round_trip_dict() -> None:
    nl = Netlist()
    nl.create_port("p1")
    nl.create_inst("i1", kcl="pdk", component="comp", settings={}, na=2, nb=3)
    nl.create_net(PortRef(instance="i1", port="o1"))
    d = nl.to_dict()
    nl2 = Netlist.from_dict(d)
    assert nl2 == nl


def test_netlist_extra_field_forbidden() -> None:
    with pytest.raises(Exception):
        Netlist.from_dict({"instances": {}, "nets": [], "ports": [], "x": 1})


def test_netlist_validate_assigns_instance_name() -> None:
    nl = Netlist.from_dict(
        {
            "instances": {
                "i1": {
                    "kcl": "pdk",
                    "component": "comp",
                    "settings": {},
                }
            },
            "nets": [],
            "ports": [],
        }
    )
    assert nl.get_instance("i1").name == "i1"


def test_netlist_sort_orders_instances_nets_ports() -> None:
    nl = Netlist()
    nl.create_inst("b", kcl="p", component="c", settings={})
    nl.create_inst("a", kcl="p", component="c", settings={})
    nl.create_port("p2")
    nl.create_port("p1")
    nl.create_net(PortRef(instance="b", port="o1"))
    nl.create_net(PortRef(instance="a", port="o1"))
    nl.sort()
    assert nl.instance_names() == ["a", "b"]
    assert [p.name for p in nl.ports] == ["p1", "p2"]


def test_netlist_flatten_instances() -> None:
    nl = Netlist()
    nl.create_inst("a", kcl="p", component="c", settings={})
    nl.create_inst("b", kcl="p", component="c", settings={})
    nl.create_inst("flat", kcl="p", component="c", settings={})
    nl.create_net(
        PortRef(instance="a", port="o1"),
        PortRef(instance="flat", port="o1"),
    )
    nl.create_net(
        PortRef(instance="flat", port="o2"),
        PortRef(instance="b", port="o1"),
    )
    nl.flatten_instances(["flat"])
    assert not nl.has_instance("flat")
    flat_refs = [
        port
        for net in nl.nets
        for port in net
        if isinstance(port, PortRef) and port.instance == "flat"
    ]
    assert flat_refs == []
