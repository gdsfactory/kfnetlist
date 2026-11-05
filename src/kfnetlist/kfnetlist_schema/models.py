"""Rust-backed circuit and PIC document types. Fields return owned snapshots.

Both follow one hierarchy: a netlist (container) holds circuit definitions, and each
circuit holds subcircuit instances.
"""

from kfnetlist._native import (
    TerminalDirection as TerminalDirection,
    SignalDomain as SignalDomain,
    SIPrefix as SIPrefix,
    PrefixedValue as PrefixedValue,
    ParameterValue as ParameterValue,
    Parameter as Parameter,
    ModelInterface as ModelInterface,
    ModelReference as ModelReference,
    Terminal as Terminal,
    TerminalReference as TerminalReference,
    Connection as Connection,
    Bus as Bus,
    ExternalCircuit as ExternalCircuit,
    ProtoSubCircuit as ProtoSubCircuit,
    ProtoCircuit as ProtoCircuit,
    ProtoNetlist as ProtoNetlist,
    ArraySpec as ArraySpec,
    SubCircuitDocument as SubCircuitDocument,
    CircuitDocument as CircuitDocument,
    NetlistDocument as NetlistDocument,
    Net as Net,
    Netlist as Netlist,
    NetlistArray as NetlistArray,
    NetlistInstance as NetlistInstance,
    NetlistPort as NetlistPort,
    PortRef as PortRef,
    PortArrayRef as PortArrayRef,
)

ModuleNetlist = Netlist
InstanceRef = NetlistInstance

# Names before the Netlist → Circuit → SubCircuit rename. `ProtoCircuit` is not
# listed: it now names the circuit definition (the container is `ProtoNetlist`).
_DEPRECATED = {
    "ProtoModule": "ProtoCircuit",
    "ProtoModuleReference": "ProtoSubCircuit",
    "ExternalModule": "ExternalCircuit",
    "TopLevelModule": "NetlistDocument",
    "Module": "CircuitDocument",
    "Instance": "SubCircuitDocument",
}


def __getattr__(name: str) -> object:
    if name in _DEPRECATED:
        import warnings

        new = _DEPRECATED[name]
        warnings.warn(
            f"{name} is deprecated; use {new}", DeprecationWarning, stacklevel=2
        )
        return globals()[new]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
