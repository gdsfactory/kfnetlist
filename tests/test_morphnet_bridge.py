"""kfnetlist Netlists <-> morphnet Netlists <-> SPICE / Spectre / Verilog-AMS text."""

import json
from pathlib import Path

import pytest

from kfnetlist import Netlist, NetlistPort, PortRef, morphnet
from kfnetlist.kfnetlist_schema import ProtoCircuit
from kfnetlist.morphnet.morphnet_schema import circuit_pb2 as pb
from kfnetlist.morphnet.netlist import (
    parse_spectre,
    parse_spice,
    parse_vams,
    write_spectre,
    write_spice,
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


def connectivity(nl: Netlist):
    nl.sort()
    instances = {k: (v.component, v.settings) for k, v in nl.instances.items()}
    return nl.nets, nl.ports, instances


def test_direct_round_trip_is_exact():
    nl = rc()
    back = morphnet.to_netlists(morphnet.from_netlists({"rc": nl}))["rc"]
    back.sort()
    assert back == nl


@pytest.mark.parametrize(
    ("write", "parse"),
    [
        (write_spice, parse_spice),
        (write_spectre, parse_spectre),
        (write_vams, parse_vams),
    ],
)
def test_every_format_round_trips_connectivity(write, parse):
    nl = rc()
    text = write(morphnet.from_netlists({"rc": nl}, "rc"))
    back = morphnet.to_netlists(parse(text))["rc"]
    assert connectivity(back) == connectivity(nl)


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
    assert ProtoCircuit.from_json(netlist.to_json()) == ProtoCircuit.from_proto(
        netlist.to_proto_bytes()
    )
    _assert_schema_keys(json.loads(netlist.to_json()), pb.Circuit.DESCRIPTOR)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Module", "Circuit"),
        ("ModuleReference", "SubCircuit"),
        ("module", "circuit"),
        ("module_reference", "subcircuit"),
        ("circuit_from_netlists", "from_netlists"),
        ("circuit_to_netlists", "to_netlists"),
    ],
)
def test_pre_rename_names_warn(old, new):
    with pytest.warns(DeprecationWarning, match=f"use {new}"):
        assert getattr(morphnet, old) is getattr(morphnet, new)
