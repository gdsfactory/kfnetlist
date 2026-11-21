from kfnetlist.morphnet.morphnet_schema import DirectiveKind
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


class TestIncludeSection:
    def test_include_section_is_lib_directive(self) -> None:
        netlist = parse_spectre('include "m.scs" section=tt\n')
        (d,) = netlist.directives
        assert (d.kind, d.value, d.name) == (DirectiveKind.LIB, "m.scs tt", "")

    def test_include_section_lang(self) -> None:
        netlist = parse_spectre('include "m.lib" section=tt lang=ngspice\n')
        (d,) = netlist.directives
        assert (d.kind, d.value, d.name) == (
            DirectiveKind.LIB,
            "m.lib tt",
            "lang=ngspice",
        )

    def test_include_lang_only(self) -> None:
        netlist = parse_spectre('include "m.lib" lang=ngspice\n')
        (d,) = netlist.directives
        assert (d.kind, d.value, d.name) == (
            DirectiveKind.INCLUDE,
            "m.lib",
            "lang=ngspice",
        )

    def test_plain_include_unchanged(self) -> None:
        (d,) = parse_spectre('include "m.scs"\n').directives
        assert (d.kind, d.value, d.name) == (DirectiveKind.INCLUDE, "m.scs", "")

    def test_round_trip(self) -> None:
        for line in (
            'include "m.scs" section=tt',
            'include "m.lib" section=tt lang=ngspice',
            'include "m.lib" lang=ngspice',
            'include "m.scs"',
        ):
            assert line in write_spectre(parse_spectre(line + "\n")).splitlines()


class TestSimulationFixtures:
    def test_a_source_is_a_stimulus(self) -> None:
        from kfnetlist.morphnet.morphnet_schema import WaveformKind
        from kfnetlist.morphnet.netlist.expression import parameter_value
        from kfnetlist.morphnet.netlist.stimulus import stimulus_of

        nl = parse_spectre(
            "V1 (a 0) vsource dc=0.9 mag=1 type=pulse val0=0 val1=1.8 period=2n\n"
            'I1 (a 0) isource dc=1m type="sine" sinedc=1m ampl=0.5m freq=1M\n'
            "R1 (a 0) resistor r=1k\n"
        )
        v1, i1, _ = nl.circuits[0].subcircuits
        assert v1.parameters == [] and i1.parameters == []
        stim = stimulus_of(nl, v1)
        assert stim.name == "__top__/V1"
        assert stim.waveform.kind == WaveformKind.PULSE
        assert stim.waveform.args["val1"] == parameter_value("1.8")
        assert stim.ac_magnitude == parameter_value("1")
        assert stimulus_of(nl, i1).waveform.kind == WaveformKind.SIN

    def test_simulator_lang_sections_are_one_netlist(self) -> None:
        nl = parse_spectre(
            "simulator lang=spice\n.subckt rdiv a b\nR1 a b 1k\n.ends rdiv\n"
            "simulator lang=spectre\nX1 (in mid) rdiv\nX2 (mid out) rdiv\n"
        )
        assert sorted(c.name for c in nl.circuits) == ["__top__", "rdiv"]
        assert nl.top_circuit == "__top__"

    def test_top_level_instances_are_the_top_even_with_subcircuits(self) -> None:
        nl = parse_spectre(
            "subckt foo (a)\nR1 (a 0) resistor r=1k\nends foo\nX1 (n) foo\n"
        )
        assert nl.top_circuit == "__top__"
