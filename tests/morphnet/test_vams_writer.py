from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    Connection,
    Directive,
    DirectiveKind,
    ExternalCircuit,
    ExternalCircuitKind,
    Circuit,
    SubCircuit,
    Parameter,
    ParameterValue,
    Port,
    PortDirection,
    PortReference,
    PrefixedValue,
    SignalDomain,
    SIPrefix,
)
from kfnetlist.morphnet.netlist.vams.writer import write_vams


def make_pv(val: float, prefix: SIPrefix = SIPrefix.UNSPECIFIED) -> ParameterValue:
    return ParameterValue(prefixed_value=PrefixedValue(double_value=val, prefix=prefix))


def make_port(
    name: str,
    direction: PortDirection = PortDirection.INOUT,
    discipline: str = "electrical",
) -> Port:
    return Port(
        name=name,
        direction=direction,
        domain=SignalDomain.ELECTRICAL,
        discipline=discipline,
    )


def make_conn(
    net: str, src_inst: str, src_port: str, tgt_inst: str, tgt_port: str
) -> Connection:
    return Connection(
        name=net,
        source=PortReference(instance_name=src_inst, port_name=src_port),
        target=PortReference(instance_name=tgt_inst, port_name=tgt_port),
    )


class TestModuleOutput:
    def test_simple_module(self) -> None:
        circ = Circuit(
            name="divider",
            ports=[make_port("vin"), make_port("vout"), make_port("gnd")],
            subcircuits=[
                SubCircuit(
                    name="R1",
                    circuit_name="resistor",
                    parameters=[
                        Parameter(name="r", default_value=make_pv(10.0, SIPrefix.KILO))
                    ],
                ),
            ],
            connections=[
                make_conn("vin", "", "vin", "R1", "p"),
                make_conn("vout", "", "vout", "R1", "n"),
            ],
        )
        netlist = Netlist(name="", top_circuit="divider", circuits=[circ])
        output = write_vams(netlist)
        assert "module divider" in output
        assert "endmodule" in output
        assert "inout vin, vout, gnd;" in output
        assert "electrical vin, vout, gnd;" in output
        assert "resistor" in output
        assert "R1" in output


class TestDirectiveOutput:
    def test_include(self) -> None:
        netlist = Netlist(
            name="",
            directives=[Directive(kind=DirectiveKind.INCLUDE, value="models.vams")],
        )
        output = write_vams(netlist)
        assert '`include "models.vams"' in output

    def test_timescale(self) -> None:
        netlist = Netlist(
            name="",
            directives=[Directive(kind=DirectiveKind.TIMESCALE, value="1ns/1ps")],
        )
        output = write_vams(netlist)
        assert "`timescale 1ns/1ps" in output


class TestParameterOutput:
    def test_typed_parameter(self) -> None:
        circ = Circuit(
            name="test",
            ports=[make_port("a")],
            parameters=[
                Parameter(
                    name="r",
                    default_value=make_pv(50.0),
                    properties={"type": "real"},
                ),
            ],
        )
        netlist = Netlist(name="", top_circuit="test", circuits=[circ])
        output = write_vams(netlist)
        assert "parameter real r = 50" in output


class TestNatureAndDisciplineOutput:
    def test_nature(self) -> None:
        ext = ExternalCircuit(
            name="Voltage",
            kind=ExternalCircuitKind.NATURE,
            properties={"nature_units": "V", "nature_access": "V"},
        )
        netlist = Netlist(name="", ext_circuits=[ext])
        output = write_vams(netlist)
        assert "nature Voltage;" in output
        assert "endnature" in output
        assert "units = V;" in output

    def test_discipline(self) -> None:
        ext = ExternalCircuit(
            name="electrical",
            kind=ExternalCircuitKind.DISCIPLINE,
            properties={
                "discipline_potential": "Voltage",
                "discipline_flow": "Current",
                "discipline_domain": "continuous",
            },
        )
        netlist = Netlist(name="", ext_circuits=[ext])
        output = write_vams(netlist)
        assert "discipline electrical;" in output
        assert "enddiscipline" in output
        assert "domain continuous;" in output
        assert "potential Voltage;" in output


class TestNativeSimulationForms:
    def test_a_gsch_schematic_is_written_with_native_verilog_ams(self) -> None:
        from pathlib import Path

        from kfnetlist.morphnet.netlist import parse_vams, read_gsch

        gsch = Path(__file__).parent / "netlists" / "gsch" / "ihp_hier_top.gsch"
        nl = read_gsch(gsch, corners=["mos_ff"])
        text = write_vams(nl)
        assert "Mprim #(" in text  # a `.model` name is the module (LRM E.2.2.1)
        assert "paramset Mprim mosfet;" in text  # ... of a primitive (LRM 7.5)
        assert "vsine #(.dc(1.8)) V2" in text  # a DC source (LRM E.2.2.3)
        assert "vpulse #(.dc(0.9), .val0(0), .val1(1.8), .td(1n)" in text
        assert (
            '(* spice_lib = "ihp/models/ngspice/models/cornerMOSlv.lib mos_ff' in text
        )
        assert "ground GND;" in text
        back = parse_vams(text)
        assert {(d.kind.name, d.value) for d in back.directives} >= {
            ("LIB", "ihp/models/ngspice/models/cornerMOSlv.lib mos_ff"),
            ("INCLUDE", "pdk/models/mprim.lib"),
        }
        assert len(back.simulation.stimuli) == 3

    def test_node_sets_are_net_initializers(self) -> None:
        from kfnetlist.morphnet.morphnet_schema import InitialCondition, Simulation
        from kfnetlist.morphnet.netlist import parse_vams

        nl = parse_vams(
            "module t (a);\n  inout a;\n  resistor #(.r(1k)) R1 (.p(a), .n(b));\nendmodule\n"
        )
        nl.simulation = Simulation(node_sets=InitialCondition(conditions={"V(b)": "5"}))
        text = write_vams(nl)
        assert "electrical b = 5;" in text
        assert parse_vams(text).simulation.node_sets.conditions == {"V(b)": "5"}

    def test_a_model_instance_reads_back_as_its_primitive(self) -> None:
        from kfnetlist.morphnet.netlist import parse_spice, parse_vams

        nl = parse_spice("* t\nM1 d g s b pch w=1u\n.end\n")
        back = parse_vams(write_vams(nl))
        (m1,) = back.circuits[0].subcircuits
        assert (m1.circuit_name, m1.properties["model_name"]) == ("mosfet", "pch")
