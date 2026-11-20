import json
from pathlib import Path

import pytest

from kfnetlist.morphnet.morphnet_schema import Netlist, SIPrefix, SignalDomain
from kfnetlist.morphnet.netlist import parse_gsch, write_gsch

FIXTURES = Path(__file__).parent / "netlists" / "gsch"
WAVEGUIDE, ELECTRICAL = SignalDomain.WAVEGUIDE, SignalDomain.ELECTRICAL


def load(name: str, **kwargs) -> Netlist:
    return parse_gsch((FIXTURES / f"{name}.gsch").read_text(), **kwargs)


def nets(netlist: Netlist) -> dict[str, set[tuple[str, str]]]:
    """Net name -> {(instance, pin)}; the circuit's own pins have instance ``""``."""
    out: dict[str, set[tuple[str, str]]] = {}
    for c in netlist.circuits[0].connections:
        out.setdefault(c.name, set()).update(
            (r.instance_name, r.port_name) for r in (c.source, c.target) if r
        )
    return out


def ext_ports(netlist: Netlist, name: str) -> dict[str, SignalDomain]:
    ext = next(e for e in netlist.ext_circuits if e.name == name)
    return {p.name: p.domain for p in ext.ports}


def test_mosaic_rc_filter():
    nl = load("ihp_rc_filter")
    # built-in symbols take the device templates' pins (P N -> p n)
    assert nets(nl) == {
        "W3": {("V1", "p"), ("R1", "n")},
        "GND": {("V1", "n"), ("C1", "n")},
        "P1": {("R1", "p"), ("C1", "p"), ("", "P1")},
    }
    circuit = nl.circuits[0]
    assert (circuit.name, nl.top_circuit) == ("__top__", "__top__")
    assert json.loads(circuit.properties["__info__"])["gsch_schema"] == "demo"
    # the ground marker is not a pin, but its net keeps the name GND
    assert [(p.name, p.domain) for p in circuit.ports] == [("P1", ELECTRICAL)]
    assert {c.domain for c in circuit.connections} == {ELECTRICAL}
    assert [s.name for s in circuit.subcircuits] == ["V1", "R1", "C1"]
    assert [s.circuit_name for s in circuit.subcircuits] == [
        "vsource",
        "resistor",
        "capacitor",
    ]
    assert ext_ports(nl, "resistor") == {"p": ELECTRICAL, "n": ELECTRICAL}


def test_mosaic_props_become_si_values_or_expressions():
    nl = load("ihp_rc_filter")
    r1 = nl.circuits[0].subcircuits[1]
    (resistance,) = r1.parameters  # nyancad: `resistance` is R's value
    assert resistance.name == "value"
    assert resistance.default_value.prefixed_value.double_value == 1
    assert resistance.default_value.prefixed_value.prefix == SIPrefix.KILO

    nl = load("ihp_cmos_inverter")
    v2 = next(s for s in nl.circuits[0].subcircuits if s.name == "V2")
    (value,) = v2.parameters  # a `tran` string is no waveform: nyancad drops it
    assert value.default_value.expression.raw == "DC 0.9 AC 1"  # no expression
    assert value.properties == {}
    m1 = next(s for s in nl.circuits[0].subcircuits if s.name == "M1")
    by_name = {p.name: p for p in m1.parameters}
    assert by_name["width"].default_value.prefixed_value.double_value == 0.15
    assert m1.properties["model_name"] == "sg13_lv_nmos"  # the `model` prop


def test_mosaic_inverter_with_models_and_polylines():
    nl = load("ihp_cmos_inverter")
    assert nets(nl) == {
        "GND": {("M1", "b"), ("M1", "s"), ("V1", "n"), ("V2", "n")},
        "P1": {("M1", "d"), ("M2", "s"), ("R1", "n"), ("", "P1")},
        "P2": {("M1", "g"), ("M2", "g"), ("V2", "p"), ("", "P2")},
        "W5": {("M2", "d"), ("M2", "b"), ("R1", "p"), ("V1", "p")},
    }
    assert [p.name for p in nl.circuits[0].ports] == ["P1", "P2"]
    masters = {s.name: s.circuit_name for s in nl.circuits[0].subcircuits}
    assert masters["M1"] == "mosfet"  # its model is not in `models`: built-in
    assert list(ext_ports(nl, "mosfet")) == ["d", "g", "s", "b"]


def test_livewire_polyline_joins_the_pins_it_ends_on():
    nl = load("livewire_two_straights")
    assert nets(nl) == {
        "net_1": {("uuid-A:M1", "o2"), ("uuid-B:M2", "o1")},
    }
    circuit = nl.circuits[0]
    assert circuit.name == "__top__"
    info = json.loads(circuit.properties["__info__"])
    assert info["gsch_schema"] is None  # the two keys have different prefixes
    assert [s.circuit_name for s in circuit.subcircuits] == [
        "gf.components.straight"
    ] * 2
    assert {c.domain for c in circuit.connections} == {WAVEGUIDE}
    assert ext_ports(nl, "gf.components.straight") == {
        "o1": WAVEGUIDE,
        "o2": WAVEGUIDE,
    }


