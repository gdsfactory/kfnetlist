from kfnetlist.morphnet.netlist.xyce.parser import parse_xyce


class TestBasicParsing:
    def test_resistor_divider(self) -> None:
        text = """\
.SUBCKT divider vin vout gnd
R1 vin vout 10k
R2 vout gnd 10k
.ENDS divider
.END
"""
        netlist = parse_xyce(text)
        assert netlist.top_circuit == "divider"
        assert len(netlist.circuits) == 1

    def test_params_keyword(self) -> None:
        """Xyce .SUBCKT with PARAMS: keyword."""
        text = """\
.SUBCKT myres in out PARAMS: R=1k
R1 in out {R}
.ENDS myres
.END
"""
        netlist = parse_xyce(text)
        m = netlist.circuits[0]
        assert m.name == "myres"
        assert [p.name for p in m.ports] == ["in", "out"]

    def test_case_insensitive(self) -> None:
        text = """\
.subckt test a b
R1 a b 1k
.ends test
.end
"""
        netlist = parse_xyce(text)
        assert netlist.circuits[0].name == "test"


class TestDeviceTypes:
    def test_mosfet(self) -> None:
        text = """\
.SUBCKT inv in out vdd vss
M1 out in vdd vdd pch W=1u L=0.18u
M2 out in vss vss nch W=0.5u L=0.18u
.ENDS inv
.END
"""
        netlist = parse_xyce(text)
        refs = netlist.circuits[0].subcircuits
        assert refs[0].circuit_name == "mosfet"
        assert refs[0].properties.get("model_name") == "pch"


class TestDirectives:
    def test_include(self) -> None:
        text = """\
.INCLUDE "models.lib"
.SUBCKT test a b
R1 a b 1k
.ENDS test
.END
"""
        netlist = parse_xyce(text)
        includes = [d for d in netlist.directives if d.kind.name == "INCLUDE"]
        assert len(includes) >= 1
        assert includes[0].value == "models.lib"

    def test_model_statement(self) -> None:
        text = """\
.MODEL nch nmos level=49 vth0=0.4
.SUBCKT test d g s b
M1 d g s b nch W=1u L=0.18u
.ENDS test
.END
"""
        netlist = parse_xyce(text)
        ext_names = {e.name for e in netlist.ext_circuits}
        assert "nch" in ext_names
