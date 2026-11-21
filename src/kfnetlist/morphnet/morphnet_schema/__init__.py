from kfnetlist.morphnet.morphnet_schema._base import ProtoModel
from kfnetlist.morphnet.morphnet_schema._circuit import (
    BinaryOp,
    Bus,
    Call,
    Circuit,
    Connection,
    Directive,
    DirectiveKind,
    ExternalLibrary,
    ExternalCircuit,
    ExternalCircuitKind,
    Expression,
    Macro,
    ModelInterface,
    ModelReference,
    Netlist,
    Operator,
    Parameter,
    ParameterValue,
    Port,
    PortDirection,
    PortReference,
    PrefixedValue,
    SignalDomain,
    SIPrefix,
    SubCircuit,
    Ternary,
    UnaryOp,
)
from kfnetlist.morphnet.morphnet_schema._simulation import (
    Analysis,
    AnalysisKind,
    InitialCondition,
    Measurement,
    OutputRequest,
    OutputRequestKind,
    Simulation,
    Stimulus,
    Waveform,
    WaveformKind,
)

__all__ = [
    "Analysis",
    "AnalysisKind",
    "BinaryOp",
    "Bus",
    "Call",
    "Circuit",
    "Connection",
    "Directive",
    "DirectiveKind",
    "ExternalLibrary",
    "ExternalCircuit",
    "ExternalCircuitKind",
    "Expression",
    "InitialCondition",
    "Macro",
    "Measurement",
    "ModelInterface",
    "ModelReference",
    "Netlist",
    "Operator",
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
    "Stimulus",
    "SubCircuit",
    "Ternary",
    "UnaryOp",
    "Waveform",
    "WaveformKind",
]

# Names before the Netlist → Circuit → SubCircuit rename.
_DEPRECATED = {
    "Module": "Circuit",
    "ModuleReference": "SubCircuit",
    "ExternalModule": "ExternalCircuit",
    "ExternalModuleKind": "ExternalCircuitKind",
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
