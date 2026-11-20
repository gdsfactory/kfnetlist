"""kfnetlist Netlists <-> morphnet Netlists <-> SPICE / Spectre / Verilog-AMS text."""

import json
from functools import partial
from pathlib import Path

import pytest

from kfnetlist import Netlist, NetlistPort, PortRef, morphnet
from kfnetlist.kfnetlist_schema import NetlistDocument, ProtoNetlist
from kfnetlist.morphnet.morphnet_schema import circuit_pb2 as pb
from kfnetlist.morphnet.netlist.expression import parse_expression
from kfnetlist.morphnet.netlist import (
    parse_gsch,
    parse_spectre,
    parse_spice,
    parse_systemverilog,
    parse_vams,
    write_gsch,
    write_spectre,
    write_spice,
    write_systemverilog,
    write_vams,
)


def rc() -> Netlist:
    nl = Netlist()
    nl.create_inst("R1", kcl="", component="resistor", settings={"value": 1000.0})
    nl.create_inst("C1", kcl="", component="capacitor", settings={"value": 1e-10})
    for port in ("vin", "vout", "gnd"):
        nl.create_port(port)
    nl.create_net(NetlistPort("vin"), PortRef("R1", "p"))
    nl.create_net(PortRef("R1", "n"), PortRef("C1", "p"), NetlistPort("vout"))
    nl.create_net(PortRef("C1", "n"), NetlistPort("gnd"))
    nl.sort()
    return nl


def connectivity(nl: Netlist, fold_pin_case: bool = False):
    nl.sort()
    instances = {k: (v.component, v.settings) for k, v in nl.instances.items()}
    if fold_pin_case:  # Mosaic spells the pins of its symbols uppercase
        nets = {
            frozenset(
                m.name if isinstance(m, NetlistPort) else (m.instance, m.port.upper())
                for m in net
            )
            for net in nl.nets
        }
        return nets, nl.ports, instances
    return nl.nets, nl.ports, instances


def test_direct_round_trip_is_exact():
    nl = rc()
    back = morphnet.to_netlists(morphnet.from_netlists({"rc": nl}))["rc"]
    back.sort()
    assert back == nl


@pytest.mark.parametrize(
    ("write", "parse", "fold_pin_case"),
    [
        (write_spice, parse_spice, False),
        (write_spectre, parse_spectre, False),
        (write_vams, parse_vams, False),
        (write_systemverilog, parse_systemverilog, False),
        (
            write_gsch,
            partial(parse_gsch, name="rc"),
            True,
        ),  # no circuit name in a .gsch
    ],
)
def test_every_format_round_trips_connectivity(write, parse, fold_pin_case):
    nl = rc()
    text = write(morphnet.from_netlists({"rc": nl}, "rc"))
    back = morphnet.to_netlists(parse(text))["rc"]
    assert connectivity(back, fold_pin_case) == connectivity(nl, fold_pin_case)


def test_positional_writers_use_device_pin_order():
    text = write_spectre(morphnet.from_netlists({"rc": rc()}, "rc"))
    assert "C1 (vout gnd) capacitor" in text


def test_parsed_spice_becomes_a_netlist_with_si_values():
    netlist = parse_spice(
        ".subckt rc in_ out gnd\nR1 in_ out 1k\nC1 out gnd 100p\n.ends rc\n"
    )
    nl = morphnet.to_netlists(netlist)["rc"]
    assert nl.instances["R1"].settings["value"] == pytest.approx(1000.0)
    assert nl.instances["C1"].settings["value"] == pytest.approx(1e-10)
    nets = {
        frozenset(
            m.name if isinstance(m, NetlistPort) else f"{m.instance}.{m.port}"
            for m in n
        )
        for n in nl.nets
    }
    assert nets == {
        frozenset({"in_", "R1.p"}),
        frozenset({"out", "R1.n", "C1.p"}),
        frozenset({"gnd", "C1.n"}),
    }


def _assert_schema_keys(obj: dict, descriptor) -> None:
    """Every key is a field of the matching circuit.proto message, recursively."""
    fields = {f.name: f for f in descriptor.fields}
    assert set(obj) <= set(fields), set(obj) - set(fields)
    for key, value in obj.items():
        message = fields[key].message_type
        if message is None or value is None:
            continue
        if message.GetOptions().map_entry:
            value_type = message.fields_by_name["value"].message_type
            items = value.values() if value_type else []
            descriptor_of_item = value_type
        else:
            items = value if isinstance(value, list) else [value]
            descriptor_of_item = message
        for item in items:
            _assert_schema_keys(item, descriptor_of_item)


