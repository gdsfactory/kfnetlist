"""Silent losses the whole-branch review found; each must be kept or be loud."""

import json

import pytest

from kfnetlist.morphnet.morphnet_schema import Stimulus
from kfnetlist.morphnet.netlist import (
    parse_spectre,
    parse_spice,
    parse_vams,
    write_gsch,
    write_spectre,
    write_spice,
    write_vams,
)
from kfnetlist.morphnet.netlist.expression import parameter_value
from kfnetlist.morphnet.netlist.gsch.sim import source_props
from kfnetlist.morphnet.netlist.stimulus import stimulus_of
from kfnetlist.morphnet.netlist.value_utils import to_float


def test_spectre_keeps_its_own_source_params():
    for line, kept in (
        ("V1 (a 0) vsource type=sine sinedc=0 ampl=1 freq=1k damp=10\n", "10"),
        ("V1 (a 0) vsource type=exp val0=0 val1=1 td1=1n tau1=2n\n", "1n"),
    ):
        nl = parse_spectre(line)
        stim = stimulus_of(nl, nl.circuits[0].subcircuits[0])
        assert parameter_value(kept) in stim.waveform.args.values(), line


def test_spectre_keeps_an_unknown_source_type():
    nl = parse_spectre("V1 (a 0) vsource dc=1 type=prbs seed=3\n")
    text = write_spectre(nl)
    assert "type=prbs" in text and "seed=3" in text


def test_a_value_then_a_name_is_a_value_and_a_model():
    nl = parse_spice("* t\nR1 a b 1k rpoly\nR2 a b rpoly w=1u l=2u\n.end\n")
    r1, r2 = nl.circuits[0].subcircuits
    assert r1.properties["model_name"] == "rpoly"
    assert [p.name for p in r1.parameters] == ["value"]
    assert r2.properties["model_name"] == "rpoly"  # geometry params: a model


def test_an_unknown_spice_source_function_is_an_error():
    with pytest.raises(Exception, match="AM"):
        parse_spice("* t\nV1 a 0 DC 1 AM(1 0 1k 10k 0)\n.end\n")


def test_write_gsch_keeps_the_sources_of_a_spice_netlist():
    nl = parse_spice("* t\nV1 a 0 DC 0.5\nI1 a 0 1m\nR1 a 0 1k\n.end\n")
    doc = json.loads(write_gsch(nl))
    props = {e["name"]: e.get("props") for e in doc.values() if e.get("name")}
    assert props["V1"] == {"dc": "0.5"}
    assert props["I1"] == {"dc": "1m"}


def test_gsch_source_props_refuse_an_ac_phase():
    stim = Stimulus(ac_magnitude=parameter_value("1"), ac_phase=parameter_value("90"))
    with pytest.raises(ValueError, match="phase"):
        source_props("V1", stim, {})


def test_verilog_a_mega_is_M_both_ways():
    nl = parse_spice("* t\nI1 a 0 SIN(0 1m 1meg)\nR1 a 0 1k\n.end\n")
    text = write_vams(nl)
    assert "meg" not in text and ".freq(1M)" in text
    back = parse_vams(text)
    (i1,) = (s for s in back.circuits[0].subcircuits if s.name == "I1")
    freq = stimulus_of(back, i1).waveform.args["freq"]
    assert freq.prefixed_value is not None
    assert to_float(freq.prefixed_value) == 1e6
    r = parse_vams("module t;\n  resistor #(.r(1M)) R1 (.p(a), .n(b));\nendmodule\n")
    (value,) = r.circuits[0].subcircuits[0].parameters
    pv = value.default_value.prefixed_value if value.default_value else None
    assert pv is not None and to_float(pv) == 1e6
    assert "SIN(0 1m 1meg)" in write_spice(back)  # SPICE keeps its own spelling
