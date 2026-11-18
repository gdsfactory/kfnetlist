from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    Connection,
    ExternalCircuit,
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
from kfnetlist.morphnet.netlist.xyce.writer import write_xyce


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


class TestXyceFormat:
    def test_basic_output(self) -> None:
        """Xyce output matches SPICE format."""
        resistor = ExternalCircuit(
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
            name="test",
            top_circuit="test",
            circuits=[circ],
            ext_circuits=[resistor],
        )
        output = write_xyce(netlist)
        assert ".subckt test a b" in output
        assert "R1 a b 10k" in output
        assert ".ends test" in output


def _sub_call_netlist() -> Netlist:
    inner = Circuit(
        name="sub",
        ports=[make_port("p"), make_port("q")],
        parameters=[Parameter(name="w", default_value=make_pv(1.0))],
    )
    plain = Circuit(name="plain", ports=[make_port("p")])
    outer = Circuit(
        name="outer",
        ports=[make_port("a"), make_port("b")],
        subcircuits=[
            SubCircuit(
                name="X1",
                circuit_name="sub",
                parameters=[Parameter(name="w", default_value=make_pv(2.0))],
            ),
            SubCircuit(name="X2", circuit_name="plain"),
        ],
        connections=[
            make_conn("a", "", "a", "X1", "p"),
            make_conn("b", "", "b", "X1", "q"),
            make_conn("a", "", "a", "X2", "p"),
        ],
    )
    return Netlist(name="t", top_circuit="outer", circuits=[inner, plain, outer])


class TestXyceParamsKeyword:
    def test_subckt_header_params(self) -> None:
        out = write_xyce(_sub_call_netlist())
        assert ".subckt sub p q PARAMS: w=1" in out
        assert ".subckt plain p\n" in out

    def test_call_params(self) -> None:
        out = write_xyce(_sub_call_netlist())
        assert "X1 a b sub PARAMS: w=2" in out
        assert "X2 a plain\n" in out

    def test_parse_accepts_params_keyword(self) -> None:
        from kfnetlist.morphnet.netlist.xyce.parser import parse_xyce

        nl = parse_xyce(write_xyce(_sub_call_netlist()))
        outer = next(c for c in nl.circuits if c.name == "outer")
        assert outer.subcircuits[0].circuit_name == "sub"
        assert [p.name for p in outer.subcircuits[0].parameters] == ["w"]
        sub = next(c for c in nl.circuits if c.name == "sub")
        assert [p.name for p in sub.ports] == ["p", "q"]
        assert [p.name for p in sub.parameters] == ["w"]

    def test_parse_x_call_with_params_keyword(self) -> None:
        from kfnetlist.morphnet.netlist.xyce.parser import parse_xyce

        nl = parse_xyce(
            ".subckt sub p q PARAMS: w=1\n.ends sub\n"
            ".subckt top a b\nX1 a b sub PARAMS: w=2\n.ends top\n"
        )
        x1 = nl.circuits[1].subcircuits[0]
        assert x1.circuit_name == "sub"
        assert [p.name for p in x1.parameters] == ["w"]

    def test_round_trip_stable(self) -> None:
        from kfnetlist.morphnet.netlist.xyce.parser import parse_xyce

        first = write_xyce(parse_xyce(write_xyce(_sub_call_netlist())))
        assert write_xyce(parse_xyce(first)) == first
        assert "PARAMS:" in first

    def test_spice_and_hspice_keep_no_keyword(self) -> None:
        from kfnetlist.morphnet.netlist.hspice.writer import write_hspice
        from kfnetlist.morphnet.netlist.spice.writer import write_spice

        for out in (
            write_spice(_sub_call_netlist()),
            write_hspice(_sub_call_netlist()),
        ):
            assert "PARAMS:" not in out
            assert ".subckt sub p q w=1" in out
