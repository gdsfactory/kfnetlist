"""Convert between kfnetlist ``Netlist`` graphs and morphnet ``Netlist`` documents.

``kfnetlist.Netlist`` is the connectivity graph of one cell; ``morphnet.Netlist`` is
a schema document (circuits, external circuits, simulation). Both share
``circuit.proto``, so the bridge is a protobuf byte round trip.
"""

from collections.abc import Mapping

from kfnetlist._native import Netlist as KfNetlist
from kfnetlist._native import NetlistDocument
from kfnetlist.morphnet.morphnet_schema import (
    ExternalCircuit,
    Netlist,
    Port,
    PortDirection,
    SignalDomain,
)
from kfnetlist.morphnet.netlist.value_utils import (
    DEVICE_PORT_TEMPLATES,
    DEVICE_PREFIX_TO_CIRCUIT,
)

_PREFIX_BY_DEVICE = {
    device: prefix for prefix, device in DEVICE_PREFIX_TO_CIRCUIT.items()
}


def from_netlists(
    netlists: Mapping[str, KfNetlist], toplevel: str | None = None
) -> Netlist:
    """Build a morphnet ``Netlist`` from ``{cell name: kfnetlist.Netlist}``.

    Instances of built-in devices (``resistor``, ``capacitor``, ``mosfet``, ...) get the
    same external-circuit declarations the SPICE parser creates, so positional writers
    (SPICE, Spectre) emit pins in device order.
    """
    doc = NetlistDocument.from_netlists(dict(netlists), toplevel)
    netlist = Netlist.from_proto_bytes(doc.to_proto())
    defined = {c.name for c in netlist.circuits}
    used = {
        sub.circuit_name for c in netlist.circuits for sub in c.subcircuits
    } - defined
    for name in sorted(used & _PREFIX_BY_DEVICE.keys()):
        prefix = _PREFIX_BY_DEVICE[name]
        ports = [
            Port(name=p, direction=PortDirection.INOUT, domain=SignalDomain.ELECTRICAL)
            for p in DEVICE_PORT_TEMPLATES[prefix]
        ]
        netlist.add_ext(
            ExternalCircuit(name=name, ports=ports, properties={"spice_prefix": prefix})
        )
    return netlist


def to_netlists(netlist: Netlist) -> dict[str, KfNetlist]:
    """Convert a parsed or built morphnet ``Netlist`` to ``{circuit name: kfnetlist.Netlist}``."""
    return NetlistDocument.from_proto(netlist.to_proto_bytes()).to_netlists()
