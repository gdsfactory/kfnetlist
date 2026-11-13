"""Every parser marks ``o<N>`` terminals as waveguide and the rest as electrical."""

import pytest

from kfnetlist.morphnet.morphnet_schema import SignalDomain
from kfnetlist.morphnet.netlist import (
    parse_hspice,
    parse_spectre,
    parse_spice,
    parse_systemverilog,
    parse_vams,
    parse_xyce,
)
from kfnetlist.morphnet.netlist.net_utils import domain_of

SPICE = """\
.subckt cell o1 e1 vdd out
R1 e1 vdd 1k
.ends cell
.subckt top o1 e1 vdd out
X1 o1 e1 vdd out cell
.ends top
"""
SPECTRE = """\
subckt cell (o1 e1 vdd out)
R1 (e1 vdd) resistor r=1k
ends cell
subckt top (o1 e1 vdd out)
X1 (o1 e1 vdd out) cell
ends top
"""
VAMS = """\
module top (o1, e1, vdd, out);
  cell X1 (.o1(o1), .e1(e1), .vdd(vdd), .out(out));
endmodule
"""
SV = """\
module top (inout o1, e1, vdd, out);
  cell X1 (.o1, .e1, .vdd, .out);
endmodule
"""

WG, EL = SignalDomain.WAVEGUIDE, SignalDomain.ELECTRICAL
EXPECTED = {"o1": WG, "e1": EL, "vdd": EL, "out": EL}


def test_domain_of() -> None:
    assert domain_of("o1") == WG
    assert domain_of("o12") == WG
    assert domain_of("e1") == EL
    assert domain_of("out") == EL
    assert domain_of("vdd") == EL


@pytest.mark.parametrize(
    ("parse", "text"),
    [
        (parse_spice, SPICE),
        (parse_xyce, SPICE),
        (parse_hspice, SPICE),
        (parse_spectre, SPECTRE),
        (parse_vams, VAMS),
        (parse_systemverilog, SV),
    ],
)
def test_parsers_mark_optical_terminals(parse, text: str) -> None:
    top = next(c for c in parse(text).circuits if c.name == "top")
    assert {p.name: p.domain for p in top.ports} == EXPECTED
    assert {c.name: c.domain for c in top.connections} == EXPECTED
