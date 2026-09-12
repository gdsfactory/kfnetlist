from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from ._base import ProtoModel
from . import circuit_pb2

# ---------------------------------------------------------------------------
# Re-export Rust-native types as schema-level aliases (backward compat)
# ---------------------------------------------------------------------------
from kfnetlist._native import (  # noqa: F401
    Net,
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    PortArrayRef,
    PortRef,
)

ModuleNetlist = Netlist
InstanceRef = NetlistInstance


# ---------------------------------------------------------------------------
# Enums (mirrors of proto enums)
# ---------------------------------------------------------------------------


class TerminalDirection(IntEnum):
    INOUT = 0
    INPUT = 1
    OUTPUT = 2


class SignalDomain(IntEnum):
    UNSPECIFIED = 0
    ELECTRICAL = 1
    WAVEGUIDE = 2


class SIPrefix(IntEnum):
    UNSPECIFIED = 0
    QUECTO = 1
    RONTO = 2
    YOCTO = 3
    ZEPTO = 4
    ATTO = 5
    FEMTO = 6
    PICO = 7
    NANO = 8
    MICRO = 9
    MILLI = 10
    CENTI = 11
    DECI = 12
    DECA = 13
    HECTO = 14
    KILO = 15
    MEGA = 16
    GIGA = 17
    TERA = 18
    PETA = 19
    EXA = 20
    ZETTA = 21
    YOTTA = 22
    RONNA = 23
    QUETTA = 24


# ---------------------------------------------------------------------------
# Primitive proto-backed models
# ---------------------------------------------------------------------------


class PrefixedValue(ProtoModel):
    _proto_type = circuit_pb2.PrefixedValue

    double_value: float = 0.0
    prefix: SIPrefix = SIPrefix.UNSPECIFIED


class ParameterValue(ProtoModel):
    _proto_type = circuit_pb2.ParameterValue

    prefixed_value: PrefixedValue | None = None
    model_ref: ModelReference | None = None


class Parameter(ProtoModel):
    _proto_type = circuit_pb2.Parameter

    uid: int = 0
    name: str = ""
    default_value: ParameterValue | None = None
    description: str = ""
    properties: dict[str, str] = {}


class ModelInterface(ProtoModel):
    _proto_type = circuit_pb2.ModelInterface

    name: str = ""
    function_name: str = ""
    parameters: list[Parameter] = []
    properties: dict[str, str] = {}


class ModelReference(ProtoModel):
    _proto_type = circuit_pb2.ModelReference

    model_interface_name: str = ""
    arguments: dict[str, ParameterValue] = {}


# Resolve forward reference
# ParameterValue.model_rebuild()  # WHY??


class Terminal(ProtoModel):
    _proto_type = circuit_pb2.Terminal

    uid: int = 0
    name: str = ""
    direction: TerminalDirection = TerminalDirection.INOUT
    domain: SignalDomain = SignalDomain.UNSPECIFIED
    width: int = 0
    cross_section: str = ""
    properties: dict[str, str] = {}


class TerminalReference(ProtoModel):
    _proto_type = circuit_pb2.TerminalReference

    instance_name: str = ""
    terminal_name: str = ""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_capital_t(cls, data: Any) -> Any:
        # Proto field is named "Terminal_name" (capital T); accept both spellings
        if (
            isinstance(data, dict)
            and "Terminal_name" in data
            and "terminal_name" not in data
        ):
            data = dict(data)
            data["terminal_name"] = data.pop("Terminal_name")
        return data


class Connection(ProtoModel):
    _proto_type = circuit_pb2.Connection

    name: str = ""
    source: TerminalReference | None = None
    target: TerminalReference | None = None
    domain: SignalDomain = SignalDomain.UNSPECIFIED
    weight: int = 0
    properties: dict[str, str] = {}


class Bus(ProtoModel):
    _proto_type = circuit_pb2.Bus

    name: str = ""
    width: int = 0
    domain: SignalDomain = SignalDomain.UNSPECIFIED
    connections: list[Connection] = []
    properties: dict[str, str] = {}


class ExternalModule(ProtoModel):
    _proto_type = circuit_pb2.ExternalModule

    name: str = ""
    domain: str = ""
    terminals: list[Terminal] = []
    parameters: list[Parameter] = []
    properties: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Proto-backed Module / ModuleReference / Circuit
# (direct proto wrappers; non-proto YAML fields live in properties)
# ---------------------------------------------------------------------------

_PROP_PLACEMENTS = "__placements__"
_PROP_ROUTES = "__routes__"
_PROP_INFO = "__info__"
_PROP_ARRAY = "__array__"


class ProtoModuleReference(ProtoModel):
    """
    Wraps circuit_pb2.ModuleReference.
    Non-proto YAML fields are packed into properties:
      properties["__array__"]  = json(ArraySpec dict)
      properties["__info__"]   = json(info dict)
    """

    _proto_type = circuit_pb2.ModuleReference

    name: str = ""
    module_name: str = ""
    class_name: str = ""
    parameter_values: list[ParameterValue] = []
    parameter_overrides: dict[str, ParameterValue] = {}
    properties: dict[str, str] = {}