def test_livewire_port_markers_attach_to_the_straight():
    nl = load("livewire_port_markers")
    assert nets(nl) == {
        "net_in": {("", "in"), ("straight_1", "o1")},
        "net_out": {("", "out"), ("straight_1", "o2")},
    }
    assert [(p.name, p.domain) for p in nl.circuits[0].ports] == [
        ("in", WAVEGUIDE),
        ("out", WAVEGUIDE),
    ]


def test_mixed_file_uses_device_port_types_over_pin_names():
    nl = load("spclo_gc2")
    assert nets(nl) == {
        "W1": {("X1", "o1"), ("X2", "o1")},
        "P1": {("X1", "o2"), ("", "P1")},
        "P2": {("X2", "o2"), ("", "P2")},
    }
    assert nl.circuits[0].name == "__top__"
    # `o2` is named like a waveguide pin but the device says electrical
    assert ext_ports(nl, "myspclo.gc.gc") == {"o1": WAVEGUIDE, "o2": ELECTRICAL}
    domains = {c.name: c.domain for c in nl.circuits[0].connections}
    assert domains == {"W1": WAVEGUIDE, "P1": ELECTRICAL, "P2": ELECTRICAL}
    assert [(p.name, p.domain) for p in nl.circuits[0].ports] == [
        ("P1", ELECTRICAL),
        ("P2", ELECTRICAL),
    ]


def test_subcircuit_references_by_net_or_polyline():
    by_nets = load("ihp_subckt_parent_nets")
    assert nets(by_nets) == {"coupling": {("A", "D"), ("B", "S")}}
    assert [s.circuit_name for s in by_nets.circuits[0].subcircuits] == [
        "ihp_subckt_child.gsch"
    ] * 2
    assert nets(load("ihp_subckt_parent_poly")) == {"net_1": {("A", "D"), ("B", "S")}}


def test_child_schematic_exposes_attached_ports_in_marker_order():
    nl = load("ihp_subckt_child")
    assert [p.name for p in nl.circuits[0].ports] == ["D", "S"]
    assert nets(nl) == {
        "net_1": {("M1", "D"), ("", "D")},
        "net_2": {("M1", "S"), ("", "S")},
    }
    # G is on the device but unconnected: still a pin of the master
    assert list(ext_ports(nl, "ihp.cells.fet_transistors.nmos")) == ["D", "S", "G"]


def test_via_joins_everything_that_ends_on_it():
    doc = {
        "a": {"type": "ckt", "name": "A", "model": "m"},
        "b": {"type": "ckt", "name": "B", "model": "m"},
        "v": {"type": "via", "name": "v1"},
        "p1": {"type": "polyline", "terminals": {
            "start": {"component_id": "a", "port_name": "e1"},
            "finish": {"component_id": "v", "port_name": "W"}}},
        "p2": {"type": "polyline", "terminals": {
            "start": {"component_id": "v", "port_name": "E"},
            "finish": {"component_id": "b", "port_name": "e1"}}},
    }  # fmt: skip
    nl = parse_gsch(json.dumps(doc))
    assert nets(nl) == {"net_1": {("A", "e1"), ("B", "e1")}}
    assert [s.name for s in nl.circuits[0].subcircuits] == ["A", "B"]  # no via instance


def test_all_polyline_terminal_forms_and_net_entries():
    inst = {"type": "ckt", "model": "m"}
    doc = {
        "a": {**inst, "name": "A"},
        "b": {**inst, "name": "B"},
        "c": {**inst, "name": "C"},
        "d": {**inst, "name": "D"},
        "p1": {"type": "polyline", "terminals": {
            "start": {"device": "a", "port": "o2"}, "finish": ["b", "o1"]}},
        "p2": {"type": "polyline", "net": "bc", "terminals": {
            "start": {"instance": "b", "port": "o2"},
            "finish": {"component_id": "c", "port_name": "o1"}}},
        "n1": {"type": "net", "ports": [
            {"component_id": "c", "port_name": "o2"},
            {"component_id": "d", "port_name": "o1"}]},
    }  # fmt: skip
    got = nets(parse_gsch(json.dumps(doc)))
    assert got == {
        "net_1": {("A", "o2"), ("B", "o1")},
        "bc": {("B", "o2"), ("C", "o1")},
        "n1": {("C", "o2"), ("D", "o1")},  # a net entry's key is the net name
    }


def test_net_entry_name_is_id_then_key_and_ranks_like_a_mosaic_name():
    def named(entry: dict, **pin_nets) -> dict[str, set[tuple[str, str]]]:
        a = {"type": "ckt", "name": "A", "model": "m", "nets": pin_nets}
        ports = [
            {"component_id": "a", "port_name": "o1"},
            {"component_id": "b", "port_name": "o1"},
        ]
        doc = {"a": a, "b": {"type": "ckt", "name": "B", "model": "m"},
               "k": {"type": "net", "ports": ports, **entry}}  # fmt: skip
        return nets(parse_gsch(json.dumps(doc)))

    members = {("A", "o1"), ("B", "o1")}
    assert named({}) == {"k": members}
    assert named({"id": "sig"}) == {"sig": members}
    assert named({"id": "sig", "_id": "other"}) == {"sig": members}
    assert named({"_id": "other"}) == {"other": members}
    # a Mosaic `nets` name on one of the pins wins, as it does over any other name
    assert named({"id": "sig"}, o1="vdd") == {"vdd": members}


