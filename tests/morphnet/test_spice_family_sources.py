"""Every SPICE-family parser reads sources as stimuli, bare values as references."""

import pytest

from kfnetlist.morphnet.morphnet_schema import Expression, WaveformKind
from kfnetlist.morphnet.netlist import (
    parse_hspice,
    parse_spectre_spice,
    parse_spice,
    parse_xyce,
)
from kfnetlist.morphnet.netlist.expression import parameter_value
from kfnetlist.morphnet.netlist.stimulus import stimulus_of

PARSERS = {
    "spice": parse_spice,
    "hspice": parse_hspice,
    "xyce": parse_xyce,
    "spectre_spice": parse_spectre_spice,
}


def elements(nl):
    return {s.name: s for c in nl.circuits for s in c.subcircuits}


@pytest.mark.parametrize("dialect", list(PARSERS))
def test_a_source_line_is_a_stimulus(dialect):
    nl = PARSERS[dialect](
        "* t\nV1 a 0 DC 0.9 AC 1 PULSE(0 1.8 1n 10p 10p 1n 2n)\n"
        "I1 a 0 SIN(1m 0.5m 1meg)\nR1 a 0 1k\n.end\n"
    )
    v1, i1 = elements(nl)["V1"], elements(nl)["I1"]
    assert "model_name" not in v1.properties  # `AC` is no model
    stim = stimulus_of(nl, v1)
    assert stim.name == "__top__/V1"
    assert (stim.dc, stim.ac_magnitude) == (
        parameter_value("0.9"),
        parameter_value("1"),
    )
    assert stim.waveform.kind == WaveformKind.PULSE
    assert stim.waveform.args["period"] == parameter_value("2n")
    assert stimulus_of(nl, i1).waveform.args["freq"] == parameter_value("1meg")


@pytest.mark.parametrize("dialect", list(PARSERS))
def test_a_bare_value_is_a_reference_unless_a_model_has_its_name(dialect):
    nl = PARSERS[dialect](
        "* t\n.model rmod r\nR1 a b rload\nR2 a b rmod\nC1 a 0 1p\n.end\n"
    )
    r1, r2 = elements(nl)["R1"], elements(nl)["R2"]
    (value,) = r1.parameters
    assert value.default_value.expression == Expression(reference="rload")
    assert "model_name" not in r1.properties
    assert r2.properties["model_name"] == "rmod" and r2.parameters == []


@pytest.mark.parametrize("dialect", list(PARSERS))
def test_top_level_elements_are_the_top_even_with_subcircuits(dialect):
    nl = PARSERS[dialect]("* t\n.subckt foo a\nR1 a 0 1k\n.ends foo\nX1 n foo\n.end\n")
    assert nl.top_circuit == "__top__"
    nl = PARSERS[dialect]("* t\n.subckt foo a\nR1 a 0 1k\n.ends foo\n.end\n")
    assert nl.top_circuit == "foo"


@pytest.mark.parametrize(
    ("dialect", "text"),
    [("spice", "{w*2}"), ("xyce", "{w*2}"), ("hspice", "'w*2'")],
)
def test_a_wrapped_value_is_an_expression(dialect, text):
    nl = PARSERS[dialect](f"* t\nR1 a b {text}\n.end\n")
    (value,) = elements(nl)["R1"].parameters
    assert value.default_value.expression.binary is not None
