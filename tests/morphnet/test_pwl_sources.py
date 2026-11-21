"""PWL (inline and from a file) and spaced source functions in every grammar."""

from pathlib import Path

import pytest

from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    Connection,
    Netlist,
    PortReference,
    Stimulus,
    SubCircuit,
    Waveform,
    WaveformKind,
)
from kfnetlist.morphnet.netlist import (
    parse_hspice,
    parse_spectre,
    parse_spectre_spice,
    parse_spice,
    parse_systemverilog,
    parse_vams,
    parse_xyce,
    write_hspice,
    write_spectre,
    write_spectre_spice,
    write_spice,
    write_systemverilog,
    write_vams,
    write_xyce,
)
from kfnetlist.morphnet.netlist.expression import parameter_value
from kfnetlist.morphnet.netlist.stimulus import attach, stimulus_of
from kfnetlist.morphnet.netlist.value_utils import to_float

DIALECTS = {
    "ngspice": (write_spice, parse_spice),
    "hspice": (write_hspice, parse_hspice),
    "xyce": (write_xyce, parse_xyce),
    "spectre": (write_spectre, parse_spectre),
    "spectre_spice": (write_spectre_spice, parse_spectre_spice),
    "verilog-a": (write_vams, parse_vams),
    "systemverilog": (write_systemverilog, parse_systemverilog),
}
POINTS = Waveform(
    kind=WaveformKind.PWL, points=[parameter_value(v) for v in ("0", "0", "1n", "1.8")]
)
FILE = Waveform(kind=WaveformKind.PWL, file="data/w.txt")


def sources() -> Netlist:
    refs = [
        SubCircuit(name=n, circuit_name=m)
        for n, m in (("V1", "vsource"), ("I2", "isource"))
    ]
    conns = [
        Connection(name="a", source=PortReference(instance_name=r.name, port_name="p"))
        for r in refs
    ] + [
        Connection(name="0", source=PortReference(instance_name=r.name, port_name="n"))
        for r in refs
    ]
    nl = Netlist(
        top_circuit="__top__",
        circuits=[Circuit(name="__top__", subcircuits=refs, connections=conns)],
    )
    attach(nl, "__top__", refs[0], Stimulus(waveform=POINTS))
    attach(nl, "__top__", refs[1], Stimulus(waveform=FILE))
    return nl


def numbers(stim: Stimulus | None) -> tuple:
    assert stim is not None and stim.waveform is not None
    w = stim.waveform
    points = [to_float(p.prefixed_value) for p in w.points if p.prefixed_value]
    return WaveformKind(w.kind), points, w.file


@pytest.mark.parametrize("dialect", list(DIALECTS))
def test_pwl_points_and_files_round_trip(dialect):
    write, parse = DIALECTS[dialect]
    nl = sources()
    back = parse(write(nl))
    refs = {s.name.upper().lstrip("X"): s for c in back.circuits for s in c.subcircuits}
    kind, points, file = numbers(stimulus_of(back, refs["V1"]))
    assert (kind, file) == (WaveformKind.PWL, None)
    assert points == pytest.approx([0, 0, 1e-9, 1.8])
    assert numbers(stimulus_of(back, refs["I2"])) == (
        WaveformKind.PWL,
        [],
        Path("data/w.txt"),
    )


@pytest.mark.parametrize(
    "parse", [parse_spice, parse_hspice, parse_xyce, parse_spectre_spice]
)
def test_spice_reads_spaced_functions_and_pwl_files(parse):
    nl = parse(
        '* t\nV1 a 0 PULSE (0 1.8 1n 10p 10p 1n 2n)\nV2 b 0 PWL FILE "data\\w.txt"\n'
        "V3 c 0 PWL (0 0 1n 1.8)\n.end\n"
    )
    v1, v2, v3 = nl.circuits[0].subcircuits
    assert stimulus_of(nl, v1).waveform.args["period"] == parameter_value("2n")
    assert stimulus_of(nl, v2).waveform.file == Path("data/w.txt")
    assert len(stimulus_of(nl, v3).waveform.points) == 4


def test_spectre_reads_wave_lists_and_files():
    nl = parse_spectre(
        "V1 (a 0) vsource type=pwl wave=[0 0 1n vdd]\n"
        'V2 (b 0) vsource type=pwl file="data/w.txt"\n'
    )
    v1, v2 = nl.circuits[0].subcircuits
    assert stimulus_of(nl, v1).waveform.points[-1] == parameter_value("vdd")
    assert stimulus_of(nl, v2).waveform.file == Path("data/w.txt")
    assert v1.parameters == [] and v2.parameters == []


def test_verilog_a_reads_a_pwl_file_attribute():
    nl = parse_vams(
        'module t;\n  (* pwl_file = "data/w.txt" *) vpwl #(.dc(0)) V1 (.p(a), .n(b));\nendmodule\n'
    )
    (v1,) = nl.circuits[0].subcircuits
    assert stimulus_of(nl, v1).waveform.file == Path("data/w.txt")
