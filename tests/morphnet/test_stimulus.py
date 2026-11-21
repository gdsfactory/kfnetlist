"""One stimulus, every source dialect: SPICE text, Spectre params, Verilog-A primitives."""

import pytest

from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    Netlist,
    Stimulus,
    SubCircuit,
    Waveform,
    WaveformKind,
)
from kfnetlist.morphnet.netlist.expression import parameter_value
from kfnetlist.morphnet.netlist.stimulus import (
    attach,
    from_primitive,
    from_spectre,
    parse_spice,
    primitive,
    spectre_params,
    spice_text,
    stimulus_of,
)


def wave(kind: WaveformKind, **args: str) -> Waveform:
    return Waveform(kind=kind, args={k: parameter_value(v) for k, v in args.items()})


def stim(dc=None, ac=None, phase=None, waveform=None) -> Stimulus:
    def pv(text):
        return None if text is None else parameter_value(text)

    return Stimulus(
        dc=pv(dc), ac_magnitude=pv(ac), ac_phase=pv(phase), waveform=waveform
    )


PULSE = wave(
    WaveformKind.PULSE,
    val0="0", val1="1.8", delay="1n", rise="10p", fall="10p", width="1n", period="2n",
)  # fmt: skip
CASES = {
    "dc": stim(dc="1.8"),
    "ac": stim(ac="1"),
    "dc_ac_phase": stim(dc="0.9", ac="1", phase="90"),
    "pulse": stim(dc="0.9", waveform=PULSE),
    "sin": stim(
        dc="1m",
        ac="1",
        waveform=wave(
            WaveformKind.SIN,
            sinedc="1m",
            ampl="0.5m",
            freq="1meg",
            delay="0",
            theta="0",
        ),
    ),  # fmt: skip
    "exp": stim(
        waveform=wave(
            WaveformKind.EXP,
            val0="0",
            val1="1",
            delay="1n",
            tau1="2n",
            td2="5n",
            tau2="3n",
        ),
    ),  # fmt: skip
    "sffm": stim(
        waveform=wave(
            WaveformKind.SFFM,
            sinedc="0",
            ampl="1",
            freq="1k",
            modindex="2",
            modfreq="100",
        ),
    ),  # fmt: skip
    "pwl": stim(
        waveform=Waveform(
            kind=WaveformKind.PWL,
            points=[parameter_value(t) for t in ("0", "0", "1n", "1.8")],
        )
    ),
    "expression": stim(
        dc="vdd / 2",
        waveform=wave(
            WaveformKind.PULSE,
            val0="0",
            val1="vdd",
            delay="0",
            rise="0",
            fall="0",
            width="w",
            period="2 * w",
        ),
    ),  # fmt: skip
}


@pytest.mark.parametrize("case", list(CASES))
def test_spice_text_reads_back(case):
    s = CASES[case]
    assert parse_spice(spice_text(s, "ngspice")) == s


@pytest.mark.parametrize("case", list(CASES))
def test_spectre_params_read_back(case):
    s = CASES[case]
    assert from_spectre(dict(spectre_params(s, "spectre"))) == s


@pytest.mark.parametrize("case", list(CASES))
def test_verilog_a_primitive_reads_back(case):
    s = CASES[case]
    master, params = primitive(s, current=False)
    assert from_primitive(master, dict(params)) == s


def test_spice_text_is_what_nyancad_writes():
    assert spice_text(stim(dc="0.9", ac="1"), "ngspice") == "DC 0.9 AC 1"
    assert spice_text(CASES["pulse"], "ngspice") == (
        "DC 0.9 PULSE(0 1.8 1n 10p 10p 1n 2n)"
    )
    assert spice_text(CASES["expression"], "ngspice") == (
        "DC {vdd / 2} PULSE(0 vdd 0 0 0 w {2 * w})"
    )


def test_spice_text_without_a_dc_is_ac_only():
    assert spice_text(stim(ac="1"), "ngspice") == "AC 1"
    assert parse_spice("1.8") == stim(dc="1.8")  # a bare value is the DC value


def test_vacask_drops_what_inspice_leaves_out_and_counts_td2_from_the_delay():
    pulse = dict(spectre_params(CASES["pulse"], "vacask"))
    assert pulse["type"] == '"pulse"'
    sin = dict(spectre_params(CASES["sin"], "vacask"))
    assert "delay" not in sin and "theta" not in sin
    exp = dict(spectre_params(CASES["exp"], "vacask"))
    assert exp["td2"] == "4e-09"  # 5n - 1n
    assert dict(spectre_params(CASES["exp"], "spectre"))["td2"] == "5n"
    assert dict(spectre_params(CASES["pulse"], "spectre"))["type"] == "pulse"


def test_verilog_a_uses_the_lrm_primitive_names():
    master, params = primitive(CASES["pulse"], current=False)
    assert master == "vpulse"
    assert params[:2] == [("dc", "0.9"), ("val0", "0")]
    assert ("td", "1n") in params
    assert primitive(CASES["dc"], current=True) == ("isine", [("dc", "1.8")])
    master, params = primitive(CASES["sffm"], current=False)
    assert master == "vsine" and ("fmmodindex", "2") in params
    assert dict(primitive(CASES["pwl"], current=False)[1])["wave"] == "'{0, 0, 1n, 1.8}"
    assert from_primitive("resistor", {}) is None


def test_attach_names_the_stimulus_after_its_source():
    nl = Netlist(top_circuit="top", circuits=[Circuit(name="top")])
    ref = SubCircuit(name="V1", circuit_name="vsource")
    attach(nl, "top", ref, stim(dc="1"))
    assert ref.properties["stimulus"] == "top/V1"
    assert stimulus_of(nl, ref) == nl.simulation.stimuli[0]
    assert nl.simulation.stimuli[0].name == "top/V1"
    assert stimulus_of(nl, SubCircuit(name="R1")) is None
