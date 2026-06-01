from __future__ import annotations

from kfnetlist import Netlist, NetlistPort, PortRef


def test_group_nets_merges_equivalent_port_nets() -> None:
    nl = Netlist()
    nl.create_inst("a", kcl="pdk", component="other", settings={})
    nl.create_port("VDD")
    nl.create_port("VDDIO")
    nl.create_net(
        NetlistPort(name="VDD"),
        PortRef(instance="a", port="o1"),
    )
    nl.create_net(
        NetlistPort(name="VDDIO"),
        PortRef(instance="a", port="o2"),
    )

    out = nl.group_nets(equivalent_ports=[["VDD", "VDDIO"]])

    port_nets = [
        net
        for net in out.nets
        if any(isinstance(m, NetlistPort) for m in net)
    ]
    assert len(port_nets) == 1
    members = {
        (m.instance, m.port) if isinstance(m, PortRef) else ("", m.name)
        for m in port_nets[0]
    }
    assert ("", "VDD") in members
    assert ("a", "o1") in members
    assert ("a", "o2") in members


def test_group_nets_untouched_nets_preserved() -> None:
    nl = Netlist()
    nl.create_inst("a", kcl="pdk", component="other", settings={})
    nl.create_inst("b", kcl="pdk", component="other", settings={})
    nl.create_port("SIG")
    nl.create_net(
        PortRef(instance="a", port="o1"),
        PortRef(instance="b", port="o1"),
    )
    nl.create_net(
        NetlistPort(name="SIG"),
        PortRef(instance="a", port="o2"),
    )

    out = nl.group_nets(equivalent_ports=[["X", "Y"]])
    assert len(out.nets) == 2


def test_group_nets_removes_non_canonical_ports() -> None:
    nl = Netlist()
    nl.create_inst("a", kcl="pdk", component="other", settings={})
    nl.create_port("VDD")
    nl.create_port("VDDIO")
    nl.create_net(
        NetlistPort(name="VDD"),
        PortRef(instance="a", port="o1"),
    )
    nl.create_net(
        NetlistPort(name="VDDIO"),
        PortRef(instance="a", port="o2"),
    )

    out = nl.group_nets(equivalent_ports=[["VDD", "VDDIO"]])
    port_names = {p.name for p in out.ports}
    assert "VDD" in port_names
    assert "VDDIO" not in port_names


def test_group_nets_returns_new_netlist() -> None:
    nl = Netlist()
    nl.create_inst("a", kcl="pdk", component="other", settings={})
    nl.create_port("VDD")
    nl.create_port("VDDIO")
    nl.create_net(
        NetlistPort(name="VDD"),
        PortRef(instance="a", port="o1"),
    )
    nl.create_net(
        NetlistPort(name="VDDIO"),
        PortRef(instance="a", port="o2"),
    )

    before = nl.to_json()
    nl.group_nets(equivalent_ports=[["VDD", "VDDIO"]])
    assert nl.to_json() == before


def test_group_nets_empty_equivalence_is_noop() -> None:
    nl = Netlist()
    nl.create_inst("a", kcl="pdk", component="other", settings={})
    nl.create_port("SIG")
    nl.create_net(
        NetlistPort(name="SIG"),
        PortRef(instance="a", port="o1"),
    )

    out = nl.group_nets(equivalent_ports=[])
    assert len(out.nets) == 1
    assert len(out.ports) == 1


def test_group_nets_multiple_groups_independent() -> None:
    nl = Netlist()
    nl.create_inst("a", kcl="pdk", component="other", settings={})
    nl.create_port("VDD")
    nl.create_port("VDDIO")
    nl.create_port("VSS")
    nl.create_port("GND")
    nl.create_net(
        NetlistPort(name="VDD"),
        PortRef(instance="a", port="p1"),
    )
    nl.create_net(
        NetlistPort(name="VDDIO"),
        PortRef(instance="a", port="p2"),
    )
    nl.create_net(
        NetlistPort(name="VSS"),
        PortRef(instance="a", port="p3"),
    )
    nl.create_net(
        NetlistPort(name="GND"),
        PortRef(instance="a", port="p4"),
    )

    out = nl.group_nets(
        equivalent_ports=[["VDD", "VDDIO"], ["VSS", "GND"]]
    )
    assert len(out.nets) == 2
    port_names = {p.name for p in out.ports}
    assert port_names == {"VDD", "VSS"}
