import json
from pathlib import Path

import pytest

from kfnetlist import morphnet
from kfnetlist.morphnet.morphnet_schema import Netlist, SignalDomain
from kfnetlist.morphnet.netlist.net_utils import (
    NetMap,
    add_port_to_net,
    net_map_to_connections,
)
from kfnetlist.morphnet.netlist import (
    parse_gsch,
    parse_spice,
    parse_systemverilog,
    write_gsch,
)

FIXTURES = Path(__file__).parent / "netlists" / "gsch"
NAMES = sorted(p.stem for p in FIXTURES.glob("*.gsch"))
# Mosaic's accepted entry types (common.cljc `device-types` + `schematic-only-types`)
MOSAIC_TYPES = set(
    "pmos nmos npn pnp resistor capacitor inductor vsource isource diode led "
    "photodiode modulator ckt amp die straight bend sbend taper transition "
    "terminator crossing ring-single ring-double spiral splitter-1x2 coupler "
    "coupler-ring mmi-1x2 mmi-2x2 mzi-1x2 mzi-2x2 grating-coupler "
    "wire port text polyline group via".split()
)


def structure(netlist: Netlist, fold_pin_case: bool = False):
    """Everything the writer must preserve: nets, pins, instances.

    ``fold_pin_case``: Mosaic symbols spell pins uppercase (``p`` -> ``P``).
    """
    circuit = netlist.circuits[0]
    nets: dict[str, set[tuple[str, str]]] = {}
    for c in circuit.connections:
        nets.setdefault(c.name, set()).update(
            (r.instance_name, r.port_name.upper() if fold_pin_case else r.port_name)
            for r in (c.source, c.target)
            if r
        )
    return (
        {frozenset(m) for m in nets.values()},
        [(p.name, p.domain) for p in circuit.ports],
        [(s.name, s.circuit_name) for s in circuit.subcircuits],
    )


@pytest.mark.parametrize("name", NAMES)
def test_parse_write_parse_keeps_structure(name):
    nl = parse_gsch((FIXTURES / f"{name}.gsch").read_text())
    again = parse_gsch(write_gsch(nl), name=nl.top_circuit)
    assert structure(again) == structure(nl)
    assert write_gsch(again) == write_gsch(nl)  # and the output is stable


@pytest.mark.parametrize("name", NAMES)
def test_stashed_entries_come_back_verbatim(name):
    raw = json.loads((FIXTURES / f"{name}.gsch").read_text())
    out = json.loads(write_gsch(parse_gsch(json.dumps(raw))))
    assert set(out) == set(raw)  # same keys: nothing lost, nothing synthesized
    for key, entry in raw.items():
        if entry["type"] in ("wire", "text", "group", "via", "taper", "polyline"):
            assert out[key] == entry
        else:  # layout fields are kept; only name, nets, props are rewritten
            for field, value in entry.items():
                if field not in ("name", "nets", "props"):
                    assert out[key][field] == value, (key, field)
            assert out[key].get("props", {}) == entry.get("props", {})


def test_pin_spelling_of_the_editor_is_restored():
    nl = parse_gsch((FIXTURES / "ihp_rc_filter.gsch").read_text())
    for c in nl.circuits[0].connections:
        for ref in (c.source, c.target):
            if ref and ref.instance_name:
                ref.port_name = ref.port_name.lower()
    out = json.loads(write_gsch(nl))
    assert out["demo:R1"]["nets"] == {"P": "P1", "N": "W3"}


def test_renamed_instance_and_changed_master_are_written():
    nl = parse_gsch((FIXTURES / "ihp_rc_filter.gsch").read_text())
    r1 = nl.circuits[0].subcircuits[1]
    r1.circuit_name = "capacitor"
    out = json.loads(write_gsch(nl))["demo:R1"]
    assert out["type"] == "capacitor"
    assert out["x"] == 4  # layout kept


def test_polylines_are_rewritten_to_component_id_form_and_orphans_dropped():
    inst = {"type": "ckt", "model": "m", "x": 0, "y": 0}
    doc = {
        "a": {**inst, "name": "A"},
        "b": {**inst, "name": "B"},
        "p1": {"type": "polyline", "terminals": {
            "start": {"device": "a", "port": "o2"}, "finish": ["b", "o1"]}},
        "p2": {"type": "polyline", "terminals": {
            "start": {"instance": "b", "port": "o2"}, "finish": ["a", "o1"]}},
    }  # fmt: skip
    nl = parse_gsch(json.dumps(doc))
    out = json.loads(write_gsch(nl))
    for key in ("p1", "p2"):
        for end in out[key]["terminals"].values():
            assert set(end) == {"component_id", "port_name"}
    assert out["p1"]["terminals"]["finish"] == {"component_id": "b", "port_name": "o1"}

    nl.circuits[0].subcircuits.pop()  # B is gone: both polylines end on it
    assert set(json.loads(write_gsch(nl))) == {"a"}