def _schema_netlists() -> list[morphnet.Netlist]:
    fixtures = Path(__file__).parent / "morphnet" / "netlists"
    built = morphnet.from_netlists({"rc": rc()}, "rc")
    return [built] + [
        morphnet.Netlist.from_yaml(f.read_text())
        for f in sorted(fixtures.glob("*.yaml"))
    ]


@pytest.mark.parametrize("netlist", _schema_netlists())
def test_json_matches_the_kfnetlist_schema(netlist):
    assert ProtoNetlist.from_json(netlist.to_json()) == ProtoNetlist.from_proto(
        netlist.to_proto_bytes()
    )
    _assert_schema_keys(json.loads(netlist.to_json()), pb.Netlist.DESCRIPTOR)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Module", "Circuit"),
        ("ModuleReference", "SubCircuit"),
        ("module", "circuit"),
        ("module_reference", "subcircuit"),
        ("circuit_from_netlists", "from_netlists"),
        ("circuit_to_netlists", "to_netlists"),
        ("ExternalModule", "ExternalCircuit"),
        ("ExternalModuleKind", "ExternalCircuitKind"),
        ("ext_module", "ext_circuit"),
    ],
)
def test_pre_rename_names_warn(old, new):
    with pytest.warns(DeprecationWarning, match=f"use {new}"):
        assert getattr(morphnet, old) is getattr(morphnet, new)


def test_pre_rename_yaml_keys_still_load():
    old = """\
top_module: rc
modules:
- name: rc
  module_references:
  - name: R1
    module_name: resistor
ext_modules:
- name: resistor
"""
    netlist = morphnet.Netlist.from_yaml(old)
    assert netlist.top_circuit == "rc"
    assert netlist.circuits[0].subcircuits[0].circuit_name == "resistor"
    assert netlist.ext_circuits[0].name == "resistor"


# ---- lossless bridge: from_netlists(to_netlists(nl)) writes the same text ----

_FIXTURES = Path(__file__).parent / "morphnet" / "netlists"
_SPICE = """\
* lossless
.include "models.lib"
.lib "corners.lib" tt
.global VDD VSS
.option scale=1u
.param vdd=1.8
.model nch nmos level=49 vth0=0.4
.subckt inv in_ out vdd vss
M1 out in_ vdd vdd pch W=1u L=0.18u
M2 out in_ vss vss nch W=0.5u L=0.18u
.ends inv
.subckt buf a b vdd vss
.param ratio=2
X1 a mid vdd vss inv
X2 mid b vdd vss inv
R1 b n1 1k
C1 n1 0 100p
.ends buf
.end
"""
_XYCE = """\
.subckt divider vin vout gnd
R1 vin vout 10k
R2 vout gnd 10k
.ends divider
.end
"""
# Insertion-ordered maps: nature properties (not sorted) and behavioral blocks.
_VAMS_NATURE = """\
nature Voltage;
  units = "V";
  access = V;
  abstol = 1u;
endnature
module test (a);
  inout a;
endmodule
"""
_SV_BLOCKS = """\
module top (input clk, output reg q);
  always_ff @(posedge clk) begin
    if (q) q <= 1'b0; else q <= 1'b1;
  end
  always @(*) case (q) 1'b0: q = 1; default: q = 0; endcase
  initial q = 0;
  assign q = clk & q;
  r X1 (.p(clk), .n(q));
endmodule
"""
_SPECTRE_SPICE = """\
simulator lang=spice
.subckt rc in_ out gnd
R1 in_ out 1k
C1 out gnd 100p
.ends rc
"""


def _parse(path: Path) -> morphnet.Netlist:
    from kfnetlist.morphnet.netlist import parse_hspice

    text = path.read_text()
    if path.suffix == ".sv":
        domains = {
            "connection": morphnet.SignalDomain.WAVEGUIDE,
            "mzmselect": morphnet.SignalDomain.ELECTRICAL,
        }
        return parse_systemverilog(text, disciplines=domains)
    if path.suffix == ".yaml":
        return morphnet.Netlist.from_yaml(text)
    parse = {".sp": parse_hspice, ".scs": parse_spectre, ".vams": parse_vams}
    return parse[path.suffix](text)