def test_duplicate_names_are_made_unique_without_losing_an_instance():
    # the second entry's key `b` equals the first entry's name `b`
    doc = {
        "x": {"type": "ckt", "name": "b", "model": "m", "nets": {"o1": "n"}},
        "b": {"type": "ckt", "name": "b", "model": "m", "nets": {"o1": "n"}},
        "c": {"type": "ckt", "name": "b_1", "model": "m"},
    }
    nl = parse_gsch(json.dumps(doc))
    names = [s.name for s in nl.circuits[0].subcircuits]
    assert len(names) == len(set(names)) == 3
    assert names[0] == "b"
    assert {frozenset(m) for m in nets(nl).values()} == {
        frozenset({("b", "o1"), (names[1], "o1")})
    }


def test_models_argument_gives_port_order_and_domains():
    doc = {
        "x": {"type": "ckt", "name": "X", "model": "pdk.cell", "nets": {"b": "n", "a": "m"}},
    }  # fmt: skip
    models = {
        "models:pdk.cell": {
            "type": "ckt",
            "ports": [
                {"name": "z", "type": "photonic"},
                {"name": "a", "type": "electric"},
            ],
            "models": [
                {"language": "spice", "spice-type": "X", "port-order": ["b", "a", "z"]}
            ],
        }
    }
    nl = parse_gsch(json.dumps(doc), models=models)
    assert list(ext_ports(nl, "pdk.cell")) == ["b", "a", "z"]
    assert ext_ports(nl, "pdk.cell")["z"] == WAVEGUIDE
    assert ext_ports(nl, "pdk.cell")["a"] == ELECTRICAL
    # without a model entry: an X call with the nyanlib ports sorted by name
    del models["models:pdk.cell"]["models"]
    assert list(ext_ports(parse_gsch(json.dumps(doc), models=models), "pdk.cell")) == [
        "a",
        "z",
    ]


def test_inline_models_are_merged_under_the_argument_and_are_not_entries():
    inline = {"models:pdk.cell": {"ports": [{"name": "q", "type": "photonic"}]}}
    doc = {"models": inline, "x": {"type": "ckt", "name": "X", "model": "pdk.cell"}}
    nl = parse_gsch(json.dumps(doc))
    assert [s.name for s in nl.circuits[0].subcircuits] == ["X"]
    assert ext_ports(nl, "pdk.cell") == {"q": WAVEGUIDE}
    override = {"models:pdk.cell": {"ports": [{"name": "r", "type": "electric"}]}}
    nl = parse_gsch(json.dumps(doc), models=override)
    assert ext_ports(nl, "pdk.cell") == {"r": ELECTRICAL}


def test_circuit_name_argument_wins_over_key_prefix():
    text = (FIXTURES / "ihp_rc_filter.gsch").read_text()
    assert parse_gsch(text, name="rc").top_circuit == "rc"
    assert parse_gsch(json.dumps({"r": {"type": "resistor"}})).top_circuit == "__top__"


def test_raw_entries_are_stashed_for_the_writer():
    nl = load("spclo_gc2")
    circuit = nl.circuits[0]
    raw = json.loads((FIXTURES / "spclo_gc2.gsch").read_text())
    info = json.loads(circuit.properties["__info__"])
    assert info["gsch_schema"] == "gc2"
    assert [i["key"] for i in info["gsch_ports"]] == ["gc2:P1", "gc2:P2"]
    assert [i["key"] for i in info["gsch_wires"]] == ["gc2:W1"]
    assert [i["key"] for i in info["gsch_routes"]] == ["poly_1"]
    assert info["gsch_routes"][0]["entry"] == raw["poly_1"]
    x1 = json.loads(circuit.subcircuits[0].properties["__info__"])
    assert x1 == {
        "__gsch__": {"key": "gc2:X1", "entry": raw["gc2:X1"]},
        "__model__": "myspclo.gc.gc",
    }


@pytest.mark.parametrize("bad", ["[]", "3"])
def test_non_object_documents_are_rejected(bad):
    with pytest.raises(ValueError, match="JSON object"):
        parse_gsch(bad)


def test_a_dangling_mosaic_label_is_a_net_and_round_trips():
    doc = {
        "a": {"type": "ckt", "name": "A", "model": "m", "nets": {"o1": "x", "o2": "lone"}},
        "b": {"type": "ckt", "name": "B", "model": "m", "nets": {"o1": "x"}},
    }  # fmt: skip
    nl = parse_gsch(json.dumps(doc))
    assert nets(nl) == {"x": {("A", "o1"), ("B", "o1")}, "lone": {("A", "o2")}}
    out = json.loads(write_gsch(nl))
    assert out["a"]["nets"] == {"o1": "x", "o2": "lone"}
    assert nets(parse_gsch(json.dumps(out))) == nets(nl)
