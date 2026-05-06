"""Phase 1 smoke tests for the three Rust-backed port pyclasses."""

from __future__ import annotations

import json

import pytest
from kfnetlist import NetlistPort, PortArrayRef, PortRef


def test_netlistport_construction_and_fields() -> None:
    p = NetlistPort(name="x")
    assert p.name == "x"
    p.name = "y"
    assert p.name == "y"


def test_portref_construction_and_fields() -> None:
    p = PortRef(instance="i", port="o1")
    assert p.instance == "i"
    assert p.port == "o1"
    p.port = "o2"
    assert p.port == "o2"


def test_portarrayref_construction_and_fields() -> None:
    p = PortArrayRef(instance="i", port="o1", ia=2, ib=3)
    assert p.ia == 2
    assert p.ib == 3
    p.ia = 5
    assert p.ia == 5


def test_hash_equality_netlistport() -> None:
    a = NetlistPort(name="x")
    b = NetlistPort(name="x")
    c = NetlistPort(name="y")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c


def test_hash_equality_portref() -> None:
    a = PortRef(instance="i", port="p")
    b = PortRef(instance="i", port="p")
    c = PortRef(instance="i", port="q")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    assert hash(a) != hash(c)


def test_portref_vs_portarrayref_inequality() -> None:
    pr = PortRef(instance="i", port="p")
    par = PortArrayRef(instance="i", port="p", ia=0, ib=1)
    # Sibling types: even with matching instance/port they are not equal.
    assert pr != par
    assert par != pr


def test_ordering_across_types() -> None:
    np_ = NetlistPort(name="x")
    pr = PortRef(instance="i", port="p")
    par = PortArrayRef(instance="i", port="p", ia=0, ib=0)

    # NetlistPort < PortRef < PortArrayRef
    assert np_ < pr
    assert pr < par
    assert np_ < par

    assert not (pr < np_)
    assert not (par < pr)
    assert not (par < np_)


def test_ordering_within_type() -> None:
    a = NetlistPort(name="a")
    b = NetlistPort(name="b")
    assert a < b
    assert not (b < a)

    p1 = PortRef(instance="a", port="x")
    p2 = PortRef(instance="a", port="y")
    p3 = PortRef(instance="b", port="x")
    assert p1 < p2 < p3

    q1 = PortArrayRef(instance="a", port="x", ia=0, ib=0)
    q2 = PortArrayRef(instance="a", port="x", ia=0, ib=1)
    q3 = PortArrayRef(instance="a", port="x", ia=1, ib=0)
    assert q1 < q2 < q3


def test_sortable_mixed_list() -> None:
    items = [
        PortArrayRef(instance="i", port="p", ia=0, ib=0),
        NetlistPort(name="z"),
        PortRef(instance="i", port="p"),
    ]
    items.sort()
    assert isinstance(items[0], NetlistPort)
    assert isinstance(items[1], PortRef) and not isinstance(items[1], PortArrayRef)
    assert isinstance(items[2], PortArrayRef)


def test_repr_and_str() -> None:
    assert repr(NetlistPort(name="x")) == "NetlistPort(name='x')"
    pr = PortRef(instance="i", port="o1")
    assert repr(pr) == "PortRef(instance='i', port='o1')"
    assert str(pr) == "i['o1']"
    par = PortArrayRef(instance="i", port="o1", ia=2, ib=3)
    assert repr(par) == "PortArrayRef(instance='i', port='o1', ia=2, ib=3)"
    assert str(par) == "i['o1', 2, 3]"


def test_as_python_str_with_override() -> None:
    pr = PortRef(instance="i", port="o1")
    assert pr.as_python_str("alias") == "alias['o1']"
    par = PortArrayRef(instance="i", port="o1", ia=2, ib=3)
    assert par.as_python_str("alias") == "alias['o1', 2, 3]"


def test_json_roundtrip_netlistport() -> None:
    p = NetlistPort(name="x")
    s = p.to_json()
    assert json.loads(s) == {"name": "x"}
    assert NetlistPort.from_json(s) == p


def test_json_roundtrip_portref() -> None:
    p = PortRef(instance="i", port="o1")
    s = p.to_json()
    assert json.loads(s) == {"instance": "i", "port": "o1"}
    assert PortRef.from_json(s) == p


def test_json_roundtrip_portarrayref() -> None:
    p = PortArrayRef(instance="i", port="o1", ia=2, ib=3)
    s = p.to_json()
    assert json.loads(s) == {"instance": "i", "port": "o1", "ia": 2, "ib": 3}
    assert PortArrayRef.from_json(s) == p


def test_dict_roundtrip() -> None:
    p = PortArrayRef(instance="i", port="o1", ia=2, ib=3)
    d = p.to_dict()
    assert d == {"instance": "i", "port": "o1", "ia": 2, "ib": 3}
    assert PortArrayRef.from_dict(d) == p


def test_from_json_rejects_missing_field() -> None:
    with pytest.raises(ValueError):
        PortRef.from_json('{"instance": "i"}')


def test_from_json_rejects_extra_field() -> None:
    with pytest.raises(ValueError):
        PortRef.from_json('{"instance": "i", "port": "p", "junk": 1}')
    with pytest.raises(ValueError):
        NetlistPort.from_json('{"name": "x", "extra": 1}')


def test_eq_with_foreign_type_is_false_not_error() -> None:
    pr = PortRef(instance="i", port="p")
    assert (pr == 5) is False
    assert (pr != 5) is True
    assert (5 == pr) is False


def test_lt_with_foreign_type_raises_typeerror() -> None:
    pr = PortRef(instance="i", port="p")
    with pytest.raises(TypeError):
        _ = pr < 5
    with pytest.raises(TypeError):
        _ = pr > "abc"


def test_set_in_dict_keys_uses_hash() -> None:
    a = PortRef(instance="i", port="p")
    b = PortRef(instance="i", port="p")
    s = {a, b}
    assert len(s) == 1
