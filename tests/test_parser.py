"""Tests for kfnetlist.extract._parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from klayout import db as kdb

DATA_DIR = Path(__file__).parent / "data"

from kfnetlist.extract._parser import (
    _discover_layer_regions,
    _layer_display_name,
    _net_shapes_by_layer,
    _serialize_circuit,
    _serialize_net,
    l2n_to_json,
    parse_l2n,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_l2n() -> tuple[kdb.LayoutToNetlist, kdb.LayerInfo, kdb.LayerInfo]:
    """Two-cell hierarchy with M1 and M2, two named nets in TOP."""
    ly = kdb.Layout()
    ly.dbu = 0.001
    m1_info = kdb.LayerInfo(1, 0, "M1")
    m2_info = kdb.LayerInfo(2, 0, "M2")
    l1 = ly.layer(m1_info)
    l2 = ly.layer(m2_info)

    leaf = ly.create_cell("LEAF")
    leaf.shapes(l1).insert(kdb.Box(0, 0, 1000, 1000))
    leaf.shapes(l1).insert(kdb.Text("PIN_A", kdb.Trans(kdb.Point(500, 500))))

    top = ly.create_cell("TOP")
    top.insert(kdb.CellInstArray(leaf.cell_index(), kdb.Trans()))
    top.shapes(l1).insert(kdb.Box(0, 0, 2000, 100))
    top.shapes(l2).insert(kdb.Box(500, 500, 1500, 600))
    top.shapes(l1).insert(kdb.Text("NET_X", kdb.Trans(kdb.Point(100, 50))))

    l2n = kdb.LayoutToNetlist(
        kdb.RecursiveShapeIterator(ly, top, [])
    )
    r1 = l2n.make_layer(l1, "M1")
    r2 = l2n.make_layer(l2, "M2")
    l2n.connect(r1)
    l2n.connect(r2)
    l2n.connect(r1, r2)
    l2n.extract_netlist()
    return l2n, m1_info, m2_info


@pytest.fixture()
def l2n_fixture() -> tuple[kdb.LayoutToNetlist, kdb.LayerInfo, kdb.LayerInfo]:
    return _build_l2n()


# ---------------------------------------------------------------------------
# _layer_display_name
# ---------------------------------------------------------------------------

class TestLayerDisplayName:
    def test_named_layer(self) -> None:
        info = kdb.LayerInfo(1, 0, "M1")
        assert _layer_display_name(info) == "M1"

    def test_unnamed_layer_falls_back(self) -> None:
        info = kdb.LayerInfo(3, 5)
        assert _layer_display_name(info) == "3/5"


# ---------------------------------------------------------------------------
# _discover_layer_regions
# ---------------------------------------------------------------------------

class TestDiscoverLayerRegions:
    def test_returns_registered_layers(self, l2n_fixture) -> None:
        l2n, m1_info, m2_info = l2n_fixture
        regions = _discover_layer_regions(l2n)
        layer_names = {_layer_display_name(info) for info in regions}
        assert "M1" in layer_names
        assert "M2" in layer_names

    def test_values_are_regions(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        regions = _discover_layer_regions(l2n)
        for region in regions.values():
            assert isinstance(region, kdb.Region)


# ---------------------------------------------------------------------------
# _net_shapes_by_layer
# ---------------------------------------------------------------------------

class TestNetShapesByLayer:
    def test_returns_shapes_for_occupied_layers(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        top_circuit = l2n.netlist().circuit_by_name("TOP")
        for net in top_circuit.each_net():
            shapes = _net_shapes_by_layer(net, l2n, layer_regions)
            for info, region in shapes.items():
                assert not region.is_empty()

    def test_empty_layer_regions_returns_empty(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        top_circuit = l2n.netlist().circuit_by_name("TOP")
        net = next(iter(top_circuit.each_net()))
        assert _net_shapes_by_layer(net, l2n, {}) == {}


# ---------------------------------------------------------------------------
# _serialize_net
# ---------------------------------------------------------------------------

class TestSerializeNet:
    def test_returns_none_for_empty_net(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        top_circuit = l2n.netlist().circuit_by_name("TOP")
        for net in top_circuit.each_net():
            result = _serialize_net(net, l2n, layer_regions, set(), None, None)
            if result is not None:
                assert "name" in result

    def test_net_with_pins(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        leaf_circuit = l2n.netlist().circuit_by_name("LEAF")
        for net in leaf_circuit.each_net():
            if net.name == "PIN_A":
                result = _serialize_net(
                    net, l2n, layer_regions, None, None, None
                )
                assert result is not None
                assert result["name"] == "PIN_A"
                assert "pins" in result
                assert "PIN_A" in result["pins"]
                break

    def test_net_with_subcircuit_pins(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        top_circuit = l2n.netlist().circuit_by_name("TOP")
        found = False
        for net in top_circuit.each_net():
            result = _serialize_net(net, l2n, layer_regions, None, None, None)
            if result is not None and "subcircuit_pins" in result:
                found = True
                for sp in result["subcircuit_pins"]:
                    assert "subcircuit" in sp
                    assert "pin" in sp
        assert found

    def test_include_layers_filters(self, l2n_fixture) -> None:
        l2n, m1_info, m2_info = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        nonexistent_layer = kdb.LayerInfo(99, 0, "FAKE")
        top_circuit = l2n.netlist().circuit_by_name("TOP")
        for net in top_circuit.each_net():
            result = _serialize_net(
                net, l2n, layer_regions, None, {nonexistent_layer}, None
            )
            assert result is None

    def test_exclude_layers_filters(self, l2n_fixture) -> None:
        l2n, m1_info, m2_info = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        all_infos = set(layer_regions.keys())
        top_circuit = l2n.netlist().circuit_by_name("TOP")
        for net in top_circuit.each_net():
            result = _serialize_net(
                net, l2n, layer_regions, None, None, all_infos
            )
            assert result is None

    def test_layer_polygons_populated(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        leaf_circuit = l2n.netlist().circuit_by_name("LEAF")
        for net in leaf_circuit.each_net():
            result = _serialize_net(net, l2n, layer_regions, None, None, None)
            if result is not None and "layer_to_polygons" in result:
                for layer_name, polys in result["layer_to_polygons"].items():
                    assert isinstance(layer_name, str)
                    assert isinstance(polys, list)
                    for poly in polys:
                        for pt in poly:
                            assert len(pt) == 2
                            assert isinstance(pt[0], int)
                            assert isinstance(pt[1], int)

    def test_no_l2n_skips_shapes(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        leaf_circuit = l2n.netlist().circuit_by_name("LEAF")
        for net in leaf_circuit.each_net():
            result = _serialize_net(net, None, {}, None, None, None)
            if result is not None:
                assert "layer_to_polygons" not in result


# ---------------------------------------------------------------------------
# _serialize_circuit
# ---------------------------------------------------------------------------

class TestSerializeCircuit:
    def test_leaf_circuit_has_pins_and_nets(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        leaf = l2n.netlist().circuit_by_name("LEAF")
        result = _serialize_circuit(
            leaf, l2n, layer_regions, None, None, None, None
        )
        assert "pins" in result
        assert "PIN_A" in result["pins"]
        assert "nets" in result

    def test_top_circuit_has_subcircuits(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        top = l2n.netlist().circuit_by_name("TOP")
        result = _serialize_circuit(
            top, l2n, layer_regions, None, None, None, None
        )
        assert "subcircuits" in result
        refs = [s["circuit_ref"] for s in result["subcircuits"]]
        assert "LEAF" in refs

    def test_include_instances_filter(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        top = l2n.netlist().circuit_by_name("TOP")
        result = _serialize_circuit(
            top, l2n, layer_regions, {"NONEXISTENT"}, None, None, None
        )
        assert result.get("subcircuits", []) == []

    def test_exclude_instances_filter(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        top = l2n.netlist().circuit_by_name("TOP")
        result = _serialize_circuit(
            top, l2n, layer_regions, None, {"LEAF"}, None, None
        )
        assert result.get("subcircuits", []) == []

    def test_unnamed_subcircuit_gets_dollar_id(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        top = l2n.netlist().circuit_by_name("TOP")
        result = _serialize_circuit(
            top, l2n, layer_regions, None, None, None, None
        )
        for sc in result.get("subcircuits", []):
            if sc["name"].startswith("$"):
                assert sc["name"][1:].isdigit()

    def test_pins_are_sorted(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        layer_regions = _discover_layer_regions(l2n)
        leaf = l2n.netlist().circuit_by_name("LEAF")
        result = _serialize_circuit(
            leaf, l2n, layer_regions, None, None, None, None
        )
        pins = result.get("pins", [])
        assert pins == sorted(pins)


# ---------------------------------------------------------------------------
# parse_l2n
# ---------------------------------------------------------------------------

class TestParseL2N:
    def test_top_level_keys(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n)
        assert "top_circuit" in result
        assert "dbu" in result
        assert "layers" in result
        assert "circuits" in result

    def test_top_circuit_name(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n)
        assert result["top_circuit"] == "TOP"

    def test_dbu(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n)
        assert result["dbu"] == pytest.approx(0.001)

    def test_layers_reported(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n)
        layer_names = [l["name"] for l in result["layers"]]
        assert "M1" in layer_names
        assert "M2" in layer_names
        assert layer_names == sorted(layer_names)
        for entry in result["layers"]:
            assert "layer" in entry
            assert "datatype" in entry

    def test_both_circuits_present(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n)
        assert "TOP" in result["circuits"]
        assert "LEAF" in result["circuits"]

    def test_flatten_collapses_hierarchy(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n, flatten=True)
        assert list(result["circuits"].keys()) == ["TOP"]
        top_data = result["circuits"]["TOP"]
        assert "subcircuits" not in top_data or top_data["subcircuits"] == []

    def test_flatten_skips_layer_annotation(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n, flatten=True)
        for net in result["circuits"]["TOP"].get("nets", []):
            assert "layer_to_polygons" not in net

    def test_include_layers(self, l2n_fixture) -> None:
        l2n, m1_info, m2_info = l2n_fixture
        result = parse_l2n(l2n, include_layers=[m1_info])
        layer_names = [l["name"] for l in result["layers"]]
        assert "M1" in layer_names
        assert "M2" not in layer_names

    def test_exclude_layers(self, l2n_fixture) -> None:
        l2n, m1_info, m2_info = l2n_fixture
        result = parse_l2n(l2n, exclude_layers=[m2_info])
        layer_names = [l["name"] for l in result["layers"]]
        assert "M1" in layer_names
        assert "M2" not in layer_names

    def test_include_instances(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n, include_instances=["LEAF"])
        top_data = result["circuits"]["TOP"]
        refs = [s["circuit_ref"] for s in top_data.get("subcircuits", [])]
        assert all(r == "LEAF" for r in refs)

    def test_exclude_instances(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n, exclude_instances=["LEAF"])
        top_data = result["circuits"]["TOP"]
        assert top_data.get("subcircuits", []) == []

    def test_filters_ignored_when_flattened(self, l2n_fixture) -> None:
        l2n, m1_info, _ = l2n_fixture
        result = parse_l2n(
            l2n,
            flatten=True,
            include_layers=[m1_info],
            include_instances=["LEAF"],
        )
        assert list(result["circuits"].keys()) == ["TOP"]


# ---------------------------------------------------------------------------
# l2n_to_json
# ---------------------------------------------------------------------------

class TestL2NToJson:
    def test_returns_valid_json(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        text = l2n_to_json(l2n)
        parsed = json.loads(text)
        assert parsed["top_circuit"] == "TOP"

    def test_custom_indent(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        text = l2n_to_json(l2n, indent=4)
        assert "    " in text

    def test_flatten_kwarg_forwarded(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        text = l2n_to_json(l2n, flatten=True)
        parsed = json.loads(text)
        assert list(parsed["circuits"].keys()) == ["TOP"]

    def test_roundtrip_consistency(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        text = l2n_to_json(l2n)
        parsed = json.loads(text)
        direct = parse_l2n(l2n)
        assert parsed == direct


# ---------------------------------------------------------------------------
# Golden-file tests against tests/data/
# ---------------------------------------------------------------------------

class TestGoldenFiles:
    def test_hierarchical_matches_golden(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n)
        expected = json.loads(
            (DATA_DIR / "parse_l2n_hierarchical.json").read_text()
        )
        assert result == expected

    def test_flat_matches_golden(self, l2n_fixture) -> None:
        l2n, _, _ = l2n_fixture
        result = parse_l2n(l2n, flatten=True)
        expected = json.loads(
            (DATA_DIR / "parse_l2n_flat.json").read_text()
        )
        assert result == expected