def test_net_entries_keep_only_live_endpoints():
    inst = {"type": "ckt", "model": "m", "x": 0, "y": 0}
    doc = {
        "a": {**inst, "name": "A"},
        "b": {**inst, "name": "B"},
        "n": {"type": "net", "ports": [
            {"component_id": "a", "port_name": "o1"},
            {"component_id": "b", "port_name": "o1"}]},
    }  # fmt: skip
    nl = parse_gsch(json.dumps(doc))
    nl.circuits[0].subcircuits.pop()
    assert json.loads(write_gsch(nl))["n"]["ports"] == [
        {"component_id": "a", "port_name": "o1"}
    ]


def test_inline_models_survive():
    doc = {"models": {"models:m": {"ports": []}}, "a": {"type": "ckt", "name": "A"}}
    assert (
        json.loads(write_gsch(parse_gsch(json.dumps(doc))))["models"] == doc["models"]
    )


@pytest.mark.parametrize("name", NAMES)
def test_stash_survives_the_kfnetlist_bridge(name):
    nl = parse_gsch((FIXTURES / f"{name}.gsch").read_text())
    back = morphnet.from_netlists(morphnet.to_netlists(nl), nl.top_circuit)
    # the bridge may reorder JSON object keys, never change values (floats included)
    assert json.loads(write_gsch(back)) == json.loads(write_gsch(nl))


# ── writing from sources that never saw a .gsch ─────────────────────────────────

RC = """\
.subckt rc in out gnd
R1 in out 1k
C1 out gnd 100p
.ends rc
"""
PHOTONIC = """\
module mzi (input o1, output o2, input e1);
  wg_straight X1 (.o1(o1), .o2(mid));
  wg_straight X2 (.o1(mid), .o2(o2));
  heater H (.e1(e1));
endmodule
"""


def check_synthesized(text: str) -> dict:
    out = json.loads(text)
    for key, entry in out.items():
        assert entry["type"] in MOSAIC_TYPES, key
        assert entry["type"] not in ("net", "subckt")
        if entry["type"] != "wire":
            assert {"name", "x", "y"} <= entry.keys(), key
            assert entry["name"] == key
        if entry["type"] == "polyline":
            for end in entry["terminals"].values():
                assert set(end) == {"component_id", "port_name"}
    assert len({(e["x"], e["y"]) for e in out.values()}) == len(out)  # no overlap
    return out


@pytest.mark.parametrize(
    ("source", "parse"), [(RC, parse_spice), (PHOTONIC, parse_systemverilog)]
)
def test_other_formats_write_a_valid_schematic_with_the_same_connectivity(
    source, parse
):
    nl = parse(source)
    text = write_gsch(nl)
    out = check_synthesized(text)
    assert {e["name"] for e in out.values()} == {
        *(s.name for s in nl.circuits[0].subcircuits),
        *(p.name for p in nl.circuits[0].ports),
    }
    reparsed = parse_gsch(text, name=nl.top_circuit)
    assert structure(reparsed, fold_pin_case=True) == structure(nl, True)


def test_rc_is_written_as_mosaic_symbols_with_values():
    out = json.loads(write_gsch(parse_spice(RC)))
    assert out["R1"]["type"] == "resistor"
    assert "model" not in out["R1"]
    assert out["R1"]["props"] == {"value": "1k"}
    # Mosaic's resistor pins are `P` and `N`: SPICE's `p`/`n` would not connect
    assert out["R1"]["nets"] == {"P": "in", "N": "out"}
    assert out["in"]["nets"] == {"P": "in"}
    assert out["in"]["attached_port"] == {"component_id": "R1", "port_name": "P"}
    assert out["in"]["nature"] == "electric"


def test_only_pins_of_the_mosaic_symbol_are_uppercased():
    nl = parse_spice(RC)
    nl.circuits[0].subcircuits[0].circuit_name = "nmos"  # pins D G S B
    out = json.loads(write_gsch(nl))
    assert out["R1"]["nets"] == {"p": "in", "n": "out"}  # not nmos pins: verbatim
    assert out["C1"]["nets"] == {"P": "out", "N": "gnd"}  # capacitor: uppercased


def test_photonic_module_is_written_as_ckt_models_and_photonic_ports():
    out = json.loads(write_gsch(parse_systemverilog(PHOTONIC)))
    assert (out["X1"]["type"], out["X1"]["model"]) == ("ckt", "wg_straight")
    assert out["o1"]["nature"] == "photonic"
    assert out["e1"]["nature"] == "electric"
    reparsed = parse_gsch(write_gsch(parse_systemverilog(PHOTONIC)))
    assert {p.name: p.domain for p in reparsed.circuits[0].ports} == {
        "o1": SignalDomain.WAVEGUIDE,
        "o2": SignalDomain.WAVEGUIDE,
        "e1": SignalDomain.ELECTRICAL,
    }


