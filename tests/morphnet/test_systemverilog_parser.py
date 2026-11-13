import pytest

from kfnetlist import NetlistPort, morphnet
from kfnetlist.morphnet.morphnet_schema import DirectiveKind, Parameter, SignalDomain
from kfnetlist.morphnet.netlist import parse_systemverilog


def nets(text: str, cell: str) -> set[frozenset[str]]:
    nl = morphnet.to_netlists(parse_systemverilog(text))[cell]
    return {
        frozenset(
            m.name if isinstance(m, NetlistPort) else f"{m.instance}.{m.port}"
            for m in n
        )
        for n in nl.nets
    }


def value(param: Parameter) -> float:
    assert param.default_value is not None
    assert param.default_value.prefixed_value is not None
    return param.default_value.prefixed_value.double_value


class TestPorts:
    def test_ansi_ports_inherit_direction_and_type(self) -> None:
        mod = parse_systemverilog(
            "module m (input wire [3:0] a, b, output logic y, inout z);\nendmodule\n"
        ).circuits[0]
        assert [(p.name, p.direction.name, p.discipline) for p in mod.ports] == [
            ("a", "INPUT", "wire"),
            ("b", "INPUT", "wire"),
            ("y", "OUTPUT", "logic"),
            ("z", "INOUT", ""),
        ]

    def test_non_ansi_ports(self) -> None:
        mod = parse_systemverilog(
            """\
module m (a, b, y);
  input a, b;
  output y;
  wire y;
endmodule
"""
        ).circuits[0]
        assert [(p.name, p.direction.name, p.discipline) for p in mod.ports] == [
            ("a", "INPUT", ""),
            ("b", "INPUT", ""),
            ("y", "OUTPUT", "wire"),
        ]

    def test_user_type_port(self) -> None:
        mod = parse_systemverilog(
            "module m (inout optical o1, input e1);\nendmodule\n"
        ).circuits[0]
        assert mod.ports[0].discipline == "optical"
        assert mod.ports[1].discipline == ""


class TestParameters:
    def test_header_and_body_parameters(self) -> None:
        mod = parse_systemverilog(
            """\
module m #(parameter real gap = 200e-9, length = 10e-6, parameter int n = 4'b1010) ();
  localparam W = 2 * n + 1;
endmodule
"""
        ).circuits[0]
        params = {p.name: p for p in mod.parameters}
        assert value(params["gap"]) == pytest.approx(200e-9)
        assert params["length"].properties["type"] == "real"
        assert value(params["n"]) == 10
        assert params["W"].default_value is None
        assert params["W"].properties == {"expr": "2*n+1", "localparam": "true"}

    def test_instance_parameter_overrides(self) -> None:
        text = """\
module wg #(parameter length = 1, width = 2) (inout o1, o2);
endmodule
module top (inout o1, o2);
  wg #(.length(10u)) X1 (.o1(o1), .o2(n1));
  wg #(5, 6) X2 (n1, o2);
endmodule
"""
        top = parse_systemverilog(text).circuits[1]
        x1, x2 = top.subcircuits
        assert x1.parameters[0].name == "length"
        assert value(x1.parameters[0]) == 10
        assert [p.name for p in x2.parameters] == ["length", "width"]


class TestInstances:
    def test_connection_styles(self) -> None:
        text = """\
module cell (input a, b, output y);
endmodule
module top (input a, b, output y, z);
  wire n1;
  cell U1 (.a, .b(b), .y(n1));
  cell U2 (.*);
  cell U3 (n1, , z), U4 (.a(1'b0), .b(), .y(y));
endmodule
"""
        assert nets(text, "top") == {
            frozenset({"a", "U1.a", "U2.a"}),
            frozenset({"b", "U1.b", "U2.b"}),
            frozenset({"U1.y", "U3.a"}),
            frozenset({"y", "U2.y", "U4.y"}),
            frozenset({"z", "U3.y"}),
        }

    def test_positional_unknown_module_uses_pin_index(self) -> None:
        top = parse_systemverilog(
            "module top (inout a, b);\n  ext X1 (a, b);\nendmodule\n"
        ).circuits[0]
        assert {c.target.port_name for c in top.connections if c.target} == {"p0", "p1"}

    def test_wildcard_needs_definition(self) -> None:
        with pytest.raises(ValueError, match="needs the definition"):
            parse_systemverilog("module top (inout a);\n  ext X1 (.*);\nendmodule\n")

    def test_bit_select_net_names(self) -> None:
        text = """\
module top (input [1:0] bus);
  buf_cell U1 (.a(bus[0]), .y(n[1])), U2 (.a(n[1]), .y(bus[1]));
endmodule
"""
        assert frozenset({"U1.y", "U2.a"}) in nets(text, "top")
        top = parse_systemverilog(text).circuits[0]
        assert "n[1]" in {c.name for c in top.connections}


