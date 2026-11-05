"""Convert between kfnetlist ``Netlist`` documents and morphnet ``Circuit`` models.

Both sides share ``circuit.proto``, so the bridge is a protobuf byte round trip.
"""

from collections.abc import Mapping

from kfnetlist._native import Netlist, TopLevelModule
from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    ExternalModule,
    Port,
    PortDirection,
    SignalDomain,
)
from kfnetlist.morphnet.netlist.value_utils import (
    DEVICE_PORT_TEMPLATES,
    DEVICE_PREFIX_TO_MODULE,
)

_PREFIX_BY_MODULE = {
    module: prefix for prefix, module in DEVICE_PREFIX_TO_MODULE.items()
}


def circuit_from_netlists(
    netlists: Mapping[str, Netlist], toplevel: str | None = None
) -> Circuit:
    """Build a morphnet ``Circuit`` from ``{cell name: Netlist}``, ready for any writer.

    Instances of built-in devices (``resistor``, ``capacitor``, ``mosfet``, ...) get the
    same external-module declarations the SPICE parser creates, so positional writers
    (SPICE, Spectre) emit pins in device order.
    """
    doc = TopLevelModule.from_netlists(dict(netlists), toplevel)
    circuit = Circuit.from_proto_bytes(doc.to_proto())
    defined = {m.name for m in circuit.modules}
    used = {
        ref.module_name for m in circuit.modules for ref in m.module_references
    } - defined
    for name in sorted(used & _PREFIX_BY_MODULE.keys()):
        prefix = _PREFIX_BY_MODULE[name]
        ports = [
            Port(name=p, direction=PortDirection.INOUT, domain=SignalDomain.ELECTRICAL)
            for p in DEVICE_PORT_TEMPLATES[prefix]
        ]
        circuit.add_ext(
            ExternalModule(name=name, ports=ports, properties={"spice_prefix": prefix})
        )
    return circuit


def circuit_to_netlists(circuit: Circuit) -> dict[str, Netlist]:
    """Convert a parsed or built ``Circuit`` to ``{module name: Netlist}``."""
    return TopLevelModule.from_proto(circuit.to_proto_bytes()).to_netlists()
