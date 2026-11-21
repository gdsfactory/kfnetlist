"""``.gsch`` -> SPICE/Spectre parity with nyancad's netlister.

The goldens in ``netlists/gsch/golden`` were written once by nyancad + InSpice
(``golden/regen.py``); these tests never import either. Both sides are normalised
to the circuit: libraries, subckt headers and, per scope, the set of elements
(name, nodes, master/positional values, params). Simulator scaffolding (title,
``.end``, ``control`` blocks, ``load``/``model`` cards, ``ground 0``) is ignored.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from kfnetlist import morphnet
from kfnetlist.morphnet.morphnet_schema import (
    DirectiveKind,
    Expression,
    Netlist,
    WaveformKind,
)
from kfnetlist.morphnet.netlist.expression import parameter_value, parse_expression
from kfnetlist.morphnet.netlist.gsch.parser import parameter
from kfnetlist.morphnet.netlist import (
    parse_gsch,
    read_gsch,
    write_gsch,
    write_spectre,
    write_spice,
    write_xyce,
)

FIXTURES = Path(__file__).parent / "netlists" / "gsch"
GOLDEN = FIXTURES / "golden"
MODELS = json.loads((FIXTURES / "models.nyanlib").read_text())
CORNERS = {"ihp_hier_top": ["mos_ff"]}  # as in golden/regen.py
WRITERS = {"ngspice": write_spice, "xyce": write_xyce, "vacask": write_spectre}
GOLDENS = sorted(p.name for p in GOLDEN.glob("*.*.*") if p.suffix in (".cir", ".scs"))
NODES = {"R": 2, "C": 2, "L": 2, "V": 2, "I": 2, "D": 2, "Q": 3, "M": 4}
NUMBER = re.compile(
    r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)(meg|[tgkmunpf])?(v|a|s|hz)?$", re.I
)
SCALE = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6}
SCALE |= {"n": 1e-9, "p": 1e-12, "f": 1e-15}


def value(text: str, fold: bool) -> object:
    """A number (any SI suffix or unit) as a float; anything else without spaces."""
    text = text.strip()
    m = NUMBER.match(text)
    if m:
        number = float(m[1]) * SCALE.get((m[2] or "").lower(), 1)
        return float(f"{number:.9g}")
    text = re.sub(r"\s+", "", text)
    return text.lower() if fold else text


def unwrap(text: str) -> str:
    """One outer ``{…}``/``'…'`` is dialect wrapping, not circuit content: our writers
    wrap Xyce expressions in braces, nyancad does not."""
    text = text.strip()
    if len(text) >= 2 and (text[0], text[-1]) in (("{", "}"), ("'", "'")):
        return text[1:-1]
    return text


def params(tail: str, fold: bool) -> tuple:
    pairs = re.findall(r"(\S+?)=(.*?)(?=\s+\S+=|$)", tail.strip())
    out = {k.lower() if fold else k: value(unwrap(v), fold) for k, v in pairs}
    return tuple(sorted(out.items()))


def split(line: str) -> tuple[str, str]:
    """``head`` (positional tokens) and ``tail`` (``k=v`` params) of a line."""
    line = line.replace(" PARAMS:", "")  # Xyce keyword
    m = re.search(r"\s\S+=", line)
    return (line[: m.start()], line[m.start() :]) if m else (line, "")


def spice_view(text: str, golden: bool) -> dict:
    view: dict = {"libs": set(), "headers": {}, "elements": {}}
    scope = "__top__"
    for line in text.splitlines():
        line = line.strip()
        low = line.lower()
        if low.startswith(".lib "):
            view["libs"].add(tuple(t.strip('"') for t in line.split()))
        elif low.startswith(".include"):
            view["libs"].add((".include", line.split(None, 1)[1].strip('"')))
        elif low.startswith(".subckt"):
            head, tail = split(line)
            _, scope, *ports = head.split()
            view["headers"][scope] = (tuple(ports), params(tail, False))
        elif low.startswith(".ends"):
            scope = "__top__"
        elif line and not line.startswith(("*", ".")):
            head, tail = split(line)
            name, *rest = re.split(r"[\s()]+", head.strip(") "))
            if golden and name[:1].lower() == name[1:2].lower():
                name = name[1:]  # InSpice prepends the letter even when present
            n = NODES.get(name[0].upper(), len(rest) - 1)  # X: all but the master
            element = (
                name,
                tuple(rest[:n]),
                tuple(value(t, False) for t in rest[n:]),
                params(tail, False),
            )
            view["elements"].setdefault(scope, set()).add(element)
    return view


def spectre_view(text: str, golden: bool) -> dict:
    view: dict = {"libs": set(), "headers": {}, "parameters": {}, "elements": {}}
    scope, control = "__top__", False
    for line in text.splitlines():
        line = line.strip()
        word = line.split(" ", 1)[0].split("(", 1)[0]
        if word in ("control", "endc"):
            control = word == "control"
        elif control or not line or line.startswith("//"):
            continue
        elif word == "include":
            path, options = re.match(r'include\s+"([^"]*)"(.*)', line).groups()
            view["libs"].add((path, *sorted(options.split())))
        elif word == "subckt":
            scope, ports, tail = re.match(
                r"subckt\s+(\S+?)\s*\(([^)]*)\)(.*)", line
            ).groups()
            view["headers"][scope] = (tuple(ports.split()), params(tail, True))
        elif word == "parameters" and scope != "__top__":  # VACASK subckt params
            view["parameters"][scope] = params(line[10:], True)  # not on the header
        elif word == "ends":
            scope = "__top__"
        elif word not in ("ground", "load", "model", "parameters"):
            name, nodes, master, tail = re.match(
                r"(\S+?)\s*\(([^)]*)\)\s*(\S+)(.*)", line
            ).groups()
            element = (
                (name[1:] if golden else name).lower(),  # InSpice: letter + name
                tuple(nodes.split()),
                (master.lower(),),
                params(tail, True),
            )
            view["elements"].setdefault(scope, set()).add(element)
    return view


def export(stem: str, sim: str) -> Netlist:
    return read_gsch(FIXTURES / f"{stem}.gsch", sim=sim, corners=CORNERS.get(stem, ()))


@pytest.mark.parametrize("golden", GOLDENS)
def test_export_matches_nyancad(golden):
    stem, sim, _ = golden.split(".")
    view = spectre_view if sim == "vacask" else spice_view
    ours = view(WRITERS[sim](export(stem, sim)), golden=False)
    theirs = view((GOLDEN / golden).read_text(), golden=True)
    assert ours == theirs


def test_goldens_cover_every_fixture_nyancad_can_netlist():
    stems = {p.stem for p in FIXTURES.glob("*.gsch")}
    skipped = {
        line.split(".")[0]
        for line in (GOLDEN / "SKIPPED.txt").read_text().split("\n")
        if line
    }
    assert skipped == {"ihp_subckt_parent_nets"}  # nyancad: KeyError, pin S has no net
    assert {g.split(".")[0] for g in GOLDENS} == stems - skipped
    assert len(GOLDENS) == 3 * len(stems - skipped)


def lines(netlist: Netlist, sim: str = "ngspice") -> list[str]:
    return WRITERS[sim](netlist).splitlines()


def libs(netlist: Netlist) -> list[tuple]:
    return [(d.kind, d.value, d.name) for d in netlist.directives]


LIB, INCLUDE = DirectiveKind.LIB, DirectiveKind.INCLUDE


def library_doc(*models: str) -> str:
    doc = {
        f"top:{m}": {"type": "ckt", "name": m, "model": m, "nets": {"a": "x", "b": "y"}}
        for m in models
    }
    return json.dumps(doc)


def library_models(**sections: list[str]) -> dict:
    return {
        f"models:{name}": {
            "name": name,
            "ports": [{"name": "a"}, {"name": "b"}],
            "models": [
                {
                    "language": "spice",
                    "name": name,
                    "spice-type": "X",
                    "library": f"{name}.lib",
                    "sections": secs,
                }  # fmt: skip
            ],
        }
        for name, secs in sections.items()
    }


def test_corner_is_the_first_of_the_callers_list_the_library_has():
    models = library_models(mos=["tt", "ss", "ff"])
    nl = parse_gsch(library_doc("mos"), models=models, corners=["xx", "ff", "ss"])
    assert libs(nl) == [(LIB, "mos.lib ff", "")]
    nl = parse_gsch(library_doc("mos"), models=models, corners="ss")
    assert libs(nl) == [(LIB, "mos.lib ss", "")]


def test_corner_falls_back_to_the_first_section_then_to_an_include():
    models = library_models(mos=["tt", "ss"], plain=[])
    nl = parse_gsch(library_doc("mos", "plain"), models=models, corners=["ff"])
    assert libs(nl) == [(LIB, "mos.lib tt", ""), (INCLUDE, "plain.lib", "")]
    assert lines(nl)[1:3] == [".lib mos.lib tt", '.include "plain.lib"']


def test_each_model_family_takes_its_own_corner():
    models = library_models(mos=["mos_tt", "mos_ff"], res=["res_typ", "res_wcs"])
    corners = ["mos_ff", "res_wcs"]
    nl = parse_gsch(library_doc("mos", "res"), models=models, corners=corners)
    assert libs(nl) == [(LIB, "mos.lib mos_ff", ""), (LIB, "res.lib res_wcs", "")]


def test_shared_libraries_are_written_once():
    nl = export("ihp_cmos_inverter", "ngspice")  # nmos and pmos: one library
    assert libs(nl) == [
        (LIB, "ihp/models/ngspice/models/cornerMOSlv.lib mos_tt", ""),
    ]


def test_vacask_takes_the_native_entry_then_a_foreign_library_with_its_dialect():
    nl = export("ihp_cmos_inverter", "vacask")
    assert libs(nl) == [
        (LIB, "ihp/models/vacask/models/cornerMOSlv.lib mos_tt", ""),
        (LIB, "ihp/models/ngspice/models/cornerMOSlv.lib mos_tt", "lang=ngspice"),
    ]
    assert nl.properties["dialect"] == "vacask"


def test_ground_net_is_node_zero():
    nl = export("ihp_rc_filter", "ngspice")
    assert nl.properties["ground_net"] == "GND"
    assert "C1 P1 0 0.1u" in lines(nl)
    assert "V1 W3 0 DC 1 AC 1" in lines(nl)


def test_child_schematics_become_subcircuits_and_hoist_their_libraries():
    nl = export("ihp_hier_top", "ngspice")
    assert [c.name for c in nl.circuits] == ["hier_cell", "__top__"]
    cell = nl.circuits[0]
    assert [p.name for p in cell.ports] == ["in", "out", "vdd"]  # sorted model ports
    (rload,) = cell.parameters
    assert rload.name == "rload"
    assert rload.default_value.prefixed_value is not None  # a number, no expression
    # top first, then the child's; the child's nmos shares the top pmos library
    assert libs(nl) == [
        (LIB, "ihp/models/ngspice/models/cornerMOSlv.lib mos_ff", ""),
        (INCLUDE, "pdk/models/mprim.lib", ""),
    ]
    assert "hier_cell" not in {e.name for e in nl.ext_circuits}
    # vacask: only the child's nmos uses the native library, still at the top
    assert (LIB, "ihp/models/vacask/models/cornerMOSlv.lib mos_ff", "") in libs(
        export("ihp_hier_top", "vacask")
    )


def test_devices_nyancad_does_not_netlist_stay_in_the_ir_but_are_not_written():
    nl = export("ihp_hier_top", "ngspice")
    led = next(s for s in nl.circuits[-1].subcircuits if s.name == "LED1")
    assert led.properties["sim_skip"] == "1"
    assert not any(line.split()[0] in ("LED1", "XLED1") for line in lines(nl))
    nl = export("livewire_two_straights", "ngspice")  # no `nets`: nothing to netlist
    assert all(s.properties.get("sim_skip") == "1" for s in nl.circuits[0].subcircuits)


def test_missing_mos_bulk_is_tied_to_ground():
    nl = export("ihp_hier_top", "ngspice")
    assert "M4 vout2 vin 0 0 nch w=1u" in lines(nl)


def test_models_keep_their_fqn_for_write_gsch():
    nl = export("ihp_cmos_inverter", "ngspice")
    m1 = next(s for s in nl.circuits[0].subcircuits if s.name == "M1")
    assert (m1.circuit_name, m1.properties.get("sim_skip")) == ("sg13_lv_nmos", None)
    info = json.loads(m1.properties["__info__"])
    assert info["__model__"] == "ihp.cells.fet_transistors.nmos"
    out = json.loads(write_gsch(nl))["demo2:M1"]
    raw = json.loads((FIXTURES / "ihp_cmos_inverter.gsch").read_text())["demo2:M1"]
    assert (out["type"], out["model"], out["props"]) == (
        "nmos",
        "ihp.cells.fet_transistors.nmos",
        raw["props"],
    )


def test_top_circuit_is_written_flat_and_keeps_its_schema_name():
    nl = export("ihp_rc_filter", "ngspice")
    assert nl.top_circuit == nl.circuits[0].name == "__top__"
    assert json.loads(nl.circuits[0].properties["__info__"])["gsch_schema"] == "demo"
    assert not any(line.startswith(".subckt") for line in lines(nl))


def test_read_gsch_finds_the_models_of_a_project(tmp_path):
    (tmp_path / "build").mkdir()
    shutil.copy(FIXTURES / "models.nyanlib", tmp_path / "build")
    (tmp_path / "models.nyanlib").write_text("{}")  # build/ wins
    for name in ("ihp_hier_top.gsch", "ihp_hier_cell.gsch"):
        shutil.copy(FIXTURES / name, tmp_path)
    nl = read_gsch(tmp_path / "ihp_hier_top.gsch", corners="mos_ff")
    assert [c.name for c in nl.circuits] == ["hier_cell", "__top__"]
    assert any(d.value.endswith("mos_ff") for d in nl.directives)
    # a child missing from models.nyanlib is named after its file
    (tmp_path / "build" / "models.nyanlib").write_text("{}")
    nl = read_gsch(tmp_path / "ihp_hier_top.gsch")
    assert [c.name for c in nl.circuits] == ["ihp_hier_cell", "__top__"]
    assert [p.name for p in nl.circuits[0].ports] == ["in", "out", "vdd"]


def test_read_gsch_stops_at_a_cycle(tmp_path):
    doc = {"a:X": {"type": "ckt", "name": "X", "model": "a.gsch", "nets": {"p": "n"}},
           "a:p": {"type": "port", "name": "p", "nets": {"P": "n"}}}  # fmt: skip
    (tmp_path / "a.gsch").write_text(json.dumps(doc))
    nl = read_gsch(tmp_path / "a.gsch")
    assert [c.name for c in nl.circuits] == ["__top__"]


def test_read_gsch_rejects_a_missing_child(tmp_path):
    doc = {
        "a:X": {"type": "ckt", "name": "X", "model": "gone.gsch", "nets": {"p": "n"}}
    }
    (tmp_path / "a.gsch").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=r"gone\.gsch"):
        read_gsch(tmp_path / "a.gsch")


def test_read_gsch_rejects_two_children_with_one_circuit_name(tmp_path):
    child = {"c:p": {"type": "port", "name": "p", "nets": {"P": "n"}}}
    for name in ("a/cell.gsch", "b/cell.gsch"):
        (tmp_path / name).parent.mkdir()
        (tmp_path / name).write_text(json.dumps(child))
    doc = {
        f"t:X{i}": {"type": "ckt", "name": f"X{i}", "model": m, "nets": {"p": "n"}}
        for i, m in enumerate(("a/cell.gsch", "b/cell.gsch"))
    }
    (tmp_path / "top.gsch").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=re.escape(str(Path("b", "cell.gsch")))):
        read_gsch(tmp_path / "top.gsch")


@pytest.mark.parametrize("sim", ["spectre", "", "hspice"])
def test_unknown_simulator_is_rejected(sim):
    with pytest.raises(ValueError, match="sim"):
        parse_gsch("{}", sim=sim)


def test_simulator_names_are_case_insensitive():
    text = (FIXTURES / "ihp_rc_filter.gsch").read_text()
    assert write_spectre(parse_gsch(text, sim="VACASK")) == write_spectre(
        parse_gsch(text, sim="vacask")
    )


@pytest.mark.parametrize("sim", list(WRITERS))
@pytest.mark.parametrize("stem", sorted(p.stem for p in FIXTURES.glob("*.gsch")))
def test_export_survives_the_kfnetlist_bridge(stem, sim):
    nl = export(stem, sim)
    back = morphnet.from_netlists(morphnet.to_netlists(nl), nl.top_circuit)
    for write in (write_spice, write_spectre, write_xyce):
        assert write(back) == write(nl)
    assert json.loads(write_gsch(back)) == json.loads(write_gsch(nl))


@pytest.mark.skipif(not shutil.which("ngspice"), reason="ngspice not installed")
def test_ngspice_runs_the_rc_filter(tmp_path):
    deck = tmp_path / "rc.cir"
    text = write_spice(export("ihp_rc_filter", "ngspice"))
    deck.write_text(text.replace(".end", ".op\n.end"))
    run = subprocess.run(  # noqa: S603 - fixed binary, temp deck
        ["ngspice", "-b", str(deck)], capture_output=True, text=True, timeout=60
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "error" not in run.stdout.lower()


def test_vacask_multiplier_is_mfactor_and_left_out_when_one():
    nets = {"D": "d", "G": "g", "S": "s", "B": "b"}
    doc = {
        f"t:{name}": {
            "type": "nmos",
            "name": name,
            "nets": nets,
            "props": {"model": "nch", "m": m},
        }  # fmt: skip
        for name, m in (("M1", 2), ("M2", 1))
    }
    text = write_spectre(parse_gsch(json.dumps(doc), sim="vacask"))
    assert "m1 (d g s b) nch $mfactor=2" in text.splitlines()
    assert "m2 (d g s b) nch" in text.splitlines()
    assert "m=2" in write_spice(parse_gsch(json.dumps(doc)))


def test_an_edited_value_goes_back_to_its_mosaic_prop():
    nl = export("ihp_rc_filter", "ngspice")
    r1 = next(s for s in nl.circuits[0].subcircuits if s.name == "R1")
    r1.parameters = [parameter("value", "2k")]
    assert json.loads(write_gsch(nl))["demo:R1"]["props"] == {"resistance": "2k"}


def test_an_unwired_device_does_not_add_pins_to_a_simulated_master():
    doc = {
        "t:R1": {"type": "resistor", "name": "R1", "nets": {"P": "a", "N": "b"},
                 "props": {"resistance": "1k"}},
        "t:R2": {"type": "resistor", "name": "R2", "nets": {"P": "a", "N": "b"}},
        "t:R3": {"type": "resistor", "name": "R3", "ports": [{"name": "X"}]},
    }  # fmt: skip
    nl = parse_gsch(json.dumps(doc))
    assert [p.name for p in nl.ext_circuits[0].ports] == ["p", "n"]
    assert "R1 a b 1k" in lines(nl)


# ── open pins, source fields (fix round 1) ─────────────────────────────────────


def test_open_pins_keep_their_own_named_nodes():
    doc = {
        "t:R1": {"type": "resistor", "name": "R1", "nets": {"P": "a", "N": "net7"},
                 "props": {"resistance": "1k"}},
        "t:R2": {"type": "resistor", "name": "R2", "nets": {"P": "a", "N": "net8"},
                 "props": {"resistance": "1k"}},
    }  # fmt: skip
    nl = parse_gsch(json.dumps(doc))
    assert "R1 a net7 1k" in lines(nl)
    assert "R2 a net8 1k" in lines(nl)
    assert not any("?" in line for line in lines(nl))


def test_a_lone_tied_bulk_is_node_zero():
    doc = {
        "t:M1": {"type": "nmos", "name": "M1",
                 "nets": {"D": "d", "G": "g", "S": "s"}, "props": {"model": "nch"}},
        "t:R1": {"type": "resistor", "name": "R1", "nets": {"P": "d", "N": "g"}},
    }  # fmt: skip
    assert "M1 d g s 0 nch" in lines(parse_gsch(json.dumps(doc)))


def pulse(**tran) -> dict:
    return {
        "t:V1": {"type": "vsource", "name": "V1", "nets": {"P": "a", "N": "GND"},
                 "props": {"tran": {"type": "pulse", **tran}}},
        "t:R1": {"type": "resistor", "name": "R1", "nets": {"P": "a", "N": "GND"}},
    }  # fmt: skip


def test_an_expression_keeps_its_slot_in_a_waveform():
    doc = pulse(initial=0, pulsed="{vdd}", width="5n", period="10n")
    assert "V1 a 0 DC 0 PULSE(0 {vdd} 0 0 0 5n 10n)" in lines(
        parse_gsch(json.dumps(doc))
    )
    text = write_spectre(parse_gsch(json.dumps(doc), sim="vacask"))
    assert (  # `{}` is SPICE wrapping: VACASK writes the expression bare
        'v1 (a 0) vsource dc=0 type="pulse" val0=0 val1=vdd fall=0 width=5n period=10n'
        in text
    )


def test_an_unparsed_derived_expression_keeps_its_ngspice_braces():
    doc = {
        "t:M1": {"type": "nmos", "name": "M1", "model": "nch", "props": {"W": "1u"},
                 "nets": {"D": "d", "G": "g", "S": "GND", "B": "GND"}},
    }  # fmt: skip
    models = {
        "models:nch": {
            "name": "nch",
            "ports": [{"name": n} for n in "DGSB"],
            "models": [  # `^` is not parsed: the derived `w` stays raw
                {
                    "language": lang,
                    "name": "nch",
                    "spice-type": "M",
                    "params": {"w": "W^2"},
                }
                for lang in ("spice", "spectre")
            ],
        }  # fmt: skip
    }
    for sim, want in (("ngspice", "w={1u^2}"), ("vacask", "w=1u^2")):
        nl = parse_gsch(json.dumps(doc), models=models, sim=sim)
        assert want in WRITERS[sim](nl)


def test_a_positional_raw_value_is_not_wrapped():
    doc = {"t:V1": {"type": "vsource", "name": "V1", "nets": {"P": "a", "N": "GND"},
                    "props": {"dc": "0.9", "ac": "1"}}}  # fmt: skip
    assert "V1 a 0 DC 0.9 AC 1" in lines(parse_gsch(json.dumps(doc)))


def test_a_missing_required_waveform_field_is_an_error():
    doc = pulse(initial=0, width="5n", period="10n")
    with pytest.raises(ValueError, match=r"V1.*pulsed"):
        parse_gsch(json.dumps(doc))


# ── parse -> write_gsch is lossless (final fix wave) ───────────────────────────


@pytest.mark.parametrize("sim", list(WRITERS))
@pytest.mark.parametrize("stem", sorted(p.stem for p in FIXTURES.glob("*.gsch")))
def test_an_unedited_schematic_is_written_back_unchanged(stem, sim):
    text = (FIXTURES / f"{stem}.gsch").read_text()
    nl = parse_gsch(text, models=MODELS, sim=sim, corners=CORNERS.get(stem, ()))
    assert json.loads(write_gsch(nl)) == json.loads(text)


def test_a_model_backed_primitive_keeps_the_pins_of_its_entry():
    doc = {
        "t:V1": {"type": "vsource", "name": "V1", "nets": {"P": "in", "N": "GND"},
                 "props": {"dc": "1"}},
        "t:R1": {"type": "ckt", "model": "pdk.rpoly", "name": "R1",
                 "nets": {"A": "in", "B": "out"}, "props": {"width": 2}},
    }  # fmt: skip
    nl = parse_gsch(json.dumps(doc), models=MODELS)
    assert "R1 in out w=2" in lines(nl)  # SPICE R pins p/n
    assert json.loads(write_gsch(nl)) == doc
    for c in nl.circuits[0].connections:  # an edit still lands on the entry's pins
        if c.name == "out":
            c.name = "in"
    assert json.loads(write_gsch(nl))["t:R1"]["nets"] == {"A": "in", "B": "in"}


def test_a_tied_bulk_is_written_only_once_moved_off_ground():
    doc = {
        "t:M1": {"type": "nmos", "name": "M1",
                 "nets": {"D": "d", "G": "g", "S": "s"}, "props": {"model": "nch"}},
        "t:R1": {"type": "resistor", "name": "R1", "nets": {"P": "d", "N": "s"}},
    }  # fmt: skip
    nl = parse_gsch(json.dumps(doc))
    assert json.loads(write_gsch(nl)) == doc
    for c in nl.circuits[0].connections:
        if c.name == "GND":  # the bulk alone: move it to `s`
            c.name = "s"
    assert json.loads(write_gsch(nl))["t:M1"]["nets"] == {
        "D": "d", "G": "g", "S": "s", "B": "s"
    }  # fmt: skip


# ── source props and model-derived params (#4) ─────────────────────────────────


def inverter() -> Netlist:
    return parse_gsch((FIXTURES / "ihp_cmos_inverter.gsch").read_text(), models=MODELS)


def edited(nl: Netlist, inst: str, **settings) -> Netlist:
    """``nl`` through the kfnetlist bridge, with ``settings`` changed on ``inst``."""
    from kfnetlist import Netlist as KfNetlist

    netlists = morphnet.to_netlists(nl)
    doc = netlists[nl.top_circuit].to_dict()
    doc["instances"][inst]["settings"].update(settings)
    netlists[nl.top_circuit] = KfNetlist.from_dict(doc)
    return morphnet.from_netlists(netlists, nl.top_circuit)


def test_model_params_are_expressions_over_the_source_props():
    m1 = next(s for s in inverter().circuits[0].subcircuits if s.name == "M1")
    by_name = {p.name: p for p in m1.parameters}
    sources = {n for n, p in by_name.items() if p.properties.get("role") == "source"}
    assert sources == {"width", "length", "nf", "model"}  # `m = m`: one plain param
    assert by_name["w"].default_value.expression == parse_expression("width * 1e-6")
    assert by_name["ng"].default_value.expression == Expression(reference="nf")
    assert by_name["width"].default_value == parameter("width", 0.15).default_value
    assert "role" not in by_name["m"].properties


def test_an_edited_source_prop_reaches_the_gsch_and_the_simulation():
    raw = json.loads((FIXTURES / "ihp_cmos_inverter.gsch").read_text())["demo2:M1"]
    back = edited(inverter(), "M1", width=0.3)
    assert json.loads(write_gsch(back))["demo2:M1"]["props"] == {
        **raw["props"],
        "width": 0.3,
    }
    (m1,) = [line for line in lines(back) if line.startswith("XM1 ")]
    assert m1.endswith(" w={0.3 * 1e-6}")
    assert "width=0.3" not in m1  # a source prop is not a simulation param


def test_an_edited_derived_param_is_an_error_not_a_silent_drop():
    back = edited(inverter(), "M1", w="0.2 * 1e-6")
    message = (
        "M1: 'w' is derived from model expression 'width * 1e-6'; edit 'width' instead"
    )
    with pytest.raises(ValueError, match=re.escape(message)):
        write_gsch(back)


def test_an_edited_model_default_is_written_and_a_computed_param_is_an_error():
    text = (FIXTURES / "ihp_hier_top.gsch").read_text()
    nl = parse_gsch(text, models=MODELS)
    subs = {s.name: s for s in nl.circuits[0].subcircuits}
    # X2's `rload` is the model's default, not in the entry's props
    assert [p.name for p in subs["X2"].parameters] == ["rload"]
    subs["X2"].parameters = [parameter("rload", "2k")]
    assert json.loads(write_gsch(nl))["top:X2"]["props"]["rload"] == "2k"
    subs["M3"].parameters = [
        p if p.name != "w" else parameter("w", "9u") for p in subs["M3"].parameters
    ]
    with pytest.raises(ValueError, match="M3: 'w' is derived from"):
        write_gsch(nl)


def test_a_model_param_named_like_its_prop_survives_the_bridge():
    models = json.loads(json.dumps(MODELS))
    nmos = models["models:ihp.cells.fet_transistors.nmos"]
    for variant in nmos["models"]:
        variant["params"]["w"] = "w * 2"
    doc = json.loads((FIXTURES / "ihp_cmos_inverter.gsch").read_text())
    doc["demo2:M1"]["props"]["w"] = 0.5
    nl = parse_gsch(json.dumps(doc), models=models)
    (m1,) = [line for line in lines(nl) if line.startswith("XM1 ")]
    assert m1.endswith(" w={0.5 * 2}")
    back = morphnet.from_netlists(morphnet.to_netlists(nl), nl.top_circuit)
    assert write_spice(back) == write_spice(nl)
    assert json.loads(write_gsch(back)) == doc
    message = "M1: 'w' is derived from model expression 'w * 2'; edit 'w' instead"
    with pytest.raises(ValueError, match=re.escape(message)):
        write_gsch(edited(nl, "M1", w="3"))


# ── inline nyanlib `code` blocks are macros (#7) ───────────────────────────────


def code_models(**codes: str) -> dict:
    return {
        f"models:{name}": {
            "name": name,
            "ports": [{"name": "a"}, {"name": "b"}],
            "models": [
                {
                    "language": "spice",
                    "name": name,
                    "spice-type": "SUBCKT",
                    "code": f"\n{code}\n",
                }
            ],  # fmt: skip
        }
        for name, code in codes.items()
    }


def test_inline_code_is_a_macro_deduplicated_across_the_hierarchy(tmp_path):
    models = code_models(rdiv=".subckt rdiv a b\n.ends rdiv", rtop=".param r=1")
    models["models:cell.gsch"] = {"name": "cell", "ports": [{"name": "p"}]}
    child = {"c:X1": {"type": "ckt", "name": "X1", "model": "rdiv",
                      "nets": {"a": "p", "b": "GND"}},
             "c:p": {"type": "port", "name": "p", "nets": {"P": "p"}}}  # fmt: skip
    top = json.loads(library_doc("rtop", "rdiv"))
    top["top:C"] = {
        "type": "ckt",
        "name": "C",
        "model": "cell.gsch",
        "nets": {"p": "x"},
    }
    (tmp_path / "cell.gsch").write_text(json.dumps(child))
    (tmp_path / "top.gsch").write_text(json.dumps(top))
    nl = read_gsch(tmp_path / "top.gsch", models=models)
    assert [(m.name, m.language, m.body) for m in nl.macros] == [
        ("rtop", "spice", ".param r=1"),  # stripped, top first, rdiv once
        ("rdiv", "spice", ".subckt rdiv a b\n.ends rdiv"),
    ]
    assert ".param r=1" in lines(nl)


def macro_netlist(*macros: tuple[str, str], dialect: str = "") -> Netlist:
    from kfnetlist.morphnet.morphnet_schema import Circuit, Macro

    return Netlist(
        top_circuit="__top__",
        circuits=[
            Circuit(name="cell", macros=[Macro(name="local", language="spice",
                                               body="R1 a b 1k")]),
            Circuit(name="__top__"),
        ],
        macros=[Macro(name=n, language=lang, body=f"{n} body") for n, lang in macros],
        properties={"dialect": dialect} if dialect else {},
    )  # fmt: skip


def test_spectre_wraps_spice_macros_in_simulator_lang():
    nl = macro_netlist(("sp", "ngspice"), ("sc", "spectre"))
    text = write_spectre(nl).splitlines()
    assert text[:4] == [
        "simulator lang=spice",
        "sp body",
        "simulator lang=spectre",
        "sc body",
    ]
    assert text[4:8] == [  # a circuit's own macros go inside its subckt
        "subckt cell ()",
        "simulator lang=spice",
        "R1 a b 1k",
        "simulator lang=spectre",
    ]
    assert lines(macro_netlist(("sp", "xyce")))[1:2] == ["sp body"]


@pytest.mark.parametrize(
    ("writer", "dialect", "comment"),
    [
        ("write_spice", "", "*"),
        ("write_hspice", "", "*"),
        ("write_spectre", "vacask", "//"),
        ("write_systemverilog", "", "//"),
        ("write_vams", "", "//"),
    ],
)
def test_a_macro_in_another_language_is_a_comment_and_a_warning(
    writer, dialect, comment
):
    from kfnetlist.morphnet import netlist as writers

    nl = macro_netlist(("va", "verilog-a-ish"), dialect=dialect)
    with pytest.warns(UserWarning, match=r"skipped macro va \(verilog-a-ish\)"):
        text = getattr(writers, writer)(nl)
    assert f"{comment} skipped macro va (verilog-a-ish)" in text.splitlines()
    assert "va body" not in text


def test_vacask_skips_the_spectre_code_nyancad_drops():
    with pytest.warns(UserWarning, match=r"skipped macro rdiv \(spectre\)"):
        text = write_spectre(export("demo_inline_code", "vacask"))
    assert "// skipped macro rdiv (spectre)" in text.splitlines()


def test_an_expression_reading_a_colliding_prop_gets_its_value():
    models = json.loads(json.dumps(MODELS))
    nmos = models["models:ihp.cells.fet_transistors.nmos"]
    for variant in nmos["models"]:
        variant["params"].update(w="w * 2", ad="w * 0.5")
    doc = json.loads((FIXTURES / "ihp_cmos_inverter.gsch").read_text())
    doc["demo2:M1"]["props"]["w"] = 0.5
    nl = parse_gsch(json.dumps(doc), models=models)
    (m1,) = [line for line in lines(nl) if line.startswith("XM1 ")]
    assert " w={0.5 * 2} " in f"{m1} " and " ad={0.5 * 0.5}" in f" {m1}"
    back = morphnet.from_netlists(morphnet.to_netlists(nl), nl.top_circuit)
    assert write_spice(back) == write_spice(nl)
    assert json.loads(write_gsch(back)) == doc
    message = "M1: 'ad' is derived from model expression 'w * 0.5'; edit 'w' instead"
    with pytest.raises(ValueError, match=re.escape(message)):
        write_gsch(edited(nl, "M1", ad="3"))


def test_same_named_code_with_different_bodies_is_all_kept_with_a_warning():
    models = code_models(ra=".param ra=1", rb=".param rb=2")
    for model in models.values():
        model["models"][0]["name"] = "shared"
    with pytest.warns(UserWarning, match="macro 'shared'"):
        nl = parse_gsch(library_doc("ra", "rb"), models=models)
    assert {".param ra=1", ".param rb=2"} <= set(lines(nl))


def test_nameless_code_entries_are_not_collapsed():
    models = code_models(ra=".param ra=1", rb=".param rb=2")
    for model in models.values():
        del model["models"][0]["name"]
    nl = parse_gsch(library_doc("ra", "rb"), models=models)
    assert [m.body for m in nl.macros] == [".param ra=1", ".param rb=2"]


def test_code_without_a_language_is_spice():
    models = code_models(ra=".param ra=1")
    entry = models["models:ra"]["models"][0]
    del entry["language"]
    entry["implementation"] = "ngspice"
    nl = parse_gsch(library_doc("ra"), models=models)
    assert [m.language for m in nl.macros] == ["spice"]
    assert ".param ra=1" in lines(nl)


def test_sources_are_stimuli_of_the_simulation():
    nl = export("ihp_hier_top", "ngspice")
    stimuli = {s.name: s for s in nl.simulation.stimuli}
    assert set(stimuli) == {"__top__/V1", "__top__/V2", "__top__/I1"}
    v1 = next(s for s in nl.circuits[-1].subcircuits if s.name == "V1")
    assert v1.properties["stimulus"] == "__top__/V1"
    assert v1.parameters == []
    pulse = stimuli["__top__/V1"].waveform
    assert pulse.kind == WaveformKind.PULSE
    assert pulse.args["val1"] == parameter_value("1.8")
    sine = stimuli["__top__/I1"]
    assert sine.ac_magnitude == parameter_value("1")
    assert sine.waveform.args["sinedc"] == parameter_value("1m")


def test_the_simulator_does_not_change_a_stimulus():
    ngspice = export("ihp_hier_top", "ngspice").simulation
    assert ngspice == export("ihp_hier_top", "vacask").simulation


def test_an_edited_stimulus_goes_back_to_its_props():
    nl = export("ihp_hier_top", "ngspice")
    v2 = next(s for s in nl.simulation.stimuli if s.name == "__top__/V2")
    v2.dc = parameter_value("2.5")
    assert json.loads(write_gsch(nl))["top:V2"]["props"] == {"dc": "2.5"}
    assert "V2 vdd 0 DC 2.5" in lines(nl)
    i1 = next(s for s in nl.simulation.stimuli if s.name == "__top__/I1")
    i1.waveform.args["ampl"] = parameter_value("2m")
    tran = json.loads(write_gsch(nl))["top:I1"]["props"]["tran"]
    assert tran == {"type": "sin", "offset": "1m", "amplitude": "2m",
                    "frequency": "1meg"}  # fmt: skip


def test_a_source_in_a_child_schematic_is_named_after_its_circuit(tmp_path):
    child = {
        "c:V1": {"type": "vsource", "name": "V1", "nets": {"P": "p", "N": "GND"},
                 "props": {"dc": "1"}},
        "c:p": {"type": "port", "name": "p", "nets": {"P": "p"}},
    }  # fmt: skip
    top = {
        "t:X": {"type": "ckt", "name": "X", "model": "cell.gsch", "nets": {"p": "n"}},
        "t:R": {"type": "resistor", "name": "R", "nets": {"P": "n", "N": "GND"},
                "props": {"resistance": "1k"}},
    }  # fmt: skip
    (tmp_path / "cell.gsch").write_text(json.dumps(child))
    (tmp_path / "top.gsch").write_text(json.dumps(top))
    nl = read_gsch(tmp_path / "top.gsch")
    assert [s.name for s in nl.simulation.stimuli] == ["cell/V1"]
    v1 = nl.circuits[0].subcircuits[0]
    assert (nl.circuits[0].name, v1.properties["stimulus"]) == ("cell", "cell/V1")
    assert "V1 p 0 DC 1" in write_spice(nl)
