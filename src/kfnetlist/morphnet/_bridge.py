"""Convert between kfnetlist ``Netlist`` graphs and morphnet ``Netlist`` documents.

``kfnetlist.Netlist`` is the connectivity graph of one cell; ``morphnet.Netlist`` is
a schema document (circuits, external circuits, simulation). Both share
``circuit.proto``, so the bridge is a protobuf byte round trip.
"""

import json
from collections.abc import Iterator, Mapping

from kfnetlist._native import Netlist as KfNetlist
from kfnetlist._native import NetlistDocument
from kfnetlist.morphnet.morphnet_schema import (
    ExternalCircuit,
    Netlist,
    Port,
    PortDirection,
    ProtoModel,
    SignalDomain,
)
from kfnetlist.morphnet.netlist.expression import parse_expression
from kfnetlist.morphnet.netlist.value_utils import (
    DEVICE_PORT_TEMPLATES,
    DEVICE_PREFIX_TO_CIRCUIT,
)

_PREFIX_BY_DEVICE = {
    device: prefix for prefix, device in DEVICE_PREFIX_TO_CIRCUIT.items()
}
# Protobuf maps are unordered (Rust sorts them, upb scrambles them on decode), but
# writers print some in insertion order: the bridge records it under this key.
_ORDER = "__order__"


def _string_maps(model: ProtoModel) -> Iterator[dict[str, str]]:
    """Every ``dict[str, str]`` field (``properties``, ``options``, ...) in ``model``."""
    for name in type(model).model_fields:
        value = getattr(model, name)
        items = value.values() if isinstance(value, dict) else value
        if isinstance(value, dict) and all(isinstance(v, str) for v in items):
            yield value
        elif isinstance(value, ProtoModel):
            yield from _string_maps(value)
        elif isinstance(value, (dict, list)):
            for item in items:
                if isinstance(item, ProtoModel):
                    yield from _string_maps(item)


def _stash(info: Mapping) -> Mapping:
    stash = info.get("__morphnet__", {})
    if not isinstance(stash, dict):
        raise ValueError("info['__morphnet__'] must be an object")
    return stash


def _record_order(netlist: Netlist) -> Netlist:
    netlist = netlist.model_copy(deep=True)
    for props in _string_maps(netlist):
        keys = [k for k in props if not k.startswith("__")]
        if keys != sorted(keys):
            props[_ORDER] = json.dumps(keys)
    return netlist


def _restore_order(netlist: Netlist) -> None:
    for props in _string_maps(netlist):
        order = [k for k in json.loads(props.pop(_ORDER, "[]")) if k in props]
        ordered = {k: props[k] for k in [*order, *sorted(props.keys() - set(order))]}
        props.clear()
        props.update(ordered)


def _trees(info: Mapping) -> set[str]:
    """Names of the stashed params that held an expression tree (not ``raw`` text)."""
    return {
        p.get("name", "")
        for p in _stash(info).get("parameters", [])
        if (expr := (p.get("default_value") or {}).get("expression")) is not None
        and "raw" not in expr
    }


def _parse_raw(netlist: Netlist, netlists: Mapping[str, KfNetlist]) -> None:
    """Parse the ``raw`` text an edited expression setting leaves (unparsable text
    stays). Other string settings were never expressions: they stay verbatim."""
    for circuit in netlist.circuits:
        instances = netlists[circuit.name].instances if circuit.name in netlists else {}
        for sub in circuit.subcircuits:
            if sub.name not in instances:
                continue
            trees = _trees(instances[sub.name].info)
            for param in sub.parameters:
                value = param.default_value
                if param.name in trees and value and value.expression:
                    if value.expression.raw:
                        value.expression = parse_expression(value.expression.raw)


def from_netlists(
    netlists: Mapping[str, KfNetlist], toplevel: str | None = None
) -> Netlist:
    """Build a morphnet ``Netlist`` from ``{cell name: kfnetlist.Netlist}``.

    Instances of built-in devices (``resistor``, ``capacitor``, ``mosfet``, ...) that the
    document does not declare get the same external-circuit declarations the SPICE parser
    creates, so positional writers (SPICE, Spectre) emit pins in device order. Devices a
    document restored from morphnet (see below) used undeclared stay undeclared.

    Morphnet data with no kfnetlist counterpart travels in ``Netlist.info["__morphnet__"]``
    (and the instances' ``info["__morphnet__"]``), so ``from_netlists(to_netlists(nl))``
    writes the same text as ``nl``.
    """
    doc = NetlistDocument.from_netlists(dict(netlists), toplevel)
    netlist = Netlist.from_proto_bytes(doc.to_proto())
    _restore_order(netlist)
    _parse_raw(netlist, netlists)
    # Masters the restored source document used without declaring stay undeclared.
    undeclared = {
        name
        for nl in netlists.values()
        for name in _stash(nl.info).get("undeclared", [])
    }
    defined = {c.name for c in [*netlist.circuits, *netlist.ext_circuits]}
    used = (
        {sub.circuit_name for c in netlist.circuits for sub in c.subcircuits}
        - defined
        - undeclared
    )
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
    data = _record_order(netlist).to_proto_bytes()
    return NetlistDocument.from_proto(data).to_netlists()
