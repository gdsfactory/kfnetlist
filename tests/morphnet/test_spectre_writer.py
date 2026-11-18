from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    Connection,
    Directive,
    DirectiveKind,
    ExternalCircuit,
    Circuit,
    SubCircuit,
    Parameter,
    Port,
    PortDirection,
    PortReference,
    PrefixedValue,
    SignalDomain,
    SIPrefix,
    ParameterValue,
)
from kfnetlist.morphnet.netlist.spectre.writer import write_spectre


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


class TestSpectreFormat:
    def test_subckt_with_parens(self) -> None:
        circ = Circuit(
            name="test",
            ports=[make_port("a"), make_port("b")],
        )
        netlist = Netlist(name="test", top_circuit="test", circuits=[circ])
        output = write_spectre(netlist)
        assert "subckt test (a b)" in output
        assert "ends test" in output

    def test_instance_with_parens(self) -> None:
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
                        Parameter(name="r", default_value=make_pv(10.0, SIPrefix.KILO))
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
        output = write_spectre(netlist)
        assert "R1 (a b) resistor r=10k" in output

    def test_x_instance(self) -> None:
        inner = Circuit(name="inner", ports=[make_port("p"), make_port("q")])
        outer = Circuit(
            name="outer",
            ports=[make_port("a"), make_port("b")],
            subcircuits=[SubCircuit(name="X1", circuit_name="inner")],
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
        output = write_spectre(netlist)
        assert "X1 (a b) inner" in output


def _prim_netlist(
    inst: str = "R1",
    params: list[Parameter] | None = None,
    nets: tuple[str, str] = ("a", "b"),
    props: dict[str, str] | None = None,
    inst_props: dict[str, str] | None = None,
    circuit_name: str = "resistor",
) -> Netlist:
    resistor = ExternalCircuit(
        name=circuit_name,
        ports=[make_port("p"), make_port("n")],
        properties={"spice_prefix": "R"},
    )
    circ = Circuit(
        name="test",
        ports=[make_port("a"), make_port("b")],
        subcircuits=[
            SubCircuit(
                name=inst,
                circuit_name=circuit_name,
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
    def test_expr_verbatim_not_dropped(self) -> None:
        nl = _prim_netlist(
            params=[
                Parameter(name="r", properties={"expr": "{w*1e-6}"}),
                Parameter(name="dc", properties={"expr": "1.8"}),
            ]
        )
        assert "R1 (a b) resistor r={w*1e-6} dc=1.8" in write_spectre(nl)

    def test_expr_wins_over_numeric_default(self) -> None:
        nl = _prim_netlist(
            params=[
                Parameter(
                    name="r", default_value=make_pv(5.0), properties={"expr": "{w*2}"}
                )
            ]
        )
        assert "R1 (a b) resistor r={w*2}" in write_spectre(nl)

    def test_expr_on_subckt_header(self) -> None:
        inner = Circuit(
            name="inner",
            ports=[make_port("p")],
            parameters=[Parameter(name="k", properties={"expr": "2*x"})],
        )
        assert "subckt inner (p) k=2*x" in write_spectre(
            Netlist(name="t", circuits=[inner])
        )


class TestGroundNet:
    def test_ground_net_is_node_zero(self) -> None:
        nl = _prim_netlist(nets=("GND", "b"), props={"ground_net": "GND"})
        out = write_spectre(nl)
        assert "R1 (0 b) resistor" in out
        assert "subckt test (a b)" in out

    def test_ground_statement_only_for_vacask(self) -> None:
        nl = _prim_netlist(props={"ground_net": "GND", "dialect": "vacask"})
        assert "ground 0" in write_spectre(nl).splitlines()[:3]
        nl = _prim_netlist(props={"ground_net": "GND"})
        assert "ground 0" not in write_spectre(nl)


class TestVacaskDialect:
    def test_lowercase_instance_names(self) -> None:
        nl = _prim_netlist(inst="R_Load", props={"dialect": "vacask"})
        assert "\nr_load (a b)" in write_spectre(nl)
        nl = _prim_netlist(inst="R_Load")
        assert "\nR_Load (a b)" in write_spectre(nl)

    def test_value_maps_to_device_param(self) -> None:
        nl = _prim_netlist(
            params=[
                Parameter(name="value", properties={"expr": "1k"}),
                Parameter(name="tc1", properties={"expr": "0"}),
            ],
            props={"dialect": "vacask"},
        )
        assert "r1 (a b) resistor r=1k tc1=0" in write_spectre(nl)

    def test_value_kept_without_vacask(self) -> None:
        nl = _prim_netlist(params=[Parameter(name="value", properties={"expr": "1k"})])
        assert "R1 (a b) resistor value=1k" in write_spectre(nl)

    def test_source_params_pass_through(self) -> None:
        nl = _prim_netlist(
            params=[
                Parameter(name="dc", properties={"expr": "1"}),
                Parameter(name="mag", properties={"expr": "1"}),
            ],
            circuit_name="vsource",
            props={"dialect": "vacask"},
        )
        assert "r1 (a b) vsource dc=1 mag=1" in write_spectre(nl)


class TestSimSkip:
    def test_sim_skip_instance_omitted(self) -> None:
        nl = _prim_netlist(inst_props={"sim_skip": "1"})
        assert "R1" not in write_spectre(nl)


class TestLibDirective:
    def test_lib_with_section(self) -> None:
        nl = Netlist(
            name="t",
            directives=[Directive(kind=DirectiveKind.LIB, value="m.scs tt")],
        )
        assert 'include "m.scs" section=tt' in write_spectre(nl).splitlines()

    def test_lib_with_lang(self) -> None:
        nl = Netlist(
            name="t",
            directives=[
                Directive(kind=DirectiveKind.LIB, value="m.lib tt", name="lang=ngspice")
            ],
        )
        assert 'include "m.lib" section=tt lang=ngspice' in write_spectre(nl)

    def test_include_with_lang(self) -> None:
        nl = Netlist(
            name="t",
            directives=[
                Directive(
                    kind=DirectiveKind.INCLUDE, value="m.lib", name="lang=ngspice"
                )
            ],
        )
        assert 'include "m.lib" lang=ngspice' in write_spectre(nl).splitlines()