def test_colliding_names_do_not_overwrite_each_other():
    nl = parse_spice(".subckt t a\nR1 a b 1k\nR2 b a 1k\n.ends t\n")
    nl.circuits[0].subcircuits[0].name = "a"  # instance named like the port
    nl.circuits[0].connections.clear()
    out = json.loads(write_gsch(nl))
    assert len(out) == 3
    assert {e["name"] for e in out.values()} == {"a", "R2"}
    # the port keeps its name; its key is suffixed and recorded as `id`
    assert out["a"]["type"] == "resistor"
    assert (out["a_"]["name"], out["a_"]["id"]) == ("a", "a_")
    assert "id" not in out["a"] and "id" not in out["R2"]


def test_duplicate_names_survive_parse_write_parse():
    doc = {
        "x": {"type": "ckt", "name": "b", "model": "m", "nets": {"o1": "n"}},
        "b": {"type": "ckt", "name": "b", "model": "m", "nets": {"o1": "n"}},
    }
    nl = parse_gsch(json.dumps(doc))
    out = json.loads(write_gsch(nl))
    assert set(out) == {"x", "b"}  # nothing overwritten
    assert len({e["name"] for e in out.values()}) == 2
    assert structure(parse_gsch(json.dumps(out))) == structure(nl)
    assert len(structure(nl)[2]) == 2


# ── connectivity edited on an IR that came from a .gsch ──────────────────────────


def move_pin(nl: Netlist, inst: str, pin: str, to: str) -> None:
    """Rewire ``inst.pin`` to the pin ``to`` of the same instance."""
    for c in nl.circuits[0].connections:
        for ref in (c.source, c.target):
            if ref and (ref.instance_name, ref.port_name) == (inst, pin):
                ref.port_name = to


def rebind(nl: Netlist, inst: str, pin: str, net: str) -> None:
    """Move ``inst.pin`` onto the net called ``net``."""
    circuit = nl.circuits[0]
    net_map: NetMap = {}
    for c in circuit.connections:
        for ref in (c.source, c.target):
            if ref and (ref.instance_name, ref.port_name) != (inst, pin):
                members = net_map.setdefault(c.name, [])
                if ref not in members:
                    members.append(ref)
    add_port_to_net(net_map, net, inst, pin)
    circuit.connections = net_map_to_connections(net_map)


def parsed_nets(nl: Netlist) -> set[frozenset[tuple[str, str]]]:
    return structure(parse_gsch(write_gsch(nl)))[0]


def test_moving_a_pin_to_another_net_is_written_for_mosaic_nets():
    nl = parse_gsch((FIXTURES / "ihp_rc_filter.gsch").read_text())
    rebind(nl, "C1", "P", "W3")  # C1.P leaves net P1 for W3
    assert json.loads(write_gsch(nl))["demo:C1"]["nets"] == {"N": "GND", "P": "W3"}
    assert parsed_nets(nl) == {
        frozenset({("V1", "P"), ("R1", "N"), ("C1", "P")}),
        frozenset({("V1", "N"), ("C1", "N")}),
        frozenset({("R1", "P"), ("", "P1")}),
    }


def test_port_marker_is_rebound_when_its_pin_moves():
    nl = parse_gsch((FIXTURES / "ihp_subckt_child.gsch").read_text())
    move_pin(nl, "M1", "D", "G")  # port D now sits on M1.G
    out = json.loads(write_gsch(nl))
    assert out["port_D"]["attached_port"] == {
        "component_id": "nmos_1",
        "port_name": "G",
    }
    assert out["port_S"]["attached_port"]["port_name"] == "S"  # untouched
    assert frozenset({("", "D"), ("M1", "G")}) in parsed_nets(nl)


def test_marker_loses_its_binding_when_no_instance_is_left_on_its_net():
    nl = parse_gsch((FIXTURES / "ihp_subckt_child.gsch").read_text())
    nl.circuits[0].subcircuits.pop()  # M1 is gone
    nl.circuits[0].connections.clear()
    out = json.loads(write_gsch(nl))
    assert "attached_port" not in out["port_D"]
    assert parsed_nets(nl) == set()


def test_polyline_is_dropped_when_its_pins_are_no_longer_one_net():
    nl = parse_gsch((FIXTURES / "ihp_subckt_parent_poly.gsch").read_text())
    assert "poly_coupling" in json.loads(write_gsch(nl))  # unchanged: kept
    move_pin(nl, "A", "D", "S")  # A.D leaves the net it shared with B.S
    out = json.loads(write_gsch(nl))
    assert "poly_coupling" not in out
    assert all(("A", "D") not in net for net in parsed_nets(nl))


def test_edited_connectivity_round_trips_for_every_fixture():
    for name in NAMES:
        nl = parse_gsch((FIXTURES / f"{name}.gsch").read_text())
        assert parsed_nets(nl) == structure(nl)[0], name


def test_a_netlist_without_circuits_is_rejected():
    with pytest.raises(ValueError, match="no circuit"):
        write_gsch(Netlist())
