from pathlib import Path

import pytest

from kfnetlist.morphnet.morphnet_schema import (
    DirectiveKind,
    ExternalCircuitKind,
    SignalDomain,
)
from kfnetlist.morphnet.netlist.vams.parser import parse_vams


class TestBasicParsing:
    def test_simple_module(self) -> None:
        text = """\
module divider (vin, vout, gnd);
  inout vin, vout, gnd;
  electrical vin, vout, gnd;
  resistor #(.r(10k)) R1 (.p(vin), .n(vout));
  resistor #(.r(10k)) R2 (.p(vout), .n(gnd));
endmodule
"""
        netlist = parse_vams(text)
        assert netlist.top_circuit == "divider"
        assert len(netlist.circuits) == 1
        mod = netlist.circuits[0]
        assert mod.name == "divider"
        assert len(mod.ports) == 3
        assert len(mod.subcircuits) == 2

    def test_port_directions(self) -> None:
        text = """\
module amp (inp, inn, out, vdd, vss);
  input inp, inn;
  output out;
  inout vdd, vss;
  electrical inp, inn, out, vdd, vss;
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        dirs = {p.name: p.direction.name for p in mod.ports}
        assert dirs["inp"] == "INPUT"
        assert dirs["inn"] == "INPUT"
        assert dirs["out"] == "OUTPUT"
        assert dirs["vdd"] == "INOUT"

    def test_port_disciplines(self) -> None:
        text = """\
module test (a, b);
  inout a, b;
  electrical a, b;
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        for port in mod.ports:
            assert port.discipline == "electrical"


class TestParameters:
    def test_typed_real_parameter(self) -> None:
        text = """\
module test (a);
  inout a;
  parameter real r = 50;
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        assert len(mod.parameters) == 1
        p = mod.parameters[0]
        assert p.name == "r"
        assert p.properties.get("type") == "real"
        assert p.default_value is not None
        assert p.default_value.prefixed_value is not None

    def test_typed_integer_parameter(self) -> None:
        text = """\
module test (a);
  inout a;
  parameter integer n = 4;
endmodule
"""
        netlist = parse_vams(text)
        p = netlist.circuits[0].parameters[0]
        assert p.name == "n"
        assert p.properties.get("type") == "integer"
        assert p.default_value is not None
        assert p.default_value.prefixed_value is not None
        assert p.default_value.prefixed_value.double_value == 4.0

    def test_untyped_parameter(self) -> None:
        text = """\
module test (a);
  inout a;
  parameter x = 100;
endmodule
"""
        netlist = parse_vams(text)
        p = netlist.circuits[0].parameters[0]
        assert p.name == "x"
        assert p.properties.get("type", "") == ""

    def test_localparam(self) -> None:
        text = """\
module test (a);
  inout a;
  localparam real pi = 3.14;
endmodule
"""
        netlist = parse_vams(text)
        p = netlist.circuits[0].parameters[0]
        assert p.name == "pi"
        assert p.properties.get("localparam") == "true"
        assert p.properties.get("type") == "real"


class TestInstances:
    def test_named_ports_and_params(self) -> None:
        text = """\
module test (a, b);
  inout a, b;
  electrical a, b;
  resistor #(.r(10k)) R1 (.p(a), .n(b));
endmodule
"""
        netlist = parse_vams(text)
        ref = netlist.circuits[0].subcircuits[0]
        assert ref.name == "R1"
        assert ref.circuit_name == "resistor"
        assert any(p.name == "r" for p in ref.parameters)
        param = next(p for p in ref.parameters if p.name == "r")
        assert param.default_value.prefixed_value is not None

    def test_positional_ports(self) -> None:
        text = """\
module test (a, b);
  inout a, b;
  electrical a, b;
  resistor #(.r(1k)) R1 (a, b);
endmodule
"""
        netlist = parse_vams(text)
        ref = netlist.circuits[0].subcircuits[0]
        assert ref.name == "R1"
        assert ref.circuit_name == "resistor"
        assert len(netlist.circuits[0].connections) > 0

    def test_no_param_override(self) -> None:
        text = """\
module test (a, b);
  inout a, b;
  electrical a, b;
  mysubckt X1 (.p(a), .n(b));
