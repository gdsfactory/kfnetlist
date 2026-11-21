from enum import IntEnum

import pytest

from kfnetlist.morphnet.morphnet_schema import (
    BinaryOp,
    Bus,
    Call,
    Expression,
    Operator,
    Ternary,
    UnaryOp,
    Netlist,
    Connection,
    ExternalCircuit,
    ModelInterface,
    ModelReference,
    Circuit,
    SubCircuit,
    Parameter,
    ParameterValue,
    Port,
    PortDirection,
    PortReference,
    PrefixedValue,
    SignalDomain,
    SIPrefix,
)

# ======================================================================
# Enum tests
# ======================================================================


class TestEnums:
    def test_port_direction_is_intenum(self):
        assert issubclass(PortDirection, IntEnum)

    def test_signal_domain_is_intenum(self):
        assert issubclass(SignalDomain, IntEnum)

    def test_si_prefix_is_intenum(self):
        assert issubclass(SIPrefix, IntEnum)

    def test_port_direction_values(self):
        assert PortDirection.INOUT == 0
        assert PortDirection.INPUT == 1
        assert PortDirection.OUTPUT == 2

    def test_signal_domain_values(self):
        assert SignalDomain.UNSPECIFIED == 0
        assert SignalDomain.ELECTRICAL == 1
        assert SignalDomain.WAVEGUIDE == 2

    def test_si_prefix_values(self):
        assert SIPrefix.UNSPECIFIED == 0
        assert SIPrefix.QUECTO == 1
        assert SIPrefix.NANO == 8
        assert SIPrefix.MICRO == 9
        assert SIPrefix.MILLI == 10
        assert SIPrefix.KILO == 15
        assert SIPrefix.MEGA == 16
        assert SIPrefix.GIGA == 17
        assert SIPrefix.QUETTA == 24
        assert len(SIPrefix) == 25


# ======================================================================
# Default construction tests
# ======================================================================


class TestDefaults:
    @pytest.mark.parametrize(
        "model_cls",
        [
            PrefixedValue,
            ModelReference,
            ParameterValue,
            Parameter,
            ModelInterface,
            PortReference,
            Port,
            Connection,
            Bus,
            SubCircuit,
            Circuit,
            ExternalCircuit,
            Netlist,
        ],
    )
    def test_default_construction(self, model_cls):
        instance = model_cls()
        assert instance is not None


class TestMutable:
    def test_mutability(self, prefixed_value):
        # Models are now mutable (frozen=False) to support in-place accumulation
        prefixed_value.double_value = 99.0
        assert prefixed_value.double_value == 99.0


# ======================================================================
# ParameterValue oneof tests
# ======================================================================


class TestParameterValueOneof:
    def test_allows_empty(self):
        pv = ParameterValue()
        assert pv.prefixed_value is None
        assert pv.model_ref is None

    def test_allows_prefixed_value_only(self, prefixed_value):
        pv = ParameterValue(prefixed_value=prefixed_value)
        assert pv.prefixed_value is not None
        assert pv.model_ref is None

    def test_allows_model_ref_only(self, model_reference):
        pv = ParameterValue(model_ref=model_reference)
        assert pv.prefixed_value is None
        assert pv.model_ref is not None

    def test_rejects_both_set(self, prefixed_value, model_reference):
        with pytest.raises(ValueError, match="oneof"):
            ParameterValue(
                prefixed_value=prefixed_value,
                model_ref=model_reference,
            )


class TestExpression:
    def test_rejects_two_nodes(self):
        with pytest.raises(ValueError, match="oneof"):
            Expression(reference="a", raw="b")

    def test_rejects_expression_beside_a_number(self, prefixed_value):
        with pytest.raises(ValueError, match="oneof"):
            ParameterValue(prefixed_value=prefixed_value, expression=Expression(raw=""))

    def test_tree_roundtrips_proto_binary(self, prefixed_value):
        x = Expression(reference="x")
        tree = Expression(
            ternary=Ternary(
                cond=Expression(binary=BinaryOp(op=Operator.GT, lhs=x, rhs=x)),
                then=Expression(unary=UnaryOp(op=Operator.NEG, operand=x)),
                otherwise=Expression(
                    call=Call(
                        name="max",
                        args=[Expression(literal=prefixed_value), Expression(raw="")],
                    )
                ),
            )
        )
        pv = ParameterValue(expression=tree)
        assert ParameterValue.from_proto_bytes(pv.to_proto_bytes()) == pv


