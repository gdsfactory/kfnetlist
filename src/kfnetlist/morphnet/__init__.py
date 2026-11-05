from kfnetlist.morphnet._bridge import from_netlists, to_netlists
from kfnetlist.morphnet._api import (
    circuit,
    connection,
    ext_module,
    external_library,
    model_interface,
    parameter,
    port,
    subcircuit,
)
from kfnetlist.morphnet.morphnet_schema import (
    Analysis,
    AnalysisKind,
    Bus,
    Circuit,
    Connection,
    Directive,
    DirectiveKind,
    ExternalLibrary,
    ExternalModule,
    ExternalModuleKind,
    InitialCondition,
    Measurement,
    ModelInterface,
    ModelReference,
    Netlist,
    OutputRequest,
    OutputRequestKind,
    Parameter,
    ParameterValue,
    Port,
    PortDirection,
    PortReference,
    PrefixedValue,
    ProtoModel,
    SIPrefix,
    SignalDomain,
    Simulation,
    SubCircuit,
)

__all__ = [
    "from_netlists",
    "to_netlists",
    # Factory functions
    "circuit",
    "connection",
    "ext_module",
    "external_library",
    "model_interface",
    "parameter",
    "port",
    "subcircuit",
    # Schema types
    "Analysis",
    "AnalysisKind",
    "Bus",
    "Circuit",
    "Connection",
    "Directive",
    "DirectiveKind",
    "ExternalLibrary",
    "ExternalModule",
    "ExternalModuleKind",
    "InitialCondition",
    "Measurement",
    "ModelInterface",
    "ModelReference",
    "Netlist",
    "OutputRequest",
    "OutputRequestKind",
    "Parameter",
    "ParameterValue",
    "Port",
    "PortDirection",
    "PortReference",
    "PrefixedValue",
    "ProtoModel",
    "SIPrefix",
    "SignalDomain",
    "Simulation",
    "SubCircuit",
]

# Names before the Netlist → Circuit → SubCircuit rename.
_DEPRECATED = {
    "Module": "Circuit",
    "ModuleReference": "SubCircuit",
    "module": "circuit",
    "module_reference": "subcircuit",
    "circuit_from_netlists": "from_netlists",
    "circuit_to_netlists": "to_netlists",
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