endmodule
"""
        netlist = parse_vams(text)
        ref = netlist.circuits[0].subcircuits[0]
        assert ref.name == "X1"
        assert ref.circuit_name == "mysubckt"
        assert len(ref.parameters) == 0


class TestDirectives:
    def test_include(self) -> None:
        text = """\
`include "constants.vams"
module test (a);
  inout a;
endmodule
"""
        netlist = parse_vams(text)
        includes = [d for d in netlist.directives if d.kind == DirectiveKind.INCLUDE]
        assert len(includes) == 1
        assert includes[0].value == "constants.vams"

    def test_timescale(self) -> None:
        text = """\
`timescale 1ns/1ps
module test (a);
  inout a;
endmodule
"""
        netlist = parse_vams(text)
        ts = [d for d in netlist.directives if d.kind == DirectiveKind.TIMESCALE]
        assert len(ts) == 1
        assert ts[0].value == "1ns/1ps"


class TestNatureAndDiscipline:
    def test_nature(self) -> None:
        text = """\
nature Voltage;
  units = "V";
  access = V;
  abstol = 1u;
endnature
module test (a);
  inout a;
endmodule
"""
        netlist = parse_vams(text)
        ext_names = {e.name for e in netlist.ext_circuits}
        assert "Voltage" in ext_names
        voltage = next(e for e in netlist.ext_circuits if e.name == "Voltage")
        assert voltage.kind == ExternalCircuitKind.NATURE
        assert "nature_abstol" in voltage.properties

    def test_discipline(self) -> None:
        text = """\
discipline electrical;
  potential Voltage;
  flow Current;
  domain continuous;
enddiscipline
module test (a);
  inout a;
endmodule
"""
        netlist = parse_vams(text)
        ext_names = {e.name for e in netlist.ext_circuits}
        assert "electrical" in ext_names
        elec = next(e for e in netlist.ext_circuits if e.name == "electrical")
        assert elec.kind == ExternalCircuitKind.DISCIPLINE
        assert elec.properties.get("discipline_potential") == "Voltage"
        assert elec.properties.get("discipline_flow") == "Current"
        assert elec.properties.get("discipline_domain") == "continuous"


class TestGroundAndAnalog:
    def test_ground(self) -> None:
        text = """\
module test (a);
  inout a;
  electrical a;
  ground gnd;
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        assert mod.properties.get("ground_net") == "gnd"

    def test_analog_block(self) -> None:
        text = """\
module test (a);
  inout a;
  electrical a;
  analog begin
    V(a) <+ 1.0;
  end
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        assert "analog_block" in mod.properties
        assert "V(a)" in mod.properties["analog_block"]


class TestConnectivity:
    def test_named_port_connections(self) -> None:
        text = """\
module test (a, b, gnd);
  inout a, b, gnd;
  electrical a, b, gnd;
  resistor #(.r(10k)) R1 (.p(a), .n(b));
  resistor #(.r(10k)) R2 (.p(b), .n(gnd));
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        assert len(mod.connections) > 0
        conn_nets = {c.name for c in mod.connections}
        assert "a" in conn_nets
        assert "b" in conn_nets
        assert "gnd" in conn_nets


class TestMultipleModules:
    def test_two_modules(self) -> None:
        text = """\
module inner (p, n);
  inout p, n;
  electrical p, n;
endmodule

module outer (a, b);
  inout a, b;
  electrical a, b;
  inner X1 (.p(a), .n(b));
endmodule
"""
        netlist = parse_vams(text)
        assert len(netlist.circuits) == 2
        assert netlist.top_circuit == "outer"


class TestAnalogBlockDirectives:
    def test_analog_begin_end_stored(self) -> None:
        text = """\
module vsrc (p, n);
  inout p, n;
  electrical p, n;
  parameter real vdc = 1.0;
  analog begin
    V(p, n) <+ vdc;
  end
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        assert "analog_block" in mod.properties
        block = mod.properties["analog_block"]
        assert "V(p, n)" in block
        assert "vdc" in block

    def test_analog_single_statement(self) -> None:
        text = """\