def _bus_ir() -> morphnet.Netlist:
    """Buses and foreign `__x` properties on an instance, a circuit and a connection."""
    from kfnetlist.morphnet.morphnet_schema import (
        Bus,
        Circuit,
        Connection,
        PortReference,
        SignalDomain,
        SubCircuit,
    )

    def ref(inst, pin):
        return PortReference(instance_name=inst, port_name=pin)

    return morphnet.Netlist(
        name="doc",
        top_circuit="top",
        circuits=[
            Circuit(
                name="top",
                subcircuits=[
                    SubCircuit(
                        name="R1",
                        circuit_name="resistor",
                        properties={"__sub_x": '"a"', "kept": "1"},
                    ),
                    SubCircuit(name="R2", circuit_name="resistor"),
                ],
                connections=[
                    Connection(
                        name="mid",
                        source=ref("R1", "n"),
                        target=ref("R2", "p"),
                        properties={"__conn_x": "2"},
                    )
                ],
                buses=[
                    Bus(
                        name="data",
                        width=2,
                        domain=SignalDomain.ELECTRICAL,
                        connections=[
                            Connection(
                                name="d0", source=ref("R1", "p"), target=ref("R2", "n")
                            )
                        ],
                        properties={"protocol": "spi", "__bus_x": "1"},
                    )
                ],
                properties={"__circuit_x": "3"},
            )
        ],
    )


def _lossless_cases():
    from kfnetlist.morphnet.netlist import parse_spectre_spice, parse_xyce

    files = sorted(
        f
        for f in _FIXTURES.rglob("*")
        if f.suffix in {".sp", ".scs", ".vams", ".sv", ".yaml"}
        and "golden" not in f.parts  # nyancad's simulator decks, not parser input
    )
    cases = [
        pytest.param(lambda f=f: _parse(f), id=str(f.relative_to(_FIXTURES)))
        for f in files
    ]
    cases += [
        pytest.param(_bus_ir, id="buses_and_foreign_properties"),
        pytest.param(lambda: parse_spice(_SPICE), id="spice"),
        pytest.param(lambda: parse_xyce(_XYCE), id="xyce"),
        pytest.param(lambda: parse_spectre_spice(_SPECTRE_SPICE), id="spectre_spice"),
        pytest.param(lambda: morphnet.from_netlists({"rc": rc()}, "rc"), id="built"),
        pytest.param(lambda: parse_vams(_VAMS_NATURE), id="vams_nature"),
        pytest.param(lambda: parse_systemverilog(_SV_BLOCKS), id="sv_blocks"),
    ]
    return cases


_WRITERS = [
    "write_spice",
    "write_spectre",
    "write_hspice",
    "write_xyce",
    "write_spectre_spice",
    "write_vams",
    "write_systemverilog",
]


@pytest.mark.parametrize("make", _lossless_cases())
def test_bridge_lossless(make):
    from kfnetlist.morphnet import netlist as writers

    netlist = make()
    back = morphnet.from_netlists(morphnet.to_netlists(netlist))
    again = morphnet.from_netlists(morphnet.to_netlists(back))
    # Every writer handles every case: no writer is skipped.
    for name in _WRITERS:
        write = getattr(writers, name)
        expected = write(netlist)
        assert write(back) == expected, name
        assert write(again) == expected, name


# ---- focused: each morphnet-only field survives the bridge ----


def test_bridge_keeps_risky_bus_and_connection_shapes():
    from kfnetlist.morphnet.morphnet_schema import (
        Bus,
        Circuit,
        Connection,
        PortReference,
        SubCircuit,
    )

    def ref(inst, pin):
        return PortReference(instance_name=inst, port_name=pin)

    def conn(name, a, b, **props):
        return Connection(name=name, source=ref(*a), target=ref(*b), properties=props)

    shared = conn("n1", ("A", "o1"), ("B", "o1"))
    out_of_order = Bus(name="ooo", connections=[conn("d0", ("C", "p"), ("A", "n"))])
    circuit = Circuit(
        name="top",
        subcircuits=[SubCircuit(name=n, circuit_name="x") for n in "ABC"],
        connections=[
            shared,  # also a bus connection, as in tests/morphnet/conftest.py
            conn("", ("A", "o3"), ("B", "o3"), __x="u"),
            conn("m", ("A", "o2"), ("B", "o2"), __x="1"),
            conn("m", ("A", "o2"), ("C", "o2")),
        ],
        buses=[Bus(name="shared", width=4, connections=[shared]), out_of_order],
    )
    ir = morphnet.Netlist(name="d", top_circuit="top", circuits=[circuit])
    back = morphnet.from_netlists(morphnet.to_netlists(ir)).circuits[0]
    assert back.buses == circuit.buses
    assert len(back.connections) == len(circuit.connections)

    def foreign(pin, other):
        (c,) = [
            c
            for c in back.connections
            if {(t.instance_name, t.port_name) for t in (c.source, c.target) if t}
            >= {(other, pin)}
            and c.name != "n1"
        ]
        return c.properties.get("__x")

    assert foreign("o3", "B") == "u"
    assert foreign("o2", "B") == "1"
    assert foreign("o2", "C") is None


