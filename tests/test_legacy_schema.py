"""Outputs captured from the pre-rename schema (main @ 821b23a) still load unchanged."""

import json
import warnings
from pathlib import Path

import pytest

from kfnetlist import kfnetlist_schema
from kfnetlist.kfnetlist_schema import (
    NetlistDocument,
    ParameterValue,
    PrefixedValue,
    ProtoCircuit,
    ProtoNetlist,
    SIPrefix,
)

LEGACY = json.loads(
    (Path(__file__).parent / "data/legacy_schema_v0_3.json").read_text()
)


@pytest.mark.parametrize("name", ["doc", "pic"])
def test_legacy_document_bytes_and_json_load_identically(name):
    from_json = NetlistDocument.from_json(LEGACY[f"{name}_json"])
    from_bytes = NetlistDocument.from_proto(bytes.fromhex(LEGACY[f"{name}_proto"]))
    assert from_bytes == from_json
    # Re-encoding with the current wire format is lossless too.
    assert NetlistDocument.from_proto(from_json.to_proto()) == from_json
    assert from_bytes.to_netlists() == from_json.to_netlists()


@pytest.mark.parametrize("key", ["circuit_dict", "circuit_json"])
def test_legacy_proto_fields_survive(key):
    load = ProtoNetlist.from_dict if key == "circuit_dict" else ProtoNetlist.from_json
    with pytest.warns(DeprecationWarning, match="removed"):
        netlist = load(LEGACY[key])
    # Re-loading upgraded data is warning-free, and bytes keep the moved values.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert ProtoNetlist.from_dict(netlist.to_dict()) == netlist
    pv = ParameterValue(
        prefixed_value=PrefixedValue(double_value=2.5, prefix=SIPrefix.MICRO)
    )
    for n in (netlist, ProtoNetlist.from_proto(netlist.to_proto())):
        # Current names.
        circuit = n.circuits[0]
        sub = circuit.subcircuits[0]
        assert (n.top_circuit, circuit.name, sub.circuit_name) == ("m", "m", "wg")
        assert circuit.terminals[0].properties["__cross_section__"] == "xs_sc"
        # Pre-rename getters still read the same values.
        with pytest.warns(DeprecationWarning):
            module = n.modules[0]
            terminal = module.terminal[0]
            ref = module.module_references[0]
            assert n.top_module == "m"
            assert ref.module_name == "wg"
            assert n.domain == "optical"
            assert n.ext_modules[0].domain == "electrical"
            assert module.uid == 7
            assert (terminal.uid, terminal.cross_section) == (3, "xs_sc")
            assert (int(terminal.direction), int(terminal.domain), terminal.width) == (
                1,
                2,
                4,
            )
            assert module.parameters[0].uid == 5
            assert ref.parameter_values == [pv]
            assert ref.parameter_overrides == {"length": pv}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("ProtoModule", "ProtoCircuit"),
        ("ProtoModuleReference", "ProtoSubCircuit"),
        ("ExternalModule", "ExternalCircuit"),
        ("TopLevelModule", "NetlistDocument"),
        ("Module", "CircuitDocument"),
        ("Instance", "SubCircuitDocument"),
    ],
)
def test_pre_rename_schema_names_warn(old, new):
    with pytest.warns(DeprecationWarning, match=f"use {new}"):
        assert getattr(kfnetlist_schema, old) is getattr(kfnetlist_schema, new)


def test_pre_rename_keyword_arguments_and_methods_warn():
    with pytest.warns(DeprecationWarning, match="renamed"):
        netlist = ProtoNetlist(top_module="m", modules=[ProtoCircuit(name="m")])
    assert (netlist.top_circuit, netlist.circuits[0].name) == ("m", "m")
    assert ProtoNetlist.from_proto(netlist.to_proto()) == netlist
    doc = NetlistDocument.from_yaml("instances: {a: {component: coupler}}")
    with pytest.warns(DeprecationWarning, match="to_proto_netlist"):
        proto = doc.to_proto_circuit()
    assert proto == doc.to_proto_netlist()
    with pytest.warns(DeprecationWarning, match="from_proto_netlist"):
        assert NetlistDocument.from_proto_circuit(proto) == doc
