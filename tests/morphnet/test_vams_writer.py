from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    Connection,
    Directive,
    DirectiveKind,
    ExternalModule,
    ExternalModuleKind,
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
        ext = ExternalModule(
            name="Voltage",
            kind=ExternalModuleKind.NATURE,
            properties={"nature_units": "V", "nature_access": "V"},
        )
        netlist = Netlist(name="", ext_modules=[ext])
        output = write_vams(netlist)
        assert "nature Voltage;" in output
        assert "endnature" in output
        assert "units = V;" in output

    def test_discipline(self) -> None:
        ext = ExternalModule(
            name="electrical",
            kind=ExternalModuleKind.DISCIPLINE,
            properties={
                "discipline_potential": "Voltage",
                "discipline_flow": "Current",
                "discipline_domain": "continuous",
            },
        )
        netlist = Netlist(name="", ext_modules=[ext])
        output = write_vams(netlist)
        assert "discipline electrical;" in output
        assert "enddiscipline" in output
        assert "domain continuous;" in output
        assert "potential Voltage;" in output
