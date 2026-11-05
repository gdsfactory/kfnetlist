"""kfnetlist Netlists <-> morphnet Circuits <-> SPICE / Spectre / Verilog-AMS text."""

import pytest

from kfnetlist import Netlist, NetlistPort, PortRef, morphnet
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
    back = morphnet.circuit_to_netlists(morphnet.circuit_from_netlists({"rc": nl}))[
        "rc"
    ]
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
    text = write(morphnet.circuit_from_netlists({"rc": nl}, "rc"))
    back = morphnet.circuit_to_netlists(parse(text))["rc"]
    assert connectivity(back) == connectivity(nl)


def test_positional_writers_use_device_pin_order():
    text = write_spectre(morphnet.circuit_from_netlists({"rc": rc()}, "rc"))
    assert "C1 (vout gnd) capacitor" in text


def test_parsed_spice_becomes_a_netlist_with_si_values():
    circuit = parse_spice(
        ".subckt rc in_ out gnd\nR1 in_ out 1k\nC1 out gnd 100p\n.ends rc\n"
    )
    nl = morphnet.circuit_to_netlists(circuit)["rc"]
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
