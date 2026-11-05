from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    Connection,
    Directive,
    DirectiveKind,
    ExternalModule,
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
from kfnetlist.morphnet.netlist.spice.writer import write_spice


def make_port(name: str) -> Port:
    return Port(
        name=name,
        direction=PortDirection.INOUT,
        domain=SignalDomain.ELECTRICAL,
    )


def make_pv(value: float, prefix: SIPrefix = SIPrefix.UNSPECIFIED) -> ParameterValue:
    return ParameterValue(
        prefixed_value=PrefixedValue(double_value=value, prefix=prefix)
    )


def make_conn(
    net: str, src_inst: str, src_port: str, tgt_inst: str, tgt_port: str
) -> Connection:
    return Connection(
        name=net,
        source=PortReference(instance_name=src_inst, port_name=src_port),
        target=PortReference(instance_name=tgt_inst, port_name=tgt_port),
    )


class TestResistorOutput:
    def test_basic_resistor(self) -> None:
        resistor = ExternalModule(
            name="resistor",
            ports=[make_port("p"), make_port("n")],
            properties={"spice_prefix": "R"},
        )
        circ = Circuit(
            name="test",
            ports=[make_port("a"), make_port("b")],
            subcircuits=[
                SubCircuit(
                    name="R1",
                    circuit_name="resistor",
                    parameters=[
                        Parameter(
                            name="value",
                            default_value=make_pv(10.0, SIPrefix.KILO),
                        )
                    ],
                ),
            ],
            connections=[
                make_conn("a", "", "a", "R1", "p"),
                make_conn("b", "", "b", "R1", "n"),
            ],
        )
        netlist = Netlist(
            name="test_circuit",
            top_circuit="test",
            circuits=[circ],
            ext_modules=[resistor],
        )
        output = write_spice(netlist)
        assert ".subckt test a b" in output
        assert "R1 a b 10k" in output
        assert ".ends test" in output
        assert ".end" in output


class TestMosfetOutput:
    def test_mosfet_with_model(self) -> None:
        mosfet = ExternalModule(
            name="mosfet",
            ports=[
                make_port("d"),
                make_port("g"),
                make_port("s"),
                make_port("b"),
            ],
            properties={"spice_prefix": "M"},
        )
        circ = Circuit(
            name="inv",
            ports=[
                make_port("in_"),
                make_port("out"),
                make_port("vdd"),
                make_port("vss"),
            ],
            subcircuits=[
                SubCircuit(
                    name="M1",
                    circuit_name="mosfet",
                    properties={"model_name": "pch"},
                    parameters=[
                        Parameter(name="W", default_value=make_pv(1.0, SIPrefix.MICRO)),
                        Parameter(
                            name="L", default_value=make_pv(0.18, SIPrefix.MICRO)
                        ),
                    ],
                ),
            ],
            connections=[
                make_conn("out", "", "out", "M1", "d"),
                make_conn("in_", "", "in_", "M1", "g"),
                make_conn("vdd", "", "vdd", "M1", "s"),
                make_conn("vdd", "", "vdd", "M1", "b"),
            ],
        )
        netlist = Netlist(
            name="test",
            top_circuit="inv",
            circuits=[circ],
            ext_modules=[mosfet],
        )
        output = write_spice(netlist)
        assert "M1 out in_ vdd vdd pch W=1u L=0.18u" in output


class TestSubcircuitInstance:
    def test_x_instance(self) -> None:
        inner = Circuit(
            name="inner",
            ports=[make_port("p"), make_port("q")],
        )
        outer = Circuit(
            name="outer",
            ports=[make_port("a"), make_port("b")],
            subcircuits=[
                SubCircuit(name="X1", circuit_name="inner"),
            ],
            connections=[
                make_conn("a", "", "a", "X1", "p"),
                make_conn("b", "", "b", "X1", "q"),
            ],
        )
        netlist = Netlist(
            name="test",
            top_circuit="outer",
            circuits=[inner, outer],
        )
        output = write_spice(netlist)
        assert "X1 a b inner" in output


class TestDirectiveOutput:
    def test_include(self) -> None:
        netlist = Netlist(
            name="test",
            directives=[Directive(kind=DirectiveKind.INCLUDE, value="models.lib")],
        )
        output = write_spice(netlist)
        assert '.include "models.lib"' in output

    def test_global(self) -> None:
        netlist = Netlist(
            name="test",
            directives=[Directive(kind=DirectiveKind.GLOBAL, value="VDD VSS")],
        )
        output = write_spice(netlist)
        assert ".global VDD VSS" in output

    def test_model(self) -> None:
        nch = ExternalModule(
            name="nch",
            parameters=[
                Parameter(name="level", default_value=make_pv(49.0)),
                Parameter(name="vth0", default_value=make_pv(0.4)),
            ],
            properties={"model_type": "nmos"},
        )
        netlist = Netlist(name="test", ext_modules=[nch])
        output = write_spice(netlist)
        assert ".model nch nmos" in output
        assert "level=49" in output
        assert "vth0=0.4" in output
