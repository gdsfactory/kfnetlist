from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.spectre.writer import write_spectre


class TestBasicParsing:
    def test_resistor_subcircuit(self) -> None:
        text = """\
subckt divider (vin vout gnd)
R1 (vin vout) resistor r=10k
R2 (vout gnd) resistor r=10k
ends divider
"""
        netlist = parse_spectre(text)
        assert netlist.top_circuit == "divider"
        assert len(netlist.circuits) == 1

    def test_port_names(self) -> None:
        text = """\
subckt mymod (a b c)
R1 (a b) resistor r=1k
ends mymod
"""
        netlist = parse_spectre(text)
        assert [p.name for p in netlist.circuits[0].ports] == ["a", "b", "c"]

    def test_instance_params(self) -> None:
        text = """\
subckt test (a b)
R1 (a b) resistor r=10k
ends test
"""
        netlist = parse_spectre(text)
        ref = netlist.circuits[0].subcircuits[0]
        assert any(p.name == "r" for p in ref.parameters)


class TestDeviceTypes:
    def test_mosfet(self) -> None:
        text = """\
subckt inv (in out vdd vss)
M1 (out in vdd vdd) pch w=1u l=0.18u
M2 (out in vss vss) nch w=0.5u l=0.18u
ends inv
"""
        netlist = parse_spectre(text)
        refs = netlist.circuits[0].subcircuits
        assert refs[0].circuit_name == "mosfet"
        assert refs[0].properties.get("model_name") == "pch"
        assert refs[1].properties.get("model_name") == "nch"

    def test_subcircuit_instance(self) -> None:
        text = """\
subckt inner (a b)
R1 (a b) resistor r=1k
ends inner

subckt outer (x y)
X1 (x y) inner
ends outer
"""
        netlist = parse_spectre(text)
        outer = next(m for m in netlist.circuits if m.name == "outer")
        assert outer.subcircuits[0].circuit_name == "inner"


class TestDirectives:
    def test_include(self) -> None:
        text = """\
include "models.scs"
subckt test (a b)
R1 (a b) resistor r=1k
ends test
"""
        netlist = parse_spectre(text)
        includes = [d for d in netlist.directives if d.kind.name == "INCLUDE"]
        assert len(includes) >= 1
        assert includes[0].value == "models.scs"

    def test_model_statement(self) -> None:
        text = """\
model nch nmos (level=49 vth0=0.4)
subckt test (d g s b)
M1 (d g s b) nch w=1u l=0.18u
ends test
"""
        netlist = parse_spectre(text)
        ext_names = {e.name for e in netlist.ext_circuits}
        assert "nch" in ext_names


class TestConnectivity:
    def test_hierarchy_port_resolution(self) -> None:
        text = """\
subckt child (p q)
R1 (p q) resistor r=1k
ends child

subckt parent (a b)
X1 (a b) child
ends parent
"""
        netlist = parse_spectre(text)
        parent = next(m for m in netlist.circuits if m.name == "parent")
        x1_ports: set[str] = set()
        for c in parent.connections:
            if c.target and c.target.instance_name == "X1":
                x1_ports.add(c.target.port_name)
            if c.source and c.source.instance_name == "X1":
                x1_ports.add(c.source.port_name)
        assert "p" in x1_ports
        assert "q" in x1_ports


def test_master_decides_device_not_instance_name() -> None:
    netlist = parse_spectre(
        """\
subckt inverter (a y)
R0 (a y) resistor r=1k
ends inverter
subckt top (a y)
I1 (a y) inverter
Xr (a y) capacitor c=1p
ends top
"""
    )
    top = netlist.circuits[1]
    assert [(s.name, s.circuit_name) for s in top.subcircuits] == [
        ("I1", "inverter"),
        ("Xr", "capacitor"),
    ]
    pins = {
        (c.target.instance_name, c.target.port_name)
        for c in top.connections
        if c.target
    }
    assert ("I1", "a") in pins and ("Xr", "p") in pins


def test_builtin_master_with_extra_nets_keeps_every_net() -> None:
    netlist = parse_spectre(
        """\
subckt mzi (e1 e2 arm)
Xheater (e1 e2 arm) resistor length=100u
ends mzi
"""
    )
    pins = {
        (c.target.port_name, c.name)
        for c in netlist.circuits[0].connections
        if c.target and c.target.instance_name == "Xheater"
    }
    assert pins == {("p0", "e1"), ("p1", "e2"), ("p2", "arm")}
    assert "Xheater (e1 e2 arm) resistor" in write_spectre(netlist)


def test_subckt_named_like_an_analysis_is_an_instance() -> None:
    netlist = parse_spectre(
        """\
subckt dc (o1 o2)
ends dc
subckt top (o1 o2)
Xdc1 (o1 o2) dc gap=200n
ends top
"""
    )
    top = netlist.circuits[1]
    assert [s.name for s in top.subcircuits] == ["Xdc1"]
    assert len(top.connections) == 2
