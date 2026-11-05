from kfnetlist._native import load_pic_yaml

from .models import (
    # Enums
    TerminalDirection,
    SignalDomain,
    SIPrefix,
    # Primitive proto-backed models
    PrefixedValue,
    ParameterValue,
    Parameter,
    ModelInterface,
    ModelReference,
    Terminal,
    TerminalReference,
    Connection,
    Bus,
    ExternalCircuit,
    # Proto-backed hierarchy: Netlist → Circuit → SubCircuit
    ProtoNetlist,
    ProtoCircuit,
    ProtoSubCircuit,
    # YAML-level (PIC document) models
    ArraySpec,
    NetlistDocument,
    CircuitDocument,
    SubCircuitDocument,
    # Rust-native type aliases
    Net,
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    PortRef,
    PortArrayRef,
    ModuleNetlist,
    InstanceRef,
)
from .models import __getattr__ as __getattr__  # deprecated pre-rename names

__all__ = [
    # Enums
    "TerminalDirection",
    "SignalDomain",
    "SIPrefix",
    # Primitive proto-backed models
    "PrefixedValue",
    "ParameterValue",
    "Parameter",
    "ModelInterface",
    "ModelReference",
    "Terminal",
    "TerminalReference",
    "Connection",
    "Bus",
    "ExternalCircuit",
    # Proto-backed hierarchy: Netlist → Circuit → SubCircuit
    "ProtoNetlist",
    "ProtoCircuit",
    "ProtoSubCircuit",
    # YAML-level (PIC document) models
    "ArraySpec",
    "NetlistDocument",
    "CircuitDocument",
    "SubCircuitDocument",
    # Rust-native type aliases
    "Net",
    "Netlist",
    "NetlistArray",
    "NetlistInstance",
    "NetlistPort",
    "PortRef",
    "PortArrayRef",
    "ModuleNetlist",
    "InstanceRef",
    # Loader
    "load_pic_yaml",
]