class ProtoModule(ProtoModel):
    """
    Wraps circuit_pb2.Module.
    Non-proto YAML fields are packed into properties:
      properties["__placements__"] = json(placements dict)
      properties["__routes__"]     = json(routes dict)
      properties["__info__"]       = json(info dict)
    settings → parameters list.
    instances → module_references list.
    ports/connections/nets → terminal + connections + buses fields.
    """

    _proto_type = circuit_pb2.Module

    uid: int = 0
    name: str = ""
    class_name: str = ""
    terminal: list[Terminal] = []
    parameters: list[Parameter] = []
    model_interfaces: list[ModelInterface] = []
    module_references: list[ProtoModuleReference] = []
    connections: list[Connection] = []
    buses: list[Bus] = []
    properties: dict[str, str] = {}


class ProtoCircuit(ProtoModel):
    """
    Wraps circuit_pb2.Circuit.
    top_module = TopLevelModule.toplevel.
    """

    _proto_type = circuit_pb2.Circuit

    name: str = ""
    domain: str = ""
    top_module: str = ""
    modules: list[ProtoModule] = []
    ext_modules: list[ExternalModule] = []
    properties: dict[str, str] = {}


# ---------------------------------------------------------------------------
# YAML-level models (ergonomic, parsed directly from PIC YAML)
# Non-proto fields (placements, routes, info) are first-class here for
# readability; they get packed into proto properties on conversion.
# ---------------------------------------------------------------------------


class ArraySpec(BaseModel):
    """Array declaration on an instance (na × nb grid)."""

    na: int = 1
    nb: int = 1


class Instance(BaseModel):
    """
    A component instantiation within a Module.
    `component` may reference an external PDK component or another Module
    defined in the same TopLevelModule document.

    On proto conversion:
      component  → ModuleReference.module_name
      settings   → ModuleReference.parameter_overrides
      array      → ModuleReference.properties["__array__"]
      info       → ModuleReference.properties["__info__"]
    """

    component: str
    settings: dict[str, Any] = {}
    array: ArraySpec | None = None
    info: dict[str, Any] = {}


class Module(BaseModel):
    """
    A single named module/subcircuit within a TopLevelModule document.
    Corresponds to circuit_pb2.Module and a Netlist on the Rust side.

    On proto conversion:
      settings     → parameters list (one Parameter per key/value)
      instances    → module_references list
      ports        → terminal list + connections
      connections  → connections list
      nets         → buses list
      placements   → properties["__placements__"]
      routes       → properties["__routes__"]
      info         → properties["__info__"]
    """

    name: str | None = None
    settings: dict[str, Any] = {}
    info: dict[str, Any] = {}
    instances: dict[str, Instance] = {}
    placements: dict[str, Any] = {}
    ports: dict[str, str] = {}
    connections: dict[str, str] = {}
    nets: list[list[str]] = []
    routes: dict[str, Any] = {}


_MODULE_KEYS = frozenset(Module.model_fields)


class TopLevelModule(BaseModel):
    """
    Top-level document for the hierarchical PIC YAML format.
    Maps to circuit_pb2.Circuit (top_module = toplevel).

    Supports two forms:

    Multi-module (canonical):
        modules:
          my_comp: ...
          my_other: ...
        toplevel: my_other

    Bare single-module (backward-compat):
        instances: ...
        ports: ...
        ...
      → promoted to modules["__root__"] with toplevel="__root__"
    """

    modules: dict[str, Module] = {}
    toplevel: str | None = None

    # Bare single-module fields (all optional; used only when `modules` absent)
    name: str | None = None
    settings: dict[str, Any] = {}
    info: dict[str, Any] = {}
    instances: dict[str, Instance] = {}
    placements: dict[str, Any] = {}
    ports: dict[str, str] = {}
    connections: dict[str, str] = {}
    nets: list[list[str]] = []
    routes: dict[str, Any] = {}

    @model_validator(mode="before")
    @classmethod
    def _promote_bare_module(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("modules"):
            return data
        # Bare single-module: any Module-level key present at top level
        bare_keys = _MODULE_KEYS - {"name"}
        if not any(k in data for k in bare_keys):
            return data
        bare: dict[str, Any] = {}
        top: dict[str, Any] = {}
        for k, v in data.items():
            if k in _MODULE_KEYS:
                bare[k] = v
            else:
                top[k] = v
        top["modules"] = {"__root__": bare}
        top.setdefault("toplevel", "__root__")
        return top

    # ------------------------------------------------------------------
    # Convenience: convert to/from ProtoCircuit
    # ------------------------------------------------------------------

    def to_proto_circuit(self) -> ProtoCircuit:
        from ._convert import top_level_module_to_proto_circuit

        return top_level_module_to_proto_circuit(self)

    @classmethod
    def from_proto_circuit(cls, circuit: ProtoCircuit) -> TopLevelModule:
        from ._convert import proto_circuit_to_top_level_module

        return proto_circuit_to_top_level_module(circuit)

    # ------------------------------------------------------------------
    # Convenience: elaborate to Netlist objects
    # ------------------------------------------------------------------

    def to_netlists(self) -> dict[str, Netlist]:
        from ._convert import top_level_module_to_netlists

        return top_level_module_to_netlists(self)

    @classmethod
    def from_netlists(
        cls,
        netlists: dict[str, Netlist],
        toplevel: str | None = None,
    ) -> TopLevelModule:
        from ._convert import netlists_to_top_level_module

        return netlists_to_top_level_module(netlists, toplevel=toplevel)
