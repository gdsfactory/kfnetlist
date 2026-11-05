from kfnetlist.morphnet.morphnet_schema._base import ProtoModel
from kfnetlist.morphnet.morphnet_schema._circuit import (
    Bus,
    Circuit,
    Connection,
    Directive,
    DirectiveKind,
    ExternalLibrary,
    ExternalModule,
    ExternalModuleKind,
    ModelInterface,
    ModelReference,
    Netlist,
    Parameter,
    ParameterValue,
    Port,
    PortDirection,
    PortReference,
    PrefixedValue,
    SignalDomain,
    SIPrefix,
    SubCircuit,
)
from kfnetlist.morphnet.morphnet_schema._simulation import (
    Analysis,
    AnalysisKind,
    InitialCondition,
    Measurement,
    OutputRequest,
    OutputRequestKind,
    Simulation,
)

__all__ = [
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
_DEPRECATED = {"Module": "Circuit", "ModuleReference": "SubCircuit"}


def __getattr__(name: str) -> object:
    if name in _DEPRECATED:
        import warnings

        new = _DEPRECATED[name]
        warnings.warn(
            f"{name} is deprecated; use {new}", DeprecationWarning, stacklevel=2
        )
        return globals()[new]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