def test_bridge_keeps_buses_and_foreign_dunder_properties():
    ir = _bus_ir()
    netlists = morphnet.to_netlists(ir)
    # kfnetlist sees the bus members as a plain net; connectivity is unchanged.
    assert len(netlists["top"].nets) == 2
    top = morphnet.from_netlists(netlists).circuits[0]
    original = ir.circuits[0]
    assert top.buses == original.buses
    assert top.properties["__circuit_x"] == "3"
    assert top.subcircuits[0].properties["__sub_x"] == '"a"'
    assert {c.properties["__conn_x"] for c in top.connections if c.name == "mid"} == {
        "2"
    }
    # A bus whose net no longer exists is dropped, not resurrected.
    nl = netlists["top"]
    nl.remove_instances(["R2"])
    assert not morphnet.from_netlists(netlists).circuits[0].buses


def _ir() -> morphnet.Netlist:
    from kfnetlist.morphnet.morphnet_schema import (
        Analysis,
        AnalysisKind,
        Circuit,
        Connection,
        Directive,
        DirectiveKind,
        ExternalCircuit,
        ExternalLibrary,
        Parameter,
        ParameterValue,
        Port,
        PortDirection,
        PortReference,
        PrefixedValue,
        SignalDomain,
        SIPrefix,
        Simulation,
        SubCircuit,
    )
    from kfnetlist.morphnet.netlist.expression import parse_expression

    def conn(net, inst, pin):
        return Connection(
            name=net,
            source=PortReference(instance_name="", port_name=net),
            target=PortReference(instance_name=inst, port_name=pin),
            properties={"discipline": "electrical"},
        )

    kilo = ParameterValue(
        prefixed_value=PrefixedValue(double_value=1, prefix=SIPrefix.KILO)
    )
    sub = SubCircuit(
        name="R1",
        circuit_name="rmodel",
        parameters=[
            Parameter(name="r", default_value=kilo),
            Parameter(
                name="w",
                default_value=ParameterValue(expression=parse_expression("2*l")),
            ),
        ],
        properties={"model_name": "rpoly", "__info__": '{"gsch": {"x": 1}}'},
    )
    top = Circuit(
        name="top",
        ports=[
            Port(
                name="a", direction=PortDirection.INPUT, domain=SignalDomain.ELECTRICAL
            ),
            Port(name="b", direction=PortDirection.OUTPUT, discipline="electrical"),
        ],
        parameters=[Parameter(name="l", default_value=kilo)],
        subcircuits=[sub],
        connections=[conn("a", "R1", "p"), conn("mid", "R1", "n")],
        properties={
            "analog_block": "analog begin end",
            "__info__": '{"gsch_schema": "s"}',
        },
        directives=[Directive(kind=DirectiveKind.INCLUDE, value="top.inc")],
    )
    return morphnet.Netlist(
        name="doc",
        top_circuit="top",
        circuits=[top],
        ext_circuits=[
            ExternalCircuit(
                name="rmodel",
                ports=[Port(name="p"), Port(name="n")],
                properties={"spice_prefix": "R"},
            )
        ],
        directives=[Directive(kind=DirectiveKind.LIB, name="tt", value="corners.lib")],
        properties={"ground_net": "0", "dialect": "spectre"},
        libraries={"pdk": ExternalLibrary(path="pdk.lib", model_type="spice")},
        simulation=Simulation(analyses=[Analysis(kind=AnalysisKind.OP, name="op")]),
    )


def _bridged() -> tuple[dict[str, Netlist], morphnet.Netlist]:
    netlists = morphnet.to_netlists(_ir())
    return netlists, morphnet.from_netlists(netlists)


