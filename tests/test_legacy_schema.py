"""Outputs captured from the pre-morphnet schema (main @ 821b23a) still load unchanged."""

import json
import warnings
from pathlib import Path

import pytest

from kfnetlist.kfnetlist_schema import (
    ParameterValue,
    PrefixedValue,
    ProtoCircuit,
    SIPrefix,
    TopLevelModule,
)

LEGACY = json.loads(
    (Path(__file__).parent / "data/legacy_schema_v0_3.json").read_text()
)


@pytest.mark.parametrize("name", ["doc", "pic"])
def test_legacy_document_bytes_and_json_load_identically(name):
    from_json = TopLevelModule.from_json(LEGACY[f"{name}_json"])
    from_bytes = TopLevelModule.from_proto(bytes.fromhex(LEGACY[f"{name}_proto"]))
    assert from_bytes == from_json
    # Re-encoding with the morphnet-shaped wire format is lossless too.
    assert TopLevelModule.from_proto(from_json.to_proto()) == from_json
    assert from_bytes.to_netlists() == from_json.to_netlists()


@pytest.mark.parametrize("key", ["circuit_dict", "circuit_json"])
def test_legacy_proto_fields_survive(key):
    load = ProtoCircuit.from_dict if key == "circuit_dict" else ProtoCircuit.from_json
    with pytest.warns(DeprecationWarning, match="removed"):
        circuit = load(LEGACY[key])
    # Re-loading upgraded data is warning-free, and bytes keep the moved values.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert ProtoCircuit.from_dict(circuit.to_dict()) == circuit
    for c in (circuit, ProtoCircuit.from_proto(circuit.to_proto())):
        with pytest.warns(DeprecationWarning):
            module = c.modules[0]
            terminal = module.terminal[0]
            ref = module.module_references[0]
            pv = ParameterValue(
                prefixed_value=PrefixedValue(double_value=2.5, prefix=SIPrefix.MICRO)
            )
            assert c.domain == "optical"
            assert c.ext_modules[0].domain == "electrical"
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