# ======================================================================
# Per-model round-trip tests
# ======================================================================


class TestPrefixedValue:
    def test_roundtrip_proto_binary(self, prefixed_value):
        data = prefixed_value.to_proto_bytes()
        restored = PrefixedValue.from_proto_bytes(data)
        assert restored == prefixed_value

    def test_roundtrip_json(self, prefixed_value):
        json_str = prefixed_value.to_json()
        restored = PrefixedValue.from_json(json_str)
        assert restored == prefixed_value

    def test_roundtrip_yaml(self, prefixed_value):
        yaml_str = prefixed_value.to_yaml()
        restored = PrefixedValue.from_yaml(yaml_str)
        assert restored == prefixed_value


class TestModelReference:
    def test_roundtrip_proto_binary(self, model_reference):
        data = model_reference.to_proto_bytes()
        restored = ModelReference.from_proto_bytes(data)
        assert restored == model_reference

    def test_roundtrip_json(self, model_reference):
        json_str = model_reference.to_json()
        restored = ModelReference.from_json(json_str)
        assert restored == model_reference

    def test_roundtrip_yaml(self, model_reference):
        yaml_str = model_reference.to_yaml()
        restored = ModelReference.from_yaml(yaml_str)
        assert restored == model_reference


class TestParameterValuePrefixed:
    def test_roundtrip_proto_binary(self, parameter_value_with_prefixed):
        data = parameter_value_with_prefixed.to_proto_bytes()
        restored = ParameterValue.from_proto_bytes(data)
        assert restored == parameter_value_with_prefixed

    def test_roundtrip_json(self, parameter_value_with_prefixed):
        json_str = parameter_value_with_prefixed.to_json()
        restored = ParameterValue.from_json(json_str)
        assert restored == parameter_value_with_prefixed

    def test_roundtrip_yaml(self, parameter_value_with_prefixed):
        yaml_str = parameter_value_with_prefixed.to_yaml()
        restored = ParameterValue.from_yaml(yaml_str)
        assert restored == parameter_value_with_prefixed


class TestParameterValueModelRef:
    def test_roundtrip_proto_binary(self, parameter_value_with_model_ref):
        data = parameter_value_with_model_ref.to_proto_bytes()
        restored = ParameterValue.from_proto_bytes(data)
        assert restored == parameter_value_with_model_ref

    def test_roundtrip_json(self, parameter_value_with_model_ref):
        json_str = parameter_value_with_model_ref.to_json()
        restored = ParameterValue.from_json(json_str)
        assert restored == parameter_value_with_model_ref

    def test_roundtrip_yaml(self, parameter_value_with_model_ref):
        yaml_str = parameter_value_with_model_ref.to_yaml()
        restored = ParameterValue.from_yaml(yaml_str)
        assert restored == parameter_value_with_model_ref


class TestParameter:
    def test_roundtrip_proto_binary(self, parameter):
        data = parameter.to_proto_bytes()
        restored = Parameter.from_proto_bytes(data)
        assert restored == parameter

    def test_roundtrip_json(self, parameter):
        json_str = parameter.to_json()
        restored = Parameter.from_json(json_str)
        assert restored == parameter

    def test_roundtrip_yaml(self, parameter):
        yaml_str = parameter.to_yaml()
        restored = Parameter.from_yaml(yaml_str)
        assert restored == parameter


class TestModelInterface:
    def test_roundtrip_proto_binary(self, model_interface):
        data = model_interface.to_proto_bytes()
        restored = ModelInterface.from_proto_bytes(data)
        assert restored == model_interface

    def test_roundtrip_json(self, model_interface):
        json_str = model_interface.to_json()
        restored = ModelInterface.from_json(json_str)
        assert restored == model_interface

    def test_roundtrip_yaml(self, model_interface):
        yaml_str = model_interface.to_yaml()
        restored = ModelInterface.from_yaml(yaml_str)
        assert restored == model_interface


class TestPortReference:
    def test_roundtrip_proto_binary(self, port_reference):
        data = port_reference.to_proto_bytes()
        restored = PortReference.from_proto_bytes(data)
        assert restored == port_reference

    def test_roundtrip_json(self, port_reference):
        json_str = port_reference.to_json()
        restored = PortReference.from_json(json_str)
        assert restored == port_reference

    def test_roundtrip_yaml(self, port_reference):
        yaml_str = port_reference.to_yaml()
        restored = PortReference.from_yaml(yaml_str)
        assert restored == port_reference