def test_bridge_parses_string_and_bool_settings_as_expressions():
    from kfnetlist.morphnet.morphnet_schema import Expression, ParameterValue

    nl = Netlist()
    nl.create_inst(
        "X1",
        kcl="",
        component="cell",
        settings={"w": "2*l", "on": True, "n": 2, "v": "DC 1"},
    )
    sub = morphnet.from_netlists({"top": nl}).circuits[0].subcircuits[0]
    params = {p.name: p for p in sub.parameters}
    assert params["w"].default_value == ParameterValue(
        expression=parse_expression("2*l")
    )
    assert params["on"].default_value == ParameterValue(
        expression=Expression(reference="true")
    )
    assert params["v"].default_value == ParameterValue(  # no expression: kept as text
        expression=Expression(raw="DC 1")
    )
    assert params["w"].properties == {}
    back = morphnet.to_netlists(morphnet.from_netlists({"top": nl}))["top"]
    assert back.instances["X1"].settings == {
        "w": "2*l",
        "on": True,
        "n": 2,
        "v": "DC 1",
    }


def test_bridge_shows_an_expression_as_its_text_and_keeps_its_tree():
    netlists, back_ir = _bridged()
    assert netlists["top"].instances["R1"].settings == {"r": 1000.0, "w": "2 * l"}
    assert (
        back_ir.circuits[0].subcircuits[0].parameters
        == _ir().circuits[0].subcircuits[0].parameters
    )


def test_an_edited_expression_setting_comes_back_structured():
    from kfnetlist.morphnet.morphnet_schema import ParameterValue

    netlists = morphnet.to_netlists(_ir())
    old = netlists["top"]
    edited = Netlist()
    for name, inst in old.instances.items():
        settings = {**inst.settings, "w": "2 * width"}
        edited.create_inst(
            name, kcl="", component=inst.component, settings=settings, info=inst.info
        )
    edited.info = old.info
    back = morphnet.from_netlists({"top": edited})
    params = {p.name: p for p in back.circuits[0].subcircuits[0].parameters}
    w = parse_expression("2 * width")
    assert w.binary is not None  # a tree, not `raw`
    assert params["w"].default_value == ParameterValue(expression=w)
    assert params["r"] == _ir().circuits[0].subcircuits[0].parameters[0]


def test_bridge_keeps_properties_and_info_at_both_levels():
    netlists, back = _bridged()
    nl = netlists["top"]
    inst_info = nl.instances["R1"].info
    assert inst_info["gsch"] == {"x": 1}
    assert inst_info["__morphnet__"]["properties"] == {"model_name": "rpoly"}
    assert nl.info["gsch_schema"] == "s"
    assert nl.info["__morphnet__"]["properties"] == {"analog_block": "analog begin end"}

    circuit = back.circuits[0]
    sub = circuit.subcircuits[0]
    assert sub.properties["model_name"] == "rpoly"
    assert json.loads(sub.properties["__info__"]) == {"gsch": {"x": 1}}
    assert circuit.properties["analog_block"] == "analog begin end"
    assert json.loads(circuit.properties["__info__"]) == {"gsch_schema": "s"}
    assert circuit.parameters == _ir().circuits[0].parameters


def test_bridge_keeps_terminal_domain_and_direction():
    _, back = _bridged()
    assert back.circuits[0].ports == _ir().circuits[0].ports


def test_bridge_lifts_circuit_and_document_directives():
    netlists, back = _bridged()
    assert netlists["top"].directives == [
        {"kind": "lib", "name": "tt", "value": "corners.lib"},
        {"kind": "include", "name": "", "value": "top.inc"},
    ]
    assert [(d.kind, d.name, d.value) for d in back.directives] == [
        (pb.DIRECTIVE_KIND_LIB, "tt", "corners.lib"),
        (pb.DIRECTIVE_KIND_INCLUDE, "", "top.inc"),
    ]
    assert back.circuits[0].directives == []


def test_bridge_keeps_document_fields():
    _, back = _bridged()
    ir = _ir()
    assert back.name == "doc"
    assert back.top_circuit == "top"
    assert back.ext_circuits == ir.ext_circuits
    assert back.properties == ir.properties
    assert back.libraries == ir.libraries
    assert back.simulation == ir.simulation


def test_bridge_keeps_net_names():
    netlists, back = _bridged()
    assert [n.name for n in netlists["top"].nets] == ["a", "mid"]
    assert [c.name for c in back.circuits[0].connections] == ["a", "mid"]
    assert all(
        c.properties["discipline"] == "electrical" for c in back.circuits[0].connections
    )

    nl = Netlist()
    nl.create_inst("R1", kcl="", component="resistor")
    nl.create_inst("R2", kcl="", component="resistor")
    nl.create_net(PortRef("R1", "n"), PortRef("R2", "p"), name="mid")
    nl.create_net(PortRef("R2", "n"))
    names = {
        c.name for c in morphnet.from_netlists({"top": nl}).circuits[0].connections
    }
    assert names == {"mid", "net_1"}
    back_nl = morphnet.to_netlists(morphnet.from_netlists({"top": nl}))["top"]
    assert [n.name for n in back_nl.nets] == ["mid", None]