module vsrc (p, n);
  inout p, n;
  electrical p, n;
  analog V(p, n) <+ 1.0;
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        assert "analog_block" in mod.properties
        assert "V(p, n)" in mod.properties["analog_block"]

    def test_analog_with_nested_begin_end(self) -> None:
        text = """\
module ctrl (out);
  output out;
  electrical out;
  analog begin
    if (V(out) > 0.5) begin
      I(out) <+ 1m;
    end
  end
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        assert "analog_block" in mod.properties
        block = mod.properties["analog_block"]
        assert "if" in block
        assert "I(out)" in block

    def test_module_with_analog_and_instances(self) -> None:
        text = """\
module amp (inp, out, vdd, gnd);
  inout inp, out, vdd, gnd;
  electrical inp, out, vdd, gnd;
  parameter real gain = 10;
  resistor #(.r(1k)) R1 (.p(inp), .n(out));
  analog begin
    V(out) <+ gain * V(inp);
  end
endmodule
"""
        netlist = parse_vams(text)
        mod = netlist.circuits[0]
        assert len(mod.subcircuits) == 1
        assert mod.subcircuits[0].name == "R1"
        assert "analog_block" in mod.properties
        assert "gain" in mod.properties["analog_block"]


class TestParamset:
    def test_paramset(self) -> None:
        text = """\
paramset myres resistor;
  parameter real r = 100;
endparamset
module test (a, b);
  inout a, b;
  electrical a, b;
endmodule
"""
        netlist = parse_vams(text)
        ext_names = {e.name for e in netlist.ext_circuits}
        assert "myres" in ext_names
        myres = next(e for e in netlist.ext_circuits if e.name == "myres")
        assert myres.kind == ExternalCircuitKind.MODEL
        assert myres.properties.get("model_type") == "resistor"


class TestBuses:
    SWITCH = (Path(__file__).parent / "netlists/vams/switch_2x2.vams").read_text()

    def test_switch_simulation_view(self) -> None:
        netlist = parse_vams(
            self.SWITCH, {"IS_SIM": "1"}, {"optical": SignalDomain.WAVEGUIDE}
        )
        switch = netlist.circuits[0]
        assert [(p.name, p.width, p.discipline, p.domain) for p in switch.ports] == [
            ("in", 2, "optical", SignalDomain.WAVEGUIDE),
            ("out", 2, "optical", SignalDomain.WAVEGUIDE),
            ("sel", 4, "electrical", SignalDomain.ELECTRICAL),
        ]
        conns = {
            (c.name, c.source.instance_name, c.source.port_name,
             c.target.instance_name, c.target.port_name, c.domain.name)
            for c in switch.connections
            if c.source is not None and c.target is not None
        }  # fmt: skip
        assert conns == {
            ("in[1]", "", "in[1]", "I_I[1]", "in0", "WAVEGUIDE"),
            ("in[0]", "", "in[0]", "I_I[0]", "in0", "WAVEGUIDE"),
            ("out[1]", "", "out[1]", "I_O[1]", "out0", "WAVEGUIDE"),
            ("out[0]", "", "out[0]", "I_O[0]", "out0", "WAVEGUIDE"),
            ("sel[3]", "", "sel[3]", "I_O[1]", "sel", "ELECTRICAL"),
            ("sel[2]", "", "sel[2]", "I_O[0]", "sel", "ELECTRICAL"),
            ("sel[1]", "", "sel[1]", "I_I[1]", "sel", "ELECTRICAL"),
            ("sel[0]", "", "sel[0]", "I_I[0]", "sel", "ELECTRICAL"),
            ("a[0]", "I_I[0]", "out0", "I_O[0]", "in0", "WAVEGUIDE"),
            ("a[1]", "I_I[0]", "out1", "I_O[1]", "in0", "WAVEGUIDE"),
            ("a[2]", "I_I[1]", "out0", "I_O[0]", "in1", "WAVEGUIDE"),
            ("a[3]", "I_I[1]", "out1", "I_O[1]", "in1", "WAVEGUIDE"),
        }

    def test_leaf_pin_domains(self) -> None:
        WG = SignalDomain.WAVEGUIDE
        pins = {"MZM_1X2": {"out0": WG, "out1": WG}}
        switch = parse_vams(self.SWITCH, pin_domains=pins).circuits[0]
        domains = {c.name: c.domain for c in switch.connections}
        assert all(domains[f"a[{i}]"] == WG for i in range(4))
        assert domains["in[0]"] == SignalDomain.ELECTRICAL  # MZM_1X2.in0 not mapped

    def test_positional_ports_use_the_definition(self) -> None:
        text = """\
