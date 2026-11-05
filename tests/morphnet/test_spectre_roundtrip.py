from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.spectre.writer import write_spectre


class TestSpectreTextRoundTrip:
    def test_resistor_divider(self) -> None:
        text = """\
subckt divider (vin vout gnd)
R1 (vin vout) resistor r=10k
R2 (vout gnd) resistor r=10k
ends divider
"""
        self.assert_roundtrip(text)

    def test_mosfet_inverter(self) -> None:
        text = """\
subckt inverter (in out vdd vss)
M1 (out in vdd vdd) pch w=1u l=0.18u
M2 (out in vss vss) nch w=0.5u l=0.18u
ends inverter
"""
        self.assert_roundtrip(text)

    def test_hierarchical(self) -> None:
        text = """\
subckt inverter (in out vdd vss)
R1 (in out) resistor r=1k
R2 (out vss) resistor r=1k
ends inverter

subckt buffer (a b vdd vss)
X1 (a mid vdd vss) inverter
X2 (mid b vdd vss) inverter
ends buffer
"""
        self.assert_roundtrip(text)

    def test_write_parse_write_stable(self) -> None:
        text = """\
subckt test (a b c)
R1 (a b) resistor r=10k
C1 (b c) capacitor c=100p
ends test
"""
        circuit1 = parse_spectre(text)
        written1 = write_spectre(circuit1)
        circuit2 = parse_spectre(written1)
        written2 = write_spectre(circuit2)
        assert written1 == written2

    def assert_roundtrip(self, text: str) -> None:
        circuit1 = parse_spectre(text)
        written = write_spectre(circuit1)
        circuit2 = parse_spectre(written)

        assert circuit1.top_circuit == circuit2.top_circuit
        assert len(circuit1.circuits) == len(circuit2.circuits)

        for m1, m2 in zip(circuit1.circuits, circuit2.circuits):
            assert m1.name == m2.name
            assert [p.name for p in m1.ports] == [p.name for p in m2.ports]
            assert len(m1.subcircuits) == len(m2.subcircuits)
            assert len(m1.connections) == len(m2.connections)

            for r1, r2 in zip(m1.subcircuits, m2.subcircuits):
                assert r1.name == r2.name
                assert r1.circuit_name == r2.circuit_name
