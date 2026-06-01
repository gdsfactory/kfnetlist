"""Tests for open detection: unconnected ports, singleton nets, missing nets."""

from kfnetlist import Net, Netlist, NetlistPort, PortRef


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


class TestFindOpenNets:
    def test_identical_netlists_returns_empty(self):
        nl = Netlist()
        nl.create_inst("a", kcl="pdk", component="res", settings={})
        nl.create_port("VDD")
        nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        ref_nl = Netlist.from_json(nl.to_json())
        missing = nl.find_open_nets(ref_nl)
        assert list(missing) == []

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

        missing = ext_nl.find_open_nets(ref_nl)
        missing_list = list(missing)
        assert len(missing_list) == 1
        # The missing net should be the VSS net
        members = missing_list[0].members()
        member_reprs = {m.name if hasattr(m, "name") and not hasattr(m, "instance") else f"{m.instance},{m.port}" for m in members}
        assert "VSS" in member_reprs
        assert "b,p1" in member_reprs

    def test_extra_nets_not_reported(self):
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

        missing = ext_nl.find_open_nets(ref_nl)
        assert list(missing) == []

    def test_empty_reference_returns_empty(self):
        ext_nl = Netlist()
        ext_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ext_nl.create_port("VDD")
        ext_nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        ref_nl = Netlist()
        missing = ext_nl.find_open_nets(ref_nl)
        assert list(missing) == []

    def test_empty_extracted_returns_all_reference_nets(self):
        ref_nl = Netlist()
        ref_nl.create_inst("a", kcl="pdk", component="res", settings={})
        ref_nl.create_port("VDD")
        ref_nl.create_net(
            NetlistPort(name="VDD"),
            PortRef(instance="a", port="p1"),
        )
        ext_nl = Netlist()
        missing = ext_nl.find_open_nets(ref_nl)
        assert len(list(missing)) == 1

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

        missing = ext_nl.find_open_nets(ref_nl)
        assert list(missing) == []
