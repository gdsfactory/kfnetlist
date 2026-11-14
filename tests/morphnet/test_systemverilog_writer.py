from pathlib import Path

import pytest

from kfnetlist.morphnet.netlist import (
    parse_spice,
    parse_systemverilog,
    parse_vams,
    write_spectre,
    write_spice,
    write_systemverilog,
    write_vams,
)
from kfnetlist.morphnet.netlist.systemverilog.writer import sv_name

MZI = """\
`timescale 1ns/1ps
module dc #(parameter real gap = 200e-9, parameter int n = 4'b1010) (
  input o1, o2, output o3, o4);
  localparam W = 2*n+1;
  wg_directional_coupler Xc (.o1, .o2, .o3, .o4);
endmodule
module mzi (input optical o1, o2, output o3, o4, input e1, inout vdd);
  dc #(.gap(150n)) X1 (o1, o2, a, b);
  dc X2 (.o1(a), .o2(b), .o3(o3), .o4());
  heater H (.e1(e1), .e2(vdd));
  always @(posedge e1) vdd <= 1;
endmodule
"""

INVERTER = """\
.subckt inv in out vdd vss
M1 out in vdd vdd pmos w=2u l=180n
M2 out in vss vss nmos w=1u l=180n
.ends inv
"""


@pytest.fixture
def written() -> str:
    return write_systemverilog(parse_systemverilog(MZI))


def test_header_ports_and_parameters(written: str) -> None:
    assert "`timescale 1ns/1ps" in written
    assert "module dc #(parameter real gap = 2e-07, parameter int n = 10) (" in written
    assert "  input optical o1,\n" in written
    assert "  localparam W = 2*n+1;" in written


def test_instances_use_named_connections(written: str) -> None:
    assert "  dc #(.gap(1.5e-07)) X1 (.o1(o1), .o2(o2), .o3(a), .o4(b));" in written
    assert "  dc X2 (.o1(a), .o2(b), .o3(o3), .o4());" in written


def test_behavioral_blocks_are_written_back(written: str) -> None:
    assert "  always @(posedge e1) vdd <= 1;\nendmodule" in written


def test_write_parse_write_is_stable(written: str) -> None:
    assert write_systemverilog(parse_systemverilog(written)) == written


def test_spice_devices_become_modules() -> None:
    text = write_systemverilog(parse_spice(INVERTER))
    assert (
        "mosfet #(.w(2e-06), .l(1.8e-07)) M1 (.d(out), .g(in), .s(vdd), .b(vdd));"
        in text
    )


def test_escaped_names() -> None:
    assert sv_name("net1") == "net1"
    assert sv_name("0") == "\\0 "
    assert sv_name("wire") == "\\wire "
    netlist = parse_systemverilog(
        "module t (inout a);\n  r R1 (.p(a), .n(\\0 ));\n  r R2 (.p(\\0 ), .n(a));\nendmodule\n"
    )
    assert write_systemverilog(netlist).count(".n(\\0 )") == 1


@pytest.mark.parametrize("write", [write_spice, write_spectre])
def test_devices_without_declaration_keep_pin_order(write) -> None:
    # Verilog-AMS / SystemVerilog carry no device declarations: positional
    # writers must still use the d, g, s, b template.
    text = write(parse_vams(write_vams(parse_spice(INVERTER))))
    assert "out in vdd vdd" in text


def connection_set(netlist) -> set[tuple]:
    return {
        (c.name, c.domain, (c.source.instance_name, c.source.port_name),
         (c.target.instance_name, c.target.port_name))
        for circuit in netlist.circuits
        for c in circuit.connections
        if c.source is not None and c.target is not None
    }  # fmt: skip


def test_buses_round_trip() -> None:
    from kfnetlist.morphnet.morphnet_schema import SignalDomain

    sv = (Path(__file__).parent / "netlists/systemverilog/switch_2x2.sv").read_text()
    types = {"connection": SignalDomain.WAVEGUIDE}
    parsed = parse_systemverilog(sv, {"IS_SIM": "1"}, types)
    text = write_systemverilog(parsed)
    assert "  input connection in [1:0],\n" in text
    assert "  connection a [3:0];\n" in text
    assert (
        "MZM_1X2 \\I_I[1]  (.in0(in[1]), .sel(sel[1]), .out0(a[2]), .out1(a[3]));"
        in text
    )
    reparsed = parse_systemverilog(text, disciplines=types)
    assert connection_set(reparsed) == connection_set(parsed)
    assert [(p.name, p.width) for p in reparsed.circuits[0].ports] == [
        ("in", 2), ("out", 2), ("sel", 4)
    ]  # fmt: skip
    assert write_systemverilog(reparsed) == text


def test_bus_connections_are_grouped() -> None:
    text = """\
module cell (input [3:0] a, output y);
endmodule
module top (input [3:0] bus, input [1:0] b, output y);
  cell C1 (.a({b, bus[3:2]}), .y(y));
  cell C2 (.a(bus), .y());
endmodule
"""
    written = write_systemverilog(parse_systemverilog(text))
    assert "  input [3:0] bus,\n" in written
    assert "  cell C1 (.a({b, bus[3:2]}), .y(y));" in written
    assert "  cell C2 (.a(bus), .y());" in written
