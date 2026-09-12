"""
Backwards-compatibility guards for the kfnetlist public API.

These tests pin the top-level public surface so that additions to
kfnetlist.kfnetlist_schema can never silently break existing consumers.
"""

from __future__ import annotations

import kfnetlist


# ---------------------------------------------------------------------------
# Top-level package exports
# ---------------------------------------------------------------------------


class TestTopLevelExports:
    """Every symbol in kfnetlist.__all__ must remain importable and correct."""

    def test_all_declared(self):
        expected = {
            "Net",
            "Netlist",
            "NetlistArray",
            "NetlistInstance",
            "NetlistPort",
            "PortArrayRef",
            "PortCheck",
            "PortRef",
            "check_connection",
            "Placement",
            "flatten_netlists",
            "PlacedInstance",
            "PlacedNetlist",
        }
        assert set(kfnetlist.__all__) == expected

    def test_native_types_are_rust_classes(self):
        # Confirm the Rust extension is what backs these names
        from kfnetlist._native import (
            Net,
            Netlist,
            NetlistArray,
            NetlistInstance,
            NetlistPort,
            PortArrayRef,
            PortRef,
        )

        assert kfnetlist.Net is Net
        assert kfnetlist.Netlist is Netlist
        assert kfnetlist.NetlistArray is NetlistArray
        assert kfnetlist.NetlistInstance is NetlistInstance
        assert kfnetlist.NetlistPort is NetlistPort
        assert kfnetlist.PortArrayRef is PortArrayRef
        assert kfnetlist.PortRef is PortRef

    def test_schema_subpackage_does_not_pollute_top_level(self):
        # Importing the schema subpackage must not inject names into kfnetlist
        import kfnetlist.kfnetlist_schema  # noqa: F401

        schema_only = {
            "TopLevelModule",
            "Module",
            "Instance",
            "ArraySpec",
            "ProtoCircuit",
            "ProtoModule",
            "load_pic_yaml",
        }
        for name in schema_only:
            assert not hasattr(kfnetlist, name), (
                f"kfnetlist.{name} should not be present at the top level"
            )

    def test_version_string_present(self):
        assert isinstance(kfnetlist.__version__, str)
        assert kfnetlist.__version__  # ty: ignore[redundant-condition]


# ---------------------------------------------------------------------------
# Rust type construction API unchanged
# ---------------------------------------------------------------------------


class TestRustTypeAPI:
    def test_netlist_create_inst_signature(self):
        nl = kfnetlist.Netlist()
        inst = nl.create_inst("i", kcl="", component="comp")
        assert inst.name == "i"
        assert inst.component == "comp"

    def test_netlist_create_port(self):
        nl = kfnetlist.Netlist()
        p = nl.create_port("clk")
        assert p.name == "clk"

    def test_netlist_create_net(self):
        nl = kfnetlist.Netlist()
        nl.create_port("p")
        nl.create_inst("a", kcl="", component="c")
        nl.create_net(kfnetlist.NetlistPort("p"), kfnetlist.PortRef("a", "x"))
        assert len(list(nl.nets)) == 1

    def test_net_construction(self):
        net = kfnetlist.Net([kfnetlist.NetlistPort("p")])
        assert len(net) == 1

    def test_netlist_array(self):
        arr = kfnetlist.NetlistArray(na=2, nb=3)
        assert arr.na == 2
        assert arr.nb == 3

    def test_port_ref(self):
        pr = kfnetlist.PortRef("inst", "port")
        assert pr.instance == "inst"
        assert pr.port == "port"

    def test_port_array_ref(self):
        par = kfnetlist.PortArrayRef("inst", "port", 1, 2)
        assert par.instance == "inst"
        assert par.ia == 1
        assert par.ib == 2

    def test_netlist_json_roundtrip(self):
        nl = kfnetlist.Netlist()
        nl.create_inst("x", kcl="lib", component="comp", settings={"a": 1})
        j = nl.to_json()
        recovered = kfnetlist.Netlist.from_json(j)
        assert recovered.get_instance("x").component == "comp"

    def test_netlist_dict_roundtrip(self):
        nl = kfnetlist.Netlist()
        nl.create_inst("x", kcl="lib", component="comp")
        d = nl.to_dict()
        recovered = kfnetlist.Netlist.from_dict(d)
        assert recovered.has_instance("x")


# ---------------------------------------------------------------------------
# Schema aliases are identical objects to the Rust types
# ---------------------------------------------------------------------------


class TestSchemaAliasIdentity:
    """kfnetlist.kfnetlist_schema re-exports must be the same objects."""

    def test_netlist(self):
        from kfnetlist.kfnetlist_schema import Netlist

        assert Netlist is kfnetlist.Netlist

    def test_net(self):
        from kfnetlist.kfnetlist_schema import Net

        assert Net is kfnetlist.Net

    def test_netlist_instance(self):
        from kfnetlist.kfnetlist_schema import NetlistInstance

        assert NetlistInstance is kfnetlist.NetlistInstance

    def test_netlist_array(self):
        from kfnetlist.kfnetlist_schema import NetlistArray

        assert NetlistArray is kfnetlist.NetlistArray

    def test_netlist_port(self):
        from kfnetlist.kfnetlist_schema import NetlistPort

        assert NetlistPort is kfnetlist.NetlistPort

    def test_port_ref(self):
        from kfnetlist.kfnetlist_schema import PortRef

        assert PortRef is kfnetlist.PortRef

    def test_port_array_ref(self):
        from kfnetlist.kfnetlist_schema import PortArrayRef

        assert PortArrayRef is kfnetlist.PortArrayRef