class TestPort:
    def test_roundtrip_proto_binary(self, port):
        data = port.to_proto_bytes()
        restored = Port.from_proto_bytes(data)
        assert restored == port

    def test_roundtrip_json(self, port):
        json_str = port.to_json()
        restored = Port.from_json(json_str)
        assert restored == port

    def test_roundtrip_yaml(self, port):
        yaml_str = port.to_yaml()
        restored = Port.from_yaml(yaml_str)
        assert restored == port


class TestConnection:
    def test_roundtrip_proto_binary(self, connection):
        data = connection.to_proto_bytes()
        restored = Connection.from_proto_bytes(data)
        assert restored == connection

    def test_roundtrip_json(self, connection):
        json_str = connection.to_json()
        restored = Connection.from_json(json_str)
        assert restored == connection

    def test_roundtrip_yaml(self, connection):
        yaml_str = connection.to_yaml()
        restored = Connection.from_yaml(yaml_str)
        assert restored == connection


class TestBus:
    def test_roundtrip_proto_binary(self, bus):
        data = bus.to_proto_bytes()
        restored = Bus.from_proto_bytes(data)
        assert restored == bus

    def test_roundtrip_json(self, bus):
        json_str = bus.to_json()
        restored = Bus.from_json(json_str)
        assert restored == bus

    def test_roundtrip_yaml(self, bus):
        yaml_str = bus.to_yaml()
        restored = Bus.from_yaml(yaml_str)
        assert restored == bus


class TestSubCircuit:
    def test_roundtrip_proto_binary(self, subcircuit):
        data = subcircuit.to_proto_bytes()
        restored = SubCircuit.from_proto_bytes(data)
        assert restored == subcircuit

    def test_roundtrip_json(self, subcircuit):
        json_str = subcircuit.to_json()
        restored = SubCircuit.from_json(json_str)
        assert restored == subcircuit

    def test_roundtrip_yaml(self, subcircuit):
        yaml_str = subcircuit.to_yaml()
        restored = SubCircuit.from_yaml(yaml_str)
        assert restored == subcircuit


class TestCircuit:
    def test_roundtrip_proto_binary(self, circuit):
        data = circuit.to_proto_bytes()
        restored = Circuit.from_proto_bytes(data)
        assert restored == circuit

    def test_roundtrip_json(self, circuit):
        json_str = circuit.to_json()
        restored = Circuit.from_json(json_str)
        assert restored == circuit

    def test_roundtrip_yaml(self, circuit):
        yaml_str = circuit.to_yaml()
        restored = Circuit.from_yaml(yaml_str)
        assert restored == circuit


class TestExternalModule:
    def test_roundtrip_proto_binary(self, external_circuit):
        data = external_circuit.to_proto_bytes()
        restored = ExternalCircuit.from_proto_bytes(data)
        assert restored == external_circuit

    def test_roundtrip_json(self, external_circuit):
        json_str = external_circuit.to_json()
        restored = ExternalCircuit.from_json(json_str)
        assert restored == external_circuit

    def test_roundtrip_yaml(self, external_circuit):
        yaml_str = external_circuit.to_yaml()
        restored = ExternalCircuit.from_yaml(yaml_str)
        assert restored == external_circuit


# ======================================================================
# Full circuit integration tests
# ======================================================================


class TestNetlistIntegration:
    def test_roundtrip_proto_binary(self, netlist):
        data = netlist.to_proto_bytes()
        restored = Netlist.from_proto_bytes(data)
        assert restored == netlist

    def test_roundtrip_json(self, netlist):
        json_str = netlist.to_json()
        restored = Netlist.from_json(json_str)
        assert restored == netlist

    def test_roundtrip_yaml(self, netlist):
        yaml_str = netlist.to_yaml()
        restored = Netlist.from_yaml(yaml_str)
        assert restored == netlist

    def test_proto_interop(self, netlist):
        proto_msg = netlist.to_proto()
        assert proto_msg.name == "mzi_circuit"
        # The protobuf message uses the kfnetlist schema names.
        assert proto_msg.top_circuit == "top"
        assert len(proto_msg.circuits) == 1
        assert len(proto_msg.ext_circuits) == 1
        assert proto_msg.circuits[0].name == "top"
        assert proto_msg.circuits[0].terminals[0].name == "o1"

        restored = Netlist.from_proto(proto_msg)
        assert restored == netlist

    def test_cross_format_equivalence(self, netlist):
        from_proto = Netlist.from_proto_bytes(netlist.to_proto_bytes())
        from_json = Netlist.from_json(netlist.to_json())
        from_yaml = Netlist.from_yaml(netlist.to_yaml())
        assert from_proto == from_json == from_yaml == netlist