# ---- reserved info keys and restored declarations ----


def test_reserved_instance_info_is_not_part_of_equality():
    one_k = morphnet.to_netlists(parse_spice(".subckt t a b\nR1 a b 1k\n.ends t\n"))[
        "t"
    ]
    plain = morphnet.to_netlists(parse_spice(".subckt t a b\nR1 a b 1000\n.ends t\n"))[
        "t"
    ]
    assert "__morphnet__" in one_k.instances["R1"].info  # 1k is stashed, 1000 is not
    assert one_k == plain

    built = Netlist()
    built.create_inst(
        "R1", kcl="", component="resistor", settings={"value": 1000.0}, na=0, nb=0
    )
    for port in ("a", "b"):
        built.create_port(port)
    built.create_net(NetlistPort("a"), PortRef("R1", "p"))
    built.create_net(NetlistPort("b"), PortRef("R1", "n"))
    for nl in (one_k, built):
        nl.sort()
    assert one_k == built


def test_restored_document_fills_only_devices_it_did_declare_or_never_used():
    source = (_FIXTURES / "vams" / "inverter_with_models.vams").read_text()
    netlists = morphnet.to_netlists(parse_vams(source))
    nl = netlists["cmos_inverter"]
    nl.create_inst("R9", kcl="", component="resistor", settings={"value": 1.0})
    back = morphnet.from_netlists(netlists)
    ext = {e.name: e for e in back.ext_circuits}
    assert "mosfet" not in ext  # the source used it undeclared
    assert [p.name for p in ext["resistor"].ports] == ["p", "n"]
    assert ext["resistor"].properties == {"spice_prefix": "R"}


# ---- the document header on every cell (final fix wave) ----

_HEADER_SPICE = """\
* t
.model nch nmos level=1 vto=0.5
.subckt inv a y
M1 y a 0 0 nch w=1u
.ends inv
.subckt buf a y
X1 a m inv
X2 m y inv
.ends buf
"""


def test_a_non_lead_toplevel_and_a_single_cell_keep_the_document_header():
    netlists = morphnet.to_netlists(parse_spice(_HEADER_SPICE))
    card = ".model nch nmos level=1 vto=0.5"
    assert card in write_spice(morphnet.from_netlists(netlists, toplevel="inv"))
    assert card in write_spice(morphnet.from_netlists({"inv": netlists["inv"]}))


def test_a_read_gsch_child_exported_alone_keeps_its_ground():
    from kfnetlist.morphnet.netlist import read_gsch

    nl = read_gsch(_FIXTURES / "gsch" / "ihp_hier_top.gsch", corners="mos_ff")
    netlists = morphnet.to_netlists(nl)
    child = morphnet.from_netlists({"hier_cell": netlists["hier_cell"]})
    assert child.properties["ground_net"] == "GND"
    assert "M1 out in 0 0 sg13_lv_nmos" in write_spice(child)


# ---- named port nets and a malformed stash ----


def test_net_names_survive_the_yaml_and_bridge_round_trips():
    src = (_FIXTURES / "hspice" / "hierarchical_subckt.sp").read_text()
    nl = morphnet.to_netlists(parse_spice(src))["inverter"]
    names = [n.name for n in nl.nets]
    assert names == ["in_", "out", "vss"]
    doc = NetlistDocument.from_netlists({"inverter": nl}, "inverter")
    yaml_back = NetlistDocument.from_yaml(doc.to_yaml()).to_netlists()["inverter"]
    assert [n.name for n in yaml_back.nets] == names
    bridged = morphnet.to_netlists(morphnet.from_netlists({"inverter": nl}))
    assert [n.name for n in bridged["inverter"].nets] == names


@pytest.mark.parametrize("value", ["garbage", [1], None])
def test_malformed_morphnet_stash_raises(value):
    nl = rc()
    nl.info = {"__morphnet__": value}
    with pytest.raises(ValueError, match="must be an object"):
        NetlistDocument.from_netlists({"rc": nl}, "rc").to_proto()
    with pytest.raises(ValueError, match="must be an object"):
        morphnet.from_netlists({"rc": nl})
