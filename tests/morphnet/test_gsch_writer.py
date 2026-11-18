import json
from pathlib import Path

import pytest

from kfnetlist import morphnet
from kfnetlist.morphnet.morphnet_schema import Netlist, SignalDomain
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


def structure(netlist: Netlist):
    """Everything the writer must preserve: nets, pins, instances."""
    circuit = netlist.circuits[0]
    nets: dict[str, set[tuple[str, str]]] = {}
    for c in circuit.connections:
        nets.setdefault(c.name, set()).update(
            (r.instance_name, r.port_name) for r in (c.source, c.target) if r
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


# spclo_gc2 is excluded: the bridge's serde_json parses floats with 1 ULP of error
# (95.34302520751953 -> ...52) unless built with its `float_roundtrip` feature.
@pytest.mark.parametrize("name", [n for n in NAMES if n != "spclo_gc2"])
def test_stash_survives_the_kfnetlist_bridge(name):
    nl = parse_gsch((FIXTURES / f"{name}.gsch").read_text())
    back = morphnet.from_netlists(morphnet.to_netlists(nl), nl.top_circuit)
    # the bridge may reorder JSON object keys, never change values
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
    assert structure(parse_gsch(text, name=nl.top_circuit)) == structure(nl)


def test_rc_is_written_as_mosaic_symbols_with_values():
    out = json.loads(write_gsch(parse_spice(RC)))
    assert out["R1"]["type"] == "resistor"
    assert "model" not in out["R1"]
    assert out["R1"]["props"] == {"value": "1k"}
    assert out["R1"]["nets"] == {"p": "in", "n": "out"}
    assert out["in"]["nets"] == {"P": "in"}
    assert out["in"]["attached_port"] == {"component_id": "R1", "port_name": "p"}
    assert out["in"]["nature"] == "electric"


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


def test_a_netlist_without_circuits_is_rejected():
    with pytest.raises(ValueError, match="no circuit"):
        write_gsch(Netlist())