module cell (p, n);
  inout [1:0] p;
  inout n;
endmodule
module top (bus, g);
  inout [1:0] bus;
  inout g;
  cell X1 (bus, g);
endmodule
"""
        top = parse_vams(text).circuits[1]
        assert {(c.target.instance_name, c.target.port_name) for c in top.connections if c.target} == {
            ("X1", "p[1]"), ("X1", "p[0]"), ("X1", "n")
        }  # fmt: skip

    def test_width_mismatch_raises(self) -> None:
        text = "module top (a);\n  inout [2:0] a;\n  leaf L[1:0] (.x(a));\nendmodule\n"
        with pytest.raises(ValueError, match="3 bits for 2 instance"):
            parse_vams(text)


class TestSimulationFixtures:
    """Verilog-AMS native forms: LRM Annex E source primitives, net initializers."""

    def test_a_source_primitive_is_a_stimulus(self) -> None:
        from kfnetlist.morphnet.morphnet_schema import WaveformKind
        from kfnetlist.morphnet.netlist.expression import parameter_value
        from kfnetlist.morphnet.netlist.stimulus import stimulus_of

        nl = parse_vams(
            "module t (a);\n  inout a;\n"
            "  vpulse #(.dc(0.9), .val0(0), .val1(1.8), .td(1n)) V1 (.p(a), .n(gnd));\n"
            "  isine #(.dc(1m)) I1 (.p(a), .n(gnd));\nendmodule\n"
        )
        v1, i1 = nl.circuits[0].subcircuits
        assert (v1.circuit_name, i1.circuit_name) == ("vsource", "isource")
        assert v1.parameters == [] and i1.parameters == []
        stim = stimulus_of(nl, v1)
        assert stim.waveform.kind == WaveformKind.PULSE
        assert stim.waveform.args["delay"] == parameter_value("1n")
        assert stimulus_of(nl, i1).dc == parameter_value("1m")

    def test_override_values_are_expressions_and_references(self) -> None:
        nl = parse_vams(
            "module t (a, b);\n  inout a, b;\n"
            "  nch #(.l(0.13 * 1e-6), .w(wmin)) M1 (.d(a), .g(b), .s(b), .b(b));\n"
            "endmodule\n"
        )
        l, w = nl.circuits[0].subcircuits[0].parameters
        assert l.default_value.expression.binary is not None
        assert w.default_value.expression.reference == "wmin"

    def test_a_module_without_ports_parses(self) -> None:
        for header in ("module t;", "module t ();"):
            nl = parse_vams(
                f"{header}\n  resistor #(.r(1k)) R1 (.p(a), .n(b));\nendmodule\n"
            )
            assert [c.name for c in nl.circuits] == ["t"]

    def test_attributes_carry_spice_libraries_and_code(self) -> None:
        import json

        code = json.dumps(
            [
                {
                    "name": "rdiv",
                    "language": "spice",
                    "body": ".subckt rdiv a b\nR1 a b 1k\n.ends rdiv",
                }
            ]
        )
        escaped = code.replace("\\", "\\\\").replace('"', '\\"')
        nl = parse_vams(
            f'(* spice_lib = "a.lib mos_ff\\nb.lib", spice_code = "{escaped}" *)\n'
            "module t;\n  rdiv X1 (.a(x), .b(y));\nendmodule\n"
        )
        assert [(d.kind.name, d.value) for d in nl.directives] == [
            ("LIB", "a.lib mos_ff"),
            ("LIB", "b.lib"),
        ]
        (macro,) = nl.macros
        assert (macro.name, macro.language) == ("rdiv", "spice")
        assert macro.body.splitlines()[1] == "R1 a b 1k"

    def test_a_net_initializer_is_a_nodeset(self) -> None:
        nl = parse_vams(
            "module t (a);\n  inout a;\n  electrical a;\n  electrical b = 5.0;\n"
            "  resistor #(.r(1k)) R1 (.p(a), .n(b));\nendmodule\n"
        )
        assert nl.simulation.node_sets.conditions == {"V(b)": "5"}
