"""
Tests for kfnetlist.kfnetlist_schema:
  - JSON round-trips (NetlistDocument)
  - YAML round-trips (NetlistDocument)
  - schema.pic.yaml parsing
  - Forward elaboration: NetlistDocument → Netlist
  - Reverse elaboration: Netlist → NetlistDocument
  - Full structural round-trip
  - Type alias identity
  - Protobuf byte round-trips through the Rust schema crate
  - Protobuf byte round-trips through Rust-backed types
"""

from __future__ import annotations

import pathlib

import pytest

import kfnetlist
from kfnetlist.kfnetlist_schema import (
    ArraySpec,
    SubCircuitDocument,
    CircuitDocument,
    ModuleNetlist,
    Netlist,
    NetlistPort,
    PortRef,
    ProtoNetlist,
    ProtoCircuit,
    Terminal,
    NetlistDocument,
    InstanceRef,
    load_pic_yaml,
)

SCHEMA_YAML = (
    pathlib.Path(__file__).parent.parent / "kfnetlist-schema" / "schema.pic.yaml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_doc() -> NetlistDocument:
    return NetlistDocument(
        modules={
            "buf": CircuitDocument(
                instances={
                    "mzi": SubCircuitDocument(
                        component="mzi_phase_shifter", settings={"delta_length": 3}
                    )
                },
                ports={"o1": "mzi,o1", "o2": "mzi,o2"},
            )
        },
        toplevel="buf",
    )


def _multi_module_doc() -> NetlistDocument:
    return NetlistDocument(
        modules={
            "child": CircuitDocument(
                instances={
                    "mzi": SubCircuitDocument(
                        component="mzi", settings={"length": 10.0}
                    )
                },
                ports={"in": "mzi,o1", "out": "mzi,o2"},
            ),
            "parent": CircuitDocument(
                instances={
                    "sub": SubCircuitDocument(component="child"),
                    "pad": SubCircuitDocument(component="pad_array", settings={"n": 2}),
                },
                ports={"o1": "sub,in"},
                nets=[["sub,out", "pad,e4"]],
            ),
        },
        toplevel="parent",
    )


# ---------------------------------------------------------------------------
# 1. JSON round-trips
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_simple(self):
        doc = _simple_doc()
        serialized = doc.model_dump_json()
        recovered = NetlistDocument.model_validate_json(serialized)
        assert recovered.toplevel == doc.toplevel
        assert list(recovered.modules) == list(doc.modules)
        assert recovered.modules["buf"].ports == doc.modules["buf"].ports

    def test_multi_module(self):
        doc = _multi_module_doc()
        serialized = doc.model_dump_json()
        recovered = NetlistDocument.model_validate_json(serialized)
        assert recovered.toplevel == "parent"
        assert set(recovered.modules) == {"child", "parent"}
        assert recovered.modules["parent"].nets == [["sub,out", "pad,e4"]]

    def test_instance_with_array(self):
        doc = NetlistDocument(
            modules={
                "top": CircuitDocument(
                    instances={
                        "arr": SubCircuitDocument(
                            component="mzi", array=ArraySpec(na=3, nb=2)
                        )
                    }
                )
            },
            toplevel="top",
        )
        recovered = NetlistDocument.model_validate_json(doc.model_dump_json())
        arr_inst = recovered.modules["top"].instances["arr"]
        assert arr_inst.array is not None
        assert arr_inst.array.na == 3
        assert arr_inst.array.nb == 2


# ---------------------------------------------------------------------------
# 2. YAML round-trips
# ---------------------------------------------------------------------------


class TestYamlRoundTrip:
    def _yaml_rt(self, doc: NetlistDocument) -> NetlistDocument:
        return NetlistDocument.from_yaml(doc.to_yaml())

    def test_simple(self):
        doc = _simple_doc()
        recovered = self._yaml_rt(doc)
        assert recovered.toplevel == doc.toplevel
        assert (
            recovered.modules["buf"].instances["mzi"].component == "mzi_phase_shifter"
        )

    def test_multi_module(self):
        doc = _multi_module_doc()
        recovered = self._yaml_rt(doc)
        assert recovered.toplevel == "parent"
        assert recovered.modules["parent"].nets == [["sub,out", "pad,e4"]]


# ---------------------------------------------------------------------------
# 3. schema.pic.yaml parsing
# ---------------------------------------------------------------------------


class TestSchemaPicYaml:
    @pytest.fixture
    def doc(self) -> NetlistDocument:
        return load_pic_yaml(SCHEMA_YAML)

    def test_module_count(self, doc):
        assert len(doc.modules) == 2

    def test_toplevel(self, doc):
        assert doc.toplevel == "my_second_component"

    def test_module_names(self, doc):
        assert set(doc.modules) == {"my_component", "my_second_component"}

    def test_my_component_instances(self, doc):
        mod = doc.modules["my_component"]
        assert "mzi" in mod.instances
        assert "pads" in mod.instances
        assert mod.instances["mzi"].component == "mzi_phase_shifter"
        assert mod.instances["pads"].component == "pad_array"

    def test_my_component_ports(self, doc):
        mod = doc.modules["my_component"]
        assert "o1" in mod.ports
        assert "o2" in mod.ports

    def test_my_second_component_instances(self, doc):
        mod = doc.modules["my_second_component"]
        assert "my_sub_module" in mod.instances
        assert mod.instances["my_sub_module"].component == "my_component"
        assert "mzi_array" in mod.instances
        assert "mzi" in mod.instances
        assert "pads" in mod.instances

    def test_sub_module_settings(self, doc):
        sub = doc.modules["my_second_component"].instances["my_sub_module"]
        assert sub.settings.get("length") == 50.0

    def test_placements_preserved(self, doc):
        mod = doc.modules["my_component"]
        assert "mzi" in mod.placements
        assert "pads" in mod.placements

    def test_routes_preserved(self, doc):
        mod = doc.modules["my_component"]
        assert "electrical" in mod.routes


# ---------------------------------------------------------------------------
# 4. Forward elaboration: NetlistDocument → Netlist
# ---------------------------------------------------------------------------


class TestForwardElaboration:
    def test_simple_instances(self):
        doc = _simple_doc()
        netlists = doc.to_netlists()
        assert "buf" in netlists
        nl = netlists["buf"]
        assert nl.has_instance("mzi")
        inst = nl.get_instance("mzi")
        assert inst.component == "mzi_phase_shifter"

    def test_instance_settings(self):
        doc = _simple_doc()
        nl = doc.to_netlists()["buf"]
        inst = nl.get_instance("mzi")
        assert inst.settings.get("delta_length") == 3

    def test_ports_become_nets(self):
        doc = _simple_doc()
        nl = doc.to_netlists()["buf"]
        # Each port exposure creates a net: NetlistPort("o1") ↔ PortRef("mzi","o1")
        port_names = {p.name for p in nl.ports}
        assert "o1" in port_names
        assert "o2" in port_names

    def test_explicit_net(self):
        doc = NetlistDocument(
            modules={
                "top": CircuitDocument(
                    instances={
                        "a": SubCircuitDocument(component="comp_a"),
                        "b": SubCircuitDocument(component="comp_b"),
                    },
                    nets=[["a,out", "b,in"]],
                )
            },
            toplevel="top",
        )
        nl = doc.to_netlists()["top"]
        assert nl.nets is not None

    def test_array_instance(self):
        doc = NetlistDocument(
            modules={
                "top": CircuitDocument(
                    instances={
                        "arr": SubCircuitDocument(
                            component="mzi", array=ArraySpec(na=3, nb=1)
                        )
                    }
                )
            },
            toplevel="top",
        )
        nl = doc.to_netlists()["top"]
        inst = nl.get_instance("arr")
        assert inst.array is not None
        assert inst.array.na == 3

    def test_schema_pic_yaml(self):
        doc = load_pic_yaml(SCHEMA_YAML)
        netlists = doc.to_netlists()
        assert "my_component" in netlists
        assert "my_second_component" in netlists
        nl_parent = netlists["my_second_component"]
        assert nl_parent.has_instance("my_sub_module")
        assert nl_parent.has_instance("mzi_array")


# ---------------------------------------------------------------------------
# 5. Reverse elaboration: Netlist → NetlistDocument
# ---------------------------------------------------------------------------


class TestReverseElaboration:
    def _make_nl(self) -> Netlist:
        nl = Netlist()
        nl.create_port("o1")
        nl.create_inst(
            "mzi", kcl="", component="mzi_phase_shifter", settings={"delta_length": 3}
        )
        nl.create_net(NetlistPort("o1"), PortRef("mzi", "o1"))
        return nl

    def test_round_trip_single(self):
        nl = self._make_nl()
        doc = NetlistDocument.from_netlists({"buf": nl}, toplevel="buf")
        assert doc.toplevel == "buf"
        assert "buf" in doc.modules
        mod = doc.modules["buf"]
        assert "mzi" in mod.instances
        assert mod.instances["mzi"].component == "mzi_phase_shifter"

    def test_ports_recovered(self):
        nl = self._make_nl()
        mod = CircuitDocument.from_netlist("buf", nl)
        assert "o1" in mod.ports
        assert mod.ports["o1"] == "mzi,o1"

    def test_settings_preserved(self):
        nl = self._make_nl()
        mod = CircuitDocument.from_netlist("buf", nl)
        assert mod.instances["mzi"].settings.get("delta_length") == 3

    def test_multi_module(self):
        nl1, nl2 = Netlist(), Netlist()
        nl1.create_inst("sub_a", kcl="", component="comp_a")
        nl2.create_inst("sub_b", kcl="", component="comp_b")
        doc = NetlistDocument.from_netlists(
            {"mod_a": nl1, "mod_b": nl2}, toplevel="mod_b"
        )
        assert set(doc.modules) == {"mod_a", "mod_b"}
        assert doc.toplevel == "mod_b"


# ---------------------------------------------------------------------------
# 6. Full structural round-trip
# ---------------------------------------------------------------------------


class TestFullRoundTrip:
    def test_doc_to_netlists_and_back(self):
        original = _multi_module_doc()
        netlists = original.to_netlists()
        recovered = NetlistDocument.from_netlists(netlists, toplevel=original.toplevel)
        for mod_name, orig_mod in original.modules.items():
            assert mod_name in recovered.modules
            rec_mod = recovered.modules[mod_name]
            for inst_name in orig_mod.instances:
                assert inst_name in rec_mod.instances
                assert (
                    rec_mod.instances[inst_name].component
                    == orig_mod.instances[inst_name].component
                )

    def test_schema_pic_yaml_full_round_trip(self):
        doc = load_pic_yaml(SCHEMA_YAML)
        netlists = doc.to_netlists()
        recovered = NetlistDocument.from_netlists(netlists, toplevel=doc.toplevel)
        assert recovered.toplevel == doc.toplevel
        for mod_name in doc.modules:
            assert mod_name in recovered.modules


# ---------------------------------------------------------------------------
# 7. Type alias identity
# ---------------------------------------------------------------------------


class TestTypeAliases:
    def test_netlist_alias(self):
        from kfnetlist.kfnetlist_schema import Netlist as SchemaNetlist

        assert SchemaNetlist is kfnetlist.Netlist

    def test_net_alias(self):
        from kfnetlist.kfnetlist_schema import Net as SchemaNet

        assert SchemaNet is kfnetlist.Net

    def test_netlist_instance_alias(self):
        from kfnetlist.kfnetlist_schema import NetlistInstance as SchemaInstance

        assert SchemaInstance is kfnetlist.NetlistInstance

    def test_module_netlist_alias(self):
        assert ModuleNetlist is kfnetlist.Netlist

    def test_instance_ref_alias(self):
        assert InstanceRef is kfnetlist.NetlistInstance


# ---------------------------------------------------------------------------
# 8. Proto round-trip
# ---------------------------------------------------------------------------


class TestProtoRoundTrip:
    def test_proto_netlist_model_round_trip(self):
        model = ProtoNetlist(
            name="test_circuit",
            top_circuit="mod_a",
            circuits=[ProtoCircuit(name="mod_a", terminals=[Terminal(name="o1")])],
        )
        wire = model.to_proto()
        assert isinstance(wire, bytes)
        back = ProtoNetlist.from_proto(wire)
        assert back == model
        assert back.circuits[0].terminals[0].name == "o1"

    def test_netlist_document_to_proto_netlist(self):
        doc = _simple_doc()
        netlist = doc.to_proto_netlist()
        assert netlist.top_circuit == "buf"
        assert len(netlist.circuits) == 1
        assert netlist.circuits[0].name == "buf"
        # Document instances → subcircuits
        assert len(netlist.circuits[0].subcircuits) == 1
        assert netlist.circuits[0].subcircuits[0].circuit_name == "mzi_phase_shifter"

    def test_proto_netlist_to_netlist_document(self):
        doc = _simple_doc()
        circuit = doc.to_proto_netlist()
        recovered = NetlistDocument.from_proto_netlist(circuit)
        assert recovered.toplevel == doc.toplevel
        assert "buf" in recovered.modules
        assert "mzi" in recovered.modules["buf"].instances
        assert (
            recovered.modules["buf"].instances["mzi"].component == "mzi_phase_shifter"
        )

    def test_proto_netlist_settings_round_trip(self):
        doc = NetlistDocument(
            modules={
                "m": CircuitDocument(
                    instances={
                        "inst": SubCircuitDocument(
                            component="comp", settings={"width": 4.5, "n": 2}
                        )
                    }
                )
            },
            toplevel="m",
        )
        circuit = doc.to_proto_netlist()
        recovered = NetlistDocument.from_proto_netlist(circuit)
        inst = recovered.modules["m"].instances["inst"]
        assert inst.settings.get("width") == 4.5
        assert inst.settings.get("n") == 2

    def test_proto_netlist_array_round_trip(self):
        doc = NetlistDocument(
            modules={
                "m": CircuitDocument(
                    instances={
                        "arr": SubCircuitDocument(
                            component="mzi", array=ArraySpec(na=5, nb=2)
                        )
                    }
                )
            },
            toplevel="m",
        )
        circuit = doc.to_proto_netlist()
        recovered = NetlistDocument.from_proto_netlist(circuit)
        arr = recovered.modules["m"].instances["arr"].array
        assert arr is not None
        assert arr.na == 5
        assert arr.nb == 2


# ---------------------------------------------------------------------------
# 9. Backward-compat bare single-module form
# ---------------------------------------------------------------------------


class TestBareModuleBackwardCompat:
    def test_bare_instances_promoted(self):
        raw = {
            "instances": {"mzi": {"component": "mzi_phase_shifter"}},
            "ports": {"o1": "mzi,o1"},
        }
        doc = NetlistDocument.model_validate(raw)
        assert "__root__" in doc.modules
        assert doc.toplevel == "__root__"
        assert "mzi" in doc.modules["__root__"].instances

    def test_bare_form_elaborates(self):
        raw = {
            "instances": {"inst": {"component": "comp"}},
            "ports": {"p": "inst,port"},
        }
        doc = NetlistDocument.model_validate(raw)
        nl = doc.to_netlists()["__root__"]
        assert nl.has_instance("inst")

    def test_explicit_modules_not_promoted(self):
        raw = {
            "modules": {"m": {"instances": {"inst": {"component": "comp"}}}},
            "toplevel": "m",
        }
        doc = NetlistDocument.model_validate(raw)
        assert "__root__" not in doc.modules
        assert "m" in doc.modules


def test_schema_runs_without_python_model_or_codec_packages():
    """A fresh interpreter blocks optional Python model and codec imports."""
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
class BlockPythonCodecs:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"google", "pydantic", "pydantic_yaml", "yaml"}:
            raise AssertionError(f"Schema tried to import {fullname}")
