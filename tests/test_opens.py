"""Tests for open detection: unconnected ports, singleton nets, missing nets."""

from kfnetlist import Netlist, NetlistPort, PortRef


class TestDetectOpens:
    def test_unconnected_port(self):
        nl = Netlist()
        nl.create_inst("a", kcl="pdk", component="res", settings={})
        nl.create_port("VDD")
        nl.create_port("VSS")
        nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        # VSS is declared but not wired to any net
        opens = nl.detect_opens()
        assert opens["unconnected_ports"] == ["VSS"]

    def test_all_ports_connected(self):
        nl = Netlist()
        nl.create_inst("a", kcl="pdk", component="res", settings={})
        nl.create_port("VDD")
        nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        opens = nl.detect_opens()
        assert opens["unconnected_ports"] == []

    def test_no_ports(self):
        nl = Netlist()
        opens = nl.detect_opens()
        assert opens["unconnected_ports"] == []
        assert list(opens["singleton_nets"]) == []

    def test_singleton_net(self):
        nl = Netlist()
        nl.create_port("SIG")
        # A net with only one member is a dangling stub
        nl.create_net(NetlistPort(name="SIG"))
        opens = nl.detect_opens()
        singletons = list(opens["singleton_nets"])
        assert len(singletons) == 1
        assert len(singletons[0]) == 1

    def test_no_singleton_nets(self):
        nl = Netlist()
        nl.create_inst("a", kcl="pdk", component="res", settings={})
        nl.create_port("VDD")
        nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        opens = nl.detect_opens()
        assert list(opens["singleton_nets"]) == []

    def test_multiple_unconnected_ports_sorted(self):
        nl = Netlist()
        nl.create_port("Z")
        nl.create_port("A")
        nl.create_port("M")
        opens = nl.detect_opens()
        assert opens["unconnected_ports"] == ["A", "M", "Z"]

    def test_combined_unconnected_and_singleton(self):
        nl = Netlist()
        nl.create_inst("a", kcl="pdk", component="res", settings={})
        nl.create_port("VDD")
        nl.create_port("VSS")  # unconnected
        nl.create_port("SIG")
        # VDD properly wired
        nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        # SIG is a singleton (only one member)
        nl.create_net(NetlistPort(name="SIG"))

        opens = nl.detect_opens()
        assert opens["unconnected_ports"] == ["VSS"]
        singletons = list(opens["singleton_nets"])
        assert len(singletons) == 1


class TestFindNetDifference:
    def test_identical_netlists_returns_empty(self):
        nl = Netlist()
        nl.create_inst("a", kcl="pdk", component="res", settings={})
        nl.create_port("VDD")
        nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        ref_nl = Netlist.from_json(nl.to_json())
        diff = nl.find_net_difference(ref_nl)
        assert list(diff["missing"]) == []
        assert list(diff["extra"]) == []

    def test_missing_net_detected(self):
        # Reference has two nets
        ref_nl = Netlist()
        ref_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ref_nl.create_inst("b", kcl="pdk", component="res", settings={})
        ref_nl.create_port("VDD")
        ref_nl.create_port("VSS")
        ref_nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        ref_nl.create_net(
            NetlistPort(name="VSS"),
            PortRef(instance="b", port="p1"),
        )

        # Extracted has only one net
        ext_nl = Netlist()
        ext_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ext_nl.create_inst("b", kcl="pdk", component="res", settings={})
        ext_nl.create_port("VDD")
        ext_nl.create_port("VSS")
        ext_nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )

        diff = ext_nl.find_net_difference(ref_nl)
        missing_list = list(diff["missing"])
        assert len(missing_list) == 1
        # The missing net should be the VSS net
        members = missing_list[0].members()
        member_reprs = {
            m.name
            if hasattr(m, "name") and not hasattr(m, "instance")
            # TODO: refactor to use isinstance narrowing so ty can resolve .instance/.port on PortRef
            else f"{m.instance},{m.port}"  # ty: ignore[unresolved-attribute]
            for m in members
        }
        assert "VSS" in member_reprs
        assert "b,p1" in member_reprs
        assert list(diff["extra"]) == []

    def test_extra_nets_reported(self):
        # Reference has one net, extracted has two
        ref_nl = Netlist()
        ref_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ref_nl.create_port("VDD")
        ref_nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )

        ext_nl = Netlist()
        ext_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ext_nl.create_inst("b", kcl="pdk", component="res", settings={})
        ext_nl.create_port("VDD")
        ext_nl.create_port("VSS")
        ext_nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        ext_nl.create_net(
            NetlistPort(name="VSS"),
            PortRef(instance="b", port="p1"),
        )

        diff = ext_nl.find_net_difference(ref_nl)
        assert list(diff["missing"]) == []
        extra_list = list(diff["extra"])
        assert len(extra_list) == 1

    def test_empty_reference_returns_all_as_extra(self):
        ext_nl = Netlist()
        ext_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ext_nl.create_port("VDD")
        ext_nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        ref_nl = Netlist()
        diff = ext_nl.find_net_difference(ref_nl)
        assert list(diff["missing"]) == []
        assert len(list(diff["extra"])) == 1

    def test_empty_extracted_returns_all_as_missing(self):
        ref_nl = Netlist()
        ref_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ref_nl.create_port("VDD")
        ref_nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        ext_nl = Netlist()
        diff = ext_nl.find_net_difference(ref_nl)
        assert len(list(diff["missing"])) == 1
        assert list(diff["extra"]) == []

    def test_set_semantics_on_net_equality(self):
        """Nets are compared by sorted member content, not by insertion order."""
        ref_nl = Netlist()
        ref_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ref_nl.create_inst("b", kcl="pdk", component="res", settings={})
        ref_nl.create_port("SIG")
        ref_nl.create_net(
            PortRef(instance="b", port="o1"),
            NetlistPort(name="SIG"),
            PortRef(instance="a", port="o1"),
        )

        # Same net but members added in different order
        ext_nl = Netlist()
        ext_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ext_nl.create_inst("b", kcl="pdk", component="res", settings={})
        ext_nl.create_port("SIG")
        ext_nl.create_net(
            NetlistPort(name="SIG"),
            PortRef(instance="a", port="o1"),
            PortRef(instance="b", port="o1"),
        )

        diff = ext_nl.find_net_difference(ref_nl)
        assert list(diff["missing"]) == []
        assert list(diff["extra"]) == []
