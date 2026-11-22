from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    Connection,
    Directive,
    DirectiveKind,
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
from kfnetlist.morphnet.netlist.expression import parse_expression
from kfnetlist.morphnet.netlist.hspice.writer import write_hspice
from kfnetlist.morphnet.netlist.spice.writer import write_spice
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


def expr(text: str) -> ParameterValue:
    return ParameterValue(expression=parse_expression(text))


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
            name="test_circuit",
            top_circuit="test",
            circuits=[circ],
            ext_circuits=[resistor],
        )
        output = write_spice(netlist)
        assert ".subckt test a b" in output
        assert "R1 a b 10k" in output
        assert ".ends test" in output
        assert ".end" in output


class TestMosfetOutput:
    def test_mosfet_with_model(self) -> None:
        mosfet = ExternalCircuit(
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
            ext_circuits=[mosfet],
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
        nch = ExternalCircuit(
            name="nch",
            parameters=[
                Parameter(name="level", default_value=make_pv(49.0)),
                Parameter(name="vth0", default_value=make_pv(0.4)),
            ],
            properties={"model_type": "nmos"},
        )
        netlist = Netlist(name="test", ext_circuits=[nch])
        output = write_spice(netlist)
        assert ".model nch nmos" in output
        assert "level=49" in output
        assert "vth0=0.4" in output


def _prim_netlist(
    inst: str = "R1",
    params: list[Parameter] | None = None,
    nets: tuple[str, str] = ("a", "b"),
    props: dict[str, str] | None = None,
    inst_props: dict[str, str] | None = None,
    ext_props: dict[str, str] | None = None,
) -> Netlist:
    resistor = ExternalCircuit(
        name="resistor",
        ports=[make_port("p"), make_port("n")],
        properties=ext_props if ext_props is not None else {"spice_prefix": "R"},
    )
    circ = Circuit(
        name="test",
        ports=[make_port("a"), make_port("b")],
        subcircuits=[
            SubCircuit(
                name=inst,
                circuit_name="resistor",
                parameters=params or [],
                properties=inst_props or {},
            )
        ],
        connections=[
            make_conn(nets[0], "", "a", inst, "p"),
            make_conn(nets[1], "", "b", inst, "n"),
        ],
    )
    return Netlist(
        name="t",
        top_circuit="test",
        circuits=[circ],
        ext_circuits=[resistor],
        properties=props or {},
    )


class TestExprParameters:
    def test_expr_is_positional_value_and_kv(self) -> None:
        nl = _prim_netlist(
            params=[
                Parameter(name="value", default_value=expr("DC 1 AC 1")),  # raw
                Parameter(name="w", default_value=expr("{w*1e-6}")),
            ]
        )
        assert "R1 a b DC 1 AC 1 w={w * 1e-6}" in write_spice(nl)

    def test_expr_on_header_and_call_params(self) -> None:
        inner = Circuit(
            name="inner",
            ports=[make_port("p")],
            parameters=[Parameter(name="k", default_value=expr("2*x"))],
        )
        outer = Circuit(
            name="outer",
            ports=[make_port("a")],
            subcircuits=[
                SubCircuit(
                    name="X1",
                    circuit_name="inner",
                    parameters=[Parameter(name="k", default_value=expr("{3*y}"))],
                )
            ],
            connections=[make_conn("a", "", "a", "X1", "p")],
        )
        out = write_spice(Netlist(name="t", circuits=[inner, outer]))
        assert ".subckt inner p k={2 * x}" in out
        assert "X1 a inner k={3 * y}" in out

    def test_each_dialect_wraps_its_own_way(self) -> None:
        nl = _prim_netlist(params=[Parameter(name="w", default_value=expr("w*2"))])
        assert "w={w * 2}" in write_spice(nl)
        assert "w={w * 2}" in write_xyce(nl)
        assert "w='w * 2'" in write_hspice(nl)

    def test_a_bare_reference_or_literal_is_not_wrapped(self) -> None:
        params = [
            Parameter(name="w", default_value=expr("wmin")),
            Parameter(name="l", default_value=expr("2.2u")),
        ]
        assert "w=wmin l=2.2u" in write_spice(_prim_netlist(params=params))


class TestSpicePrefix:
    def test_prefix_prepended_when_missing(self) -> None:
        out = write_spice(_prim_netlist(inst="load"))
        assert "\nRload a b" in out

    def test_prefix_not_duplicated_case_insensitive(self) -> None:
        out = write_spice(_prim_netlist(inst="r_load"))
        assert "\nr_load a b" in out
        assert "Rr_load" not in out

    def test_defined_circuit_gets_x(self) -> None:
        inner = Circuit(name="inner", ports=[make_port("p")])
        outer = Circuit(
            name="outer",
            ports=[make_port("a")],
            subcircuits=[SubCircuit(name="amp", circuit_name="inner")],
            connections=[make_conn("a", "", "a", "amp", "p")],
        )
        out = write_spice(Netlist(name="t", circuits=[inner, outer]))
        assert "\nXamp a inner" in out


class TestGroundNet:
    def test_ground_is_node_zero_header_unchanged(self) -> None:
        circ = Circuit(
            name="blk",
            ports=[make_port("GND"), make_port("b")],
            subcircuits=[
                SubCircuit(
                    name="R1",
                    circuit_name="resistor",
                    parameters=[Parameter(name="value", default_value=expr("1k"))],
                )
            ],
            connections=[
                make_conn("GND", "", "GND", "R1", "p"),
                make_conn("b", "", "b", "R1", "n"),
            ],
        )
        resistor = ExternalCircuit(
            name="resistor",
            ports=[make_port("p"), make_port("n")],
            properties={"spice_prefix": "R"},
        )
        nl = Netlist(
            name="t",
            circuits=[circ],
            ext_circuits=[resistor],
            properties={"ground_net": "GND"},
        )
        out = write_spice(nl)
        assert ".subckt blk GND b" in out
        assert "R1 0 b 1k" in out

    def test_ground_at_top(self) -> None:
        nl = _prim_netlist(nets=("GND", "b"), props={"ground_net": "GND"})
        nl.circuits[0].name = "__top__"
        assert "R1 0 b" in write_spice(nl)


class TestSubcktHeaderParams:
    def test_params_on_header_not_body(self) -> None:
        inner = Circuit(
            name="inner",
            ports=[make_port("p"), make_port("q")],
            parameters=[Parameter(name="r", default_value=make_pv(1.0, SIPrefix.KILO))],
        )
        out = write_spice(Netlist(name="t", circuits=[inner]))
        assert ".subckt inner p q r=1k" in out
        assert ".param" not in out


class TestSimSkip:
    def test_sim_skip_instance_omitted(self) -> None:
        nl = _prim_netlist(inst_props={"sim_skip": "1"})
        out = write_spice(nl)
        assert "R1" not in out


class TestSpiceLibDirective:
    def test_lib_path_section(self) -> None:
        nl = Netlist(
            name="t",
            directives=[Directive(kind=DirectiveKind.LIB, value="m.lib tt")],
        )
        assert ".lib m.lib tt" in write_spice(nl)


def test_an_empty_expression_is_not_written() -> None:
    nl = _prim_netlist(
        params=[Parameter(name="w", default_value=expr("")), Parameter(name="n")]
    )
    assert "R1 a b\n" in write_spice(nl)  # no `w=`
