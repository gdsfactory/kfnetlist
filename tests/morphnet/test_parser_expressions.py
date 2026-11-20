"""Each parser reads its dialect's parameter expressions into an ``Expression`` tree."""

import pytest

from kfnetlist.morphnet.morphnet_schema import Expression, Netlist
from kfnetlist.morphnet.netlist import (
    parse_hspice,
    parse_spectre,
    parse_spice,
    parse_systemverilog,
    parse_xyce,
    write_hspice,
    write_spectre,
    write_spice,
    write_systemverilog,
    write_xyce,
)
from kfnetlist.morphnet.netlist.expression import parse_expression

SPICE = """\
.subckt cell p n a=1 b=2
R1 p n 1k w={a*b+1} l=a
.ends cell
.end
"""
HSPICE = SPICE.replace("{a*b+1}", "'a*b+1'")
XYCE = SPICE.replace("n a=1", "n PARAMS: a=1")
SPECTRE = """\
subckt cell (p n) a=1 b=2
R1 (p n) resistor r=1k w=a*b+1 l=a
ends cell
"""
SV = """\
module cell #(parameter a = 1, parameter b = 2) (input p, n);
  res #(.w(a*b+1), .l(a)) R1 (p, n);
endmodule
"""

DIALECTS = [
    pytest.param(parse_spice, write_spice, SPICE, "w={a * b + 1}", id="spice"),
    pytest.param(parse_hspice, write_hspice, HSPICE, "w='a * b + 1'", id="hspice"),
    pytest.param(parse_xyce, write_xyce, XYCE, "w={a * b + 1}", id="xyce"),
    pytest.param(parse_spectre, write_spectre, SPECTRE, "w=a * b + 1", id="spectre"),
    pytest.param(
        parse_systemverilog, write_systemverilog, SV, ".w(a * b + 1)", id="sv"
    ),
]


def param(netlist: Netlist, name: str) -> Expression | None:
    cell = next(c for c in netlist.circuits if c.name == "cell")
    inst = next(s for s in cell.subcircuits if s.name == "R1")
    value = next(p for p in inst.parameters if p.name == name).default_value
    assert value is not None
    return value.expression


@pytest.mark.parametrize(("parse", "write", "text", "written"), DIALECTS)
def test_expression_round_trips(parse, write, text, written):
    first = parse(text)
    assert param(first, "w") == parse_expression("a*b+1")
    out = write(first)
    assert written in out
    assert param(parse(out), "w") == param(first, "w")


@pytest.mark.parametrize(("parse", "write", "text", "written"), DIALECTS)
def test_bare_identifier_is_a_reference(parse, write, text, written):
    assert param(parse(text), "l") == Expression(reference="a")


@pytest.mark.parametrize(
    "value",
    ["a * b + 1", "max(a, b) * 2", "(a + 1) * 2", "a > b ? a : b", "-a"],
)
def test_spectre_bare_expression_ends_at_the_next_param(value):
    text = f"subckt cell (p n)\nR1 (p n) resistor w={value} l=a\nends cell\n"
    assert param(parse_spectre(text), "w") == parse_expression(value)
    assert param(parse_spectre(text), "l") == Expression(reference="a")


def test_spectre_model_expression_stops_at_the_closing_paren():
    netlist = parse_spectre("model m resistor (w=(a+1)*2 l=b)\n")
    [ext] = netlist.ext_circuits
    w, l = (p.default_value.expression for p in ext.parameters)
    assert (w, l) == (parse_expression("(a+1)*2"), Expression(reference="b"))


def test_plain_numbers_stay_prefixed_values():
    for netlist in (parse_spice(SPICE), parse_spectre(SPECTRE)):
        cell = next(c for c in netlist.circuits if c.name == "cell")
        assert all(p.default_value.prefixed_value for p in cell.parameters)


@pytest.mark.parametrize(
    ("parse", "write", "text", "written"),
    [
        (parse_spice, write_spice, ".param x={a*b+1}\n.end\n", ".param x={a * b + 1}"),
        (
            parse_hspice,
            write_hspice,
            ".param x='a*b+1'\n.end\n",
            ".param x='a * b + 1'",
        ),
        (parse_xyce, write_xyce, ".param x={a*b+1}\n.end\n", ".param x={a * b + 1}"),
        (
            parse_spectre,
            write_spectre,
            "parameters x=a*b+1\n",
            "parameters x=a * b + 1",
        ),
    ],
)
def test_param_directive_keeps_its_expression_text(parse, write, text, written):
    out = write(parse(text))
    assert written in out
    assert write(parse(out)) == out