class TestNetMerging:
    def test_assign_and_alias_merge_nets(self) -> None:
        text = """\
module top (inout a, b);
  wire n1, n2, n3;
  wire n4 = n3;
  assign n1 = a;
  alias n2 = n3 = b;
  r X1 (.p(n1), .n(n2));
  r X2 (.p(n4), .n(a));
endmodule
"""
        assert nets(text, "top") == {
            frozenset({"a", "X1.p", "X2.n"}),
            frozenset({"b", "X1.n", "X2.p"}),
        }


class TestPreprocessing:
    def test_behavioral_blocks_are_stored(self) -> None:
        text = """\
module top (input clk, output reg q);
  /* block comment */
  (* keep *) always_ff @(posedge clk) begin
    if (q) q <= 1'b0; else q <= 1'b1;
  end
  always @(*) case (q) 1'b0: q = 1; default: q = 0; endcase
  initial q = 0;
  function automatic int f(int x); return x; endfunction
  generate for (genvar i = 0; i < 2; i++) begin : g end endgenerate
  assign q = clk & q;
  typedef struct { logic a; logic b; } pair_t;
  r X1 (.p(clk), .n(q));  // trailing comment
endmodule
"""
        mod = parse_systemverilog(text).circuits[0]
        blocks = list(mod.properties.values())
        assert len(blocks) == 6
        assert blocks[0].startswith("always_ff") and blocks[0].endswith("end")
        assert blocks[1].endswith("endcase")
        assert blocks[5] == "assign q = clk & q;"
        assert [s.name for s in mod.subcircuits] == ["X1"]

    def test_directives(self) -> None:
        netlist = parse_systemverilog(
            '`timescale 1ns/1ps\n`include "cells.sv"\nmodule m ();\nendmodule\n'
        )
        assert [(d.kind, d.value) for d in netlist.directives] == [
            (DirectiveKind.TIMESCALE, "1ns/1ps"),
            (DirectiveKind.INCLUDE, "cells.sv"),
        ]

    def test_top_is_the_uninstantiated_module(self) -> None:
        text = """\
module top (inout a);
  leaf X1 (.a);
endmodule : top
module leaf (inout a);
endmodule
"""
        assert parse_systemverilog(text).top_circuit == "top"


def test_electrical_rc_divider() -> None:
    text = """\
module rc (input vin, output vout, inout gnd);
  resistor #(.r(1k)) R1 (.p(vin), .n(vout));
  capacitor #(.c(100p)) C1 (.p(vout), .n(gnd));
endmodule
"""
    netlist = parse_systemverilog(text)
    nl = morphnet.to_netlists(netlist)["rc"]
    assert nl.instances["R1"].component == "resistor"
    assert nl.instances["C1"].settings["c"] == pytest.approx(1e-10)
    assert nets(text, "rc") == {
        frozenset({"vin", "R1.p"}),
        frozenset({"vout", "R1.n", "C1.p"}),
        frozenset({"gnd", "C1.n"}),
    }
    assert {c.domain for c in netlist.circuits[0].connections} == {
        SignalDomain.ELECTRICAL
    }


def test_waveguide_mzi_with_heater() -> None:
    text = """\
module dc_coupler #(parameter real gap = 200e-9) (input o1, o2, output o3, o4);
  wg_directional_coupler Xcoupler (.o1, .o2, .o3, .o4);
endmodule

module mzi (input o1, o2, output o3, o4, input e1, inout vdd);
  dc_coupler #(.gap(150n)) Xdc1 (o1, o2, top_a, bot_a);
  dc_coupler Xdc2 (.o1(top_b), .o2(bot_b), .o3(o3), .o4(o4));
  wg_heater Xarm_top (.o1(top_a), .o2(top_b), .e1(e1), .e2(vdd));
  wg_delay Xarm_bot (.o1(bot_a), .o2(bot_b));
endmodule
"""
    netlist = parse_systemverilog(text)
    assert netlist.top_circuit == "mzi"
    mzi = netlist.circuits[1]
    WG, EL = SignalDomain.WAVEGUIDE, SignalDomain.ELECTRICAL
    assert {p.name: p.domain for p in mzi.ports} == {
        "o1": WG, "o2": WG, "o3": WG, "o4": WG, "e1": EL, "vdd": EL,
    }  # fmt: skip
    assert {c.name: c.domain for c in mzi.connections} == {
        "o1": WG, "o2": WG, "o3": WG, "o4": WG, "e1": EL, "vdd": EL,
        "top_a": WG, "bot_a": WG, "top_b": WG, "bot_b": WG,
    }  # fmt: skip
    assert nets(text, "mzi") == {
        frozenset({"o1", "Xdc1.o1"}),
        frozenset({"o2", "Xdc1.o2"}),
        frozenset({"o3", "Xdc2.o3"}),
        frozenset({"o4", "Xdc2.o4"}),
        frozenset({"e1", "Xarm_top.e1"}),
        frozenset({"vdd", "Xarm_top.e2"}),
        frozenset({"Xdc1.o3", "Xarm_top.o1"}),
        frozenset({"Xdc1.o4", "Xarm_bot.o1"}),
        frozenset({"Xarm_top.o2", "Xdc2.o1"}),
        frozenset({"Xarm_bot.o2", "Xdc2.o2"}),
    }