sys.meta_path.insert(0, BlockPythonCodecs())
from kfnetlist.kfnetlist_schema import NetlistDocument, ProtoNetlist
from kfnetlist import _native
assert NetlistDocument is _native.NetlistDocument
doc = NetlistDocument.from_yaml("instances: {a: {component: coupler}}")
wire = doc.to_proto()
assert isinstance(wire, bytes)
assert NetlistDocument.from_proto(wire) == doc
assert ProtoNetlist.from_proto(wire).top_circuit == "__root__"
assert doc.to_netlists()["__root__"].has_instance("a")
""",
        ],
        check=True,
    )


def test_nested_proto_values_and_terminal_alias():
    from kfnetlist.kfnetlist_schema import (
        Connection,
        ModelReference,
        ParameterValue,
        PrefixedValue,
        SIPrefix,
        TerminalReference,
    )

    parameter = ParameterValue(
        model_ref=ModelReference(
            model_interface_name="model",
            arguments={
                "width": ParameterValue(
                    prefixed_value=PrefixedValue(
                        double_value=0.5, prefix=SIPrefix.MICRO
                    )
                )
            },
        )
    )
    back = ParameterValue.from_proto(parameter.to_proto())
    assert back.model_ref is not None
    width = back.model_ref.arguments["width"].prefixed_value
    assert width is not None
    assert width.double_value == 0.5
    assert width.prefix == SIPrefix.MICRO
    assert ParameterValue.from_dict(parameter.to_dict()) == parameter
    with pytest.raises(ValueError, match="only one value"):
        ParameterValue.from_dict({"prefixed_value": {}, "model_ref": {}})
    # The same validation applies to raw nested dictionaries.
    with pytest.raises(ValueError, match="only one value"):
        ModelReference.from_dict(
            {"arguments": {"x": {"prefixed_value": {}, "model_ref": {}}}}
        )
    pin = TerminalReference.from_dict({"instance_name": "a", "Terminal_name": "in"})
    connection = Connection(source=pin, target=TerminalReference(terminal_name="out"))
    recovered = Connection.from_proto(connection.to_proto())
    assert recovered.source is not None
    assert recovered.source.terminal_name == "in"
    assert recovered == connection


def test_proto_bytes_keep_exact_settings_and_metadata():
    original = CircuitDocument(
        name="display name",
        instances={
            "a": SubCircuitDocument(
                component="x",
                settings={
                    "large": 2**53 + 1,
                    "enabled": True,
                    "null": None,
                    "nested": [1, "two"],
                },
                info={"source": "layout"},
            )
        },
        nets=[[], ["a,p"]],
        info={"owner": "test"},
        placements={"a": {"x": 10}},
        routes={"optical": {"radius": 5}},
    )
    doc = NetlistDocument(modules={"m": original}, toplevel="m")
    assert NetlistDocument.from_proto(doc.to_proto()) == doc
    inst = doc.to_netlists()["m"].instances["a"]
    assert inst.info == {"source": "layout"}
    assert type(inst.settings["enabled"]) is bool
    assert inst.settings["large"] == 2**53 + 1


def test_native_fields_return_owned_snapshots():
    doc = _simple_doc()
    modules = doc.modules
    modules.clear()
    assert "buf" in doc.modules
    with pytest.raises(AttributeError):
        doc.toplevel = "other"  # ty: ignore[invalid-assignment]


def test_invalid_wire_and_yaml_raise_value_error():
    with pytest.raises(ValueError):
        ProtoNetlist.from_proto(b"\xff")
    with pytest.raises(ValueError):
        NetlistDocument.from_yaml("modules: [")


def test_optional_pydantic_adapter_delegates_to_native_model():
    pydantic = pytest.importorskip("pydantic")
    adapter = pydantic.TypeAdapter(NetlistDocument)
    doc = _simple_doc()
    assert adapter.validate_python(doc.to_dict()) == doc
    assert adapter.validate_json(adapter.dump_json(doc)) == doc