# ======================================================================
# JSON shared with the Rust schema (kfnetlist_schema.ProtoNetlist)
# ======================================================================

EXPRESSIONS = """* expressions
.param w=1 c=1
.subckt cell a b
.ends
X1 a b cell r={w*2} s={w} t={max(w, 2)} u={c ? 1 : w} v={a^2}
.end
"""


def test_expression_json_round_trips_through_the_rust_schema():
    from pathlib import Path

    from kfnetlist.kfnetlist_schema import ProtoNetlist
    from kfnetlist.morphnet.netlist import parse_gsch, parse_spice

    gsch = Path(__file__).parent / "netlists" / "gsch" / "ihp_cmos_inverter.gsch"
    for nl in (parse_spice(EXPRESSIONS), parse_gsch(gsch.read_text())):
        rust = ProtoNetlist.from_json(nl.to_json())
        assert Netlist.from_json(rust.to_json()) == nl
    x1 = parse_spice(EXPRESSIONS).circuits[0].subcircuits[0]
    kinds = {
        p.name: next(k for k, v in p.default_value.expression.model_dump().items() if v)
        for p in x1.parameters
    }
    assert kinds == {
        "r": "binary",
        "s": "reference",
        "t": "call",
        "u": "ternary",
        "v": "raw",
    }


def test_json_omits_unset_oneofs_and_empty_macros():
    nl = Netlist(
        circuits=[
            Circuit(
                name="top",
                parameters=[
                    Parameter(
                        name="w",
                        default_value=ParameterValue(
                            prefixed_value=PrefixedValue(double_value=1.0)
                        ),
                    )
                ],
            )
        ]
    )
    for text in (nl.to_json(), nl.to_yaml()):
        assert "macros" not in text
        assert "expression" not in text
        assert "null" not in text
    assert Netlist.from_json(nl.to_json()) == nl
    assert Netlist.from_yaml(nl.to_yaml()) == nl


def test_an_expression_with_no_node_is_not_written():
    from kfnetlist.morphnet.netlist import write_spice

    nl = Netlist(top_circuit="top", circuits=[Circuit(name="top")])
    nl.circuits[0].subcircuits.append(
        SubCircuit(
            name="X1",
            circuit_name="cell",
            parameters=[
                Parameter(
                    name="w", default_value=ParameterValue(expression=Expression())
                )
            ],
        )
    )
    assert "w=" not in write_spice(nl)


def test_stimulus_json_round_trips_through_the_rust_schema():
    from kfnetlist.kfnetlist_schema import ProtoNetlist
    from kfnetlist.morphnet.morphnet_schema import (
        Simulation,
        Stimulus,
        Waveform,
        WaveformKind,
    )

    def num(x: float) -> ParameterValue:
        return ParameterValue(prefixed_value=PrefixedValue(double_value=x))

    stim = Stimulus(
        name="__top__/V1",
        dc=num(0.9),
        ac_magnitude=num(1.0),
        waveform=Waveform(
            kind=WaveformKind.PULSE,
            args={
                "val0": num(0.0),
                "val1": ParameterValue(expression=Expression(reference="vdd")),
            },
        ),
    )
    pwl = Stimulus(
        name="__top__/I1",
        waveform=Waveform(
            kind=WaveformKind.PWL, points=[num(0), num(0), num(1e-9), num(1)]
        ),
    )
    nl = Netlist(
        top_circuit="__top__",
        circuits=[Circuit(name="__top__")],
        simulation=Simulation(stimuli=[stim, pwl]),
    )
    assert Netlist.from_json(nl.to_json()) == nl
    rust = ProtoNetlist.from_json(nl.to_json())
    assert Netlist.from_json(rust.to_json()) == nl
