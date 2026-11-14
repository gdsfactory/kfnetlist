from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from lark import Token, Transformer

from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    ExternalCircuit,
    ExternalCircuitKind,
    Circuit,
    SubCircuit,
    Parameter,
    ParameterValue,
    Port,
    PortDirection,
    SignalDomain,
)
from kfnetlist.morphnet.netlist.hdl import (
    Concat,
    Dim,
    Literal,
    NetRef,
    Range,
    bits,
    connect,
    decl_range,
    instance_names,
    range_width,
    to_int,
)
from kfnetlist.morphnet.netlist.net_utils import (
    NetMap,
    PinDomains,
    add_port_to_net,
    domain_of,
    propagate_domains,
    typed_connections,
)
from kfnetlist.morphnet.netlist.value_utils import parse_parameter_number


class InstanceData:
    __slots__ = (
        "dims",
        "module_type",
        "name",
        "named_params",
        "named_ports",
        "positional_params",
        "positional_ports",
    )

    def __init__(
        self,
        module_type: str,
        name: str,
        named_ports: dict[str, Any],
        positional_ports: list[Any],
        named_params: dict[str, ParameterValue],
        positional_params: list[ParameterValue],
        dims: list[Dim] | None = None,
    ) -> None:
        self.dims = dims or []
        self.module_type = module_type
        self.name = name
        self.named_ports = named_ports
        self.positional_ports = positional_ports
        self.named_params = named_params
        self.positional_params = positional_params


class NatureData:
    __slots__ = ("attrs", "name")

    def __init__(self, name: str, attrs: dict[str, ParameterValue]) -> None:
        self.name = name
        self.attrs = attrs


class DisciplineData:
    __slots__ = ("domain", "name", "natures")

    def __init__(self, name: str, natures: dict[str, str], domain: str) -> None:
        self.name = name
        self.natures = natures
        self.domain = domain


class ParamsetData:
    __slots__ = ("base_type", "name", "params")

    def __init__(
        self, name: str, base_type: str, params: dict[str, ParameterValue]
    ) -> None:
        self.name = name
        self.base_type = base_type
        self.params = params


class PortDirData:
    __slots__ = ("direction", "names", "ranges")

    def __init__(
        self,
        direction: PortDirection,
        names: list[str],
        ranges: dict[str, Range] | None = None,
    ) -> None:
        self.direction = direction
        self.names = names
        self.ranges = ranges or {}


class DisciplineDeclData:
    __slots__ = ("discipline", "names", "ranges")

    def __init__(
        self, discipline: str, names: list[str], ranges: dict[str, Range] | None = None
    ) -> None:
        self.discipline = discipline
        self.names = names
        self.ranges = ranges or {}


@dataclass
class ParamOverride:
    named: dict[str, ParameterValue] = field(default_factory=dict)
    positional: list[ParameterValue] = field(default_factory=list)


@dataclass
class PortConn:
    named: dict[str, Any] = field(default_factory=dict)
    positional: list[Any] = field(default_factory=list)


@dataclass
class VamsModule:
    """A module before connectivity: instances need the other modules' ports."""

    name: str
    ports: list[Port]
    parameters: list[Parameter]
    instances: list[InstanceData]
    properties: dict[str, str]
    buses: dict[str, Range]
    types: dict[str, str]

    def port_ranges(self) -> dict[str, Range | None]:
        return {p.name: self.buses.get(p.name) for p in self.ports}


def _decl_ranges(
    packed: Dim | None, names: list[tuple[str, list[Dim]]]
) -> dict[str, Range]:
    ranges = {}
    for name, dims in names:
        rng = decl_range(name, ([packed] if packed else []) + dims)
        if rng is not None:
            ranges[name] = rng
    return ranges


class GroundData:
    __slots__ = ("net",)

    def __init__(self, net: str) -> None:
        self.net = net


class AnalogData:
    __slots__ = ("index",)

    def __init__(self, index: int) -> None:
        self.index = index


DIR_MAP = {
    "input": PortDirection.INPUT,
    "output": PortDirection.OUTPUT,
    "inout": PortDirection.INOUT,
}


class VamsTransformer(Transformer[Token, Netlist]):
    """Transform a Verilog-AMS parse tree into a Netlist model."""

    def __init__(
        self,
        analog_blocks: list[str] | None = None,
        disciplines: Mapping[str, SignalDomain] | None = None,
        pin_domains: PinDomains | None = None,
    ) -> None:
        super().__init__()
        self.analog_blocks = analog_blocks or []
        self.disciplines = disciplines or {}
        self.pin_domains = pin_domains or {}

    # ── Leaf transformers ───────────────────────────────────────────────

    def pvalue_number(self, items: list[Token]) -> ParameterValue:
        return parse_parameter_number(str(items[0]))

    def pvalue_ident(self, items: list[Token]) -> ParameterValue:
        return ParameterValue()

    def pvalue_string(self, items: list[Token]) -> ParameterValue:
        return ParameterValue()

    def param_assign(self, items: list[Any]) -> tuple[str, ParameterValue]:
        name = str(items[0])
        value = items[1]
        if not isinstance(value, ParameterValue):
            value = ParameterValue()
        return (name, value)

    def param_assign_list(self, items: list[Any]) -> list[tuple[str, ParameterValue]]:
        return [item for item in items if isinstance(item, tuple)]

    def param_type(self, items: list[Token]) -> str:
        return str(items[0])

    # ── Port list ──────────────────────────────────────────────────────

    def port_list(self, items: list[Any]) -> list[str]:
        return [str(item) for item in items if isinstance(item, Token)]

    def port_item(self, items: list[Token]) -> Token:
        return items[0]

    def decl_name(self, items: list[Any]) -> tuple[str, list[Dim]]:
        return str(items[0]).removeprefix("\\"), items[1]

    def port_name_list(
        self, items: list[tuple[str, list[Dim]]]
    ) -> list[tuple[str, list[Dim]]]:
        return items

    def range(self, items: list[Token]) -> Dim:
        return Dim(str(t).strip() for t in items)

    def dims(self, items: list[Dim]) -> list[Dim]:
        return items

    # ── Connection expressions ─────────────────────────────────────────

    def net_ref(self, items: list[Any]) -> NetRef:
        return NetRef.make(
            str(items[0]).removeprefix("\\"), items[1] if len(items) > 1 else ()
        )

    def literal(self, items: list[Token]) -> Literal:
        return Literal(items[0])

    def concat(self, items: list[Any]) -> Concat:
        return Concat.make(items)

    def replicate(self, items: list[Any]) -> Concat:
        n = to_int(items[0])
        if n is None or n < 1:
            raise ValueError(
                f"replication count {items[0]!r} must be a positive integer"
            )
        return Concat.make(items[1:] * n)

    # ── Port direction declarations ────────────────────────────────────

    def port_dir_decl(self, items: list[Any]) -> PortDirData:
        direction = DIR_MAP.get(str(items[0]), PortDirection.INOUT)
        packed = items[1] if isinstance(items[1], Dim) else None
        names = items[-1]
        return PortDirData(
            direction=direction,
            names=[n for n, _ in names],
            ranges=_decl_ranges(packed, names),
        )

    # ── Discipline declaration ─────────────────────────────────────────

    def discipline_decl(self, items: list[Any]) -> DisciplineDeclData:
        discipline = str(items[0])
        packed = items[1] if isinstance(items[1], Dim) else None
        names = items[-1]
        return DisciplineDeclData(
            discipline=discipline,
            names=[n for n, _ in names],
            ranges=_decl_ranges(packed, names),
        )

    # ── Parameter / localparam ─────────────────────────────────────────

    def _coerce_value(self, ptype: str, pval: ParameterValue) -> ParameterValue:
        return pval

    def typed_parameter_decl(
        self, items: list[Any]
    ) -> list[tuple[str, ParameterValue, str]]:
        ptype = str(items[0])
        assigns: list[tuple[str, ParameterValue]] = []
        for item in items:
            if isinstance(item, list):
                assigns = item
                break
        return [(n, self._coerce_value(ptype, v), ptype) for n, v in assigns]

    def untyped_parameter_decl(
        self, items: list[Any]
    ) -> list[tuple[str, ParameterValue, str]]:
        assigns: list[tuple[str, ParameterValue]] = []
        for item in items:
            if isinstance(item, list):
                assigns = item
                break
        return [(n, v, "") for n, v in assigns]

    def typed_localparam_decl(
        self, items: list[Any]
    ) -> list[tuple[str, ParameterValue, str]]:
        ptype = str(items[0])
        assigns: list[tuple[str, ParameterValue]] = []
        for item in items:
            if isinstance(item, list):
                assigns = item
                break
        return [
            (n, self._coerce_value(ptype, v), f"localparam:{ptype}") for n, v in assigns
        ]

    def untyped_localparam_decl(
        self, items: list[Any]
    ) -> list[tuple[str, ParameterValue, str]]:
        assigns: list[tuple[str, ParameterValue]] = []
        for item in items:
            if isinstance(item, list):
                assigns = item
                break
        return [(n, v, "localparam") for n, v in assigns]

    # ── Ground statement ───────────────────────────────────────────────

    def ground_stmt(self, items: list[Token]) -> GroundData:
        return GroundData(net=str(items[0]))

    # ── Instance statement ─────────────────────────────────────────────

    def named_override(self, items: list[Any]) -> tuple[str, ParameterValue]:
        name = str(items[0])
        value = items[1]
        if not isinstance(value, ParameterValue):
            value = ParameterValue()
        return (name, value)

    def positional_override(self, items: list[Any]) -> ParameterValue:
        v = items[0]
        if not isinstance(v, ParameterValue):
            v = ParameterValue()
        return v

    def param_override(self, items: list[Any]) -> ParamOverride:
        override = ParamOverride()
        for item in items:
            if isinstance(item, tuple):
                override.named[item[0]] = item[1]
            elif isinstance(item, ParameterValue):
                override.positional.append(item)
        return override

    def named_conn(self, items: list[Any]) -> tuple[str, Any]:
        return (str(items[0]), items[1] if len(items) > 1 else None)

    def positional_conn(self, items: list[Any]) -> Any:
        return items[0]

    def port_conn(self, items: list[Any]) -> PortConn:
        conn = PortConn()
        for item in items:
            if isinstance(item, tuple) and not isinstance(item, Dim):
                conn.named[item[0]] = item[1]
            else:
                conn.positional.append(item)
        return conn

    def instance_stmt(self, items: list[Any]) -> InstanceData:
        rest = items[1:]
        params = rest.pop(0) if isinstance(rest[0], ParamOverride) else ParamOverride()
        name, dims, ports = rest
        return InstanceData(
            module_type=str(items[0]),
            name=str(name).removeprefix("\\"),
            named_ports=ports.named,
            positional_ports=ports.positional,
            named_params=params.named,
            positional_params=params.positional,
            dims=dims,
        )

    # ── Analog placeholder ─────────────────────────────────────────────

    def analog_placeholder(self, items: list[Token]) -> AnalogData:
        return AnalogData(index=int(float(str(items[0]))))

    # ── Nature definition ──────────────────────────────────────────────

    def nature_body(self, items: list[Any]) -> dict[str, ParameterValue]:
        attrs: dict[str, ParameterValue] = {}
        for item in items:
            if isinstance(item, tuple):
                attrs[item[0]] = item[1]
        return attrs

    def nature_attr(self, items: list[Any]) -> tuple[str, ParameterValue]:
        name = str(items[0])
        value = items[1]
        if not isinstance(value, ParameterValue):
            value = ParameterValue()
        return (name, value)

    def nature_def(self, items: list[Any]) -> NatureData:
        name = str(items[0])
        attrs = items[1] if isinstance(items[1], dict) else {}
        return NatureData(name=name, attrs=attrs)

    # ── Discipline definition ──────────────────────────────────────────

    def discipline_body(self, items: list[Any]) -> tuple[dict[str, str], str]:
        natures: dict[str, str] = {}
        domain = ""
        for item in items:
            if isinstance(item, tuple) and len(item) == 2:
                natures[item[0]] = item[1]
            elif isinstance(item, str):
                domain = item
        return natures, domain

    def discipline_nature_attr(self, items: list[Token]) -> tuple[str, str]:
        return (str(items[0]), str(items[1]))

    def discipline_domain_attr(self, items: list[Token]) -> str:
        return str(items[0])

    def discipline_def(self, items: list[Any]) -> DisciplineData:
        name = str(items[0])
        body = items[1] if isinstance(items[1], tuple) else ({}, "")
        natures, domain = body
        return DisciplineData(name=name, natures=natures, domain=domain)

    # ── Paramset definition ────────────────────────────────────────────

    def paramset_body(self, items: list[Any]) -> dict[str, ParameterValue]:
        params: dict[str, ParameterValue] = {}
        for item in items:
            if isinstance(item, tuple) and len(item) == 2:
                params[item[0]] = item[1]
        return params

    def paramset_param(self, items: list[Any]) -> tuple[str, ParameterValue] | None:
        for item in items:
            if isinstance(item, tuple) and len(item) == 2:
                name, val = item
                if isinstance(val, ParameterValue):
                    return (name, val)
        return None

    def paramset_constraint(self, items: list[Any]) -> None:
        return None

    def paramset_def(self, items: list[Any]) -> ParamsetData:
        name = str(items[0])
        base_type = str(items[1])
        params = items[2] if isinstance(items[2], dict) else {}
        return ParamsetData(name=name, base_type=base_type, params=params)

    # ── Module body ────────────────────────────────────────────────────

    def module_body(self, items: list[Any]) -> list[Any]:
        return [i for i in items if i is not None]

    # ── Module definition ──────────────────────────────────────────────

    def module_def(self, items: list[Any]) -> VamsModule:
        module_name = str(items[0])

        port_names: list[str] = []
        body_items: list[Any] = []

        for item in items[1:]:
            if (
                isinstance(item, list)
                and item
                and isinstance(item[0], str)
                and not isinstance(item[0], Token)
            ):
                port_names = item
            elif isinstance(item, list):
                body_items = item

        port_dirs: dict[str, PortDirection] = {}
        types: dict[str, str] = {}  # port and net disciplines
        buses: dict[str, Range] = {}
        parameters: list[Parameter] = []
        instances: list[InstanceData] = []
        ground_net = ""
        analog_block = ""
        properties: dict[str, str] = {}

        for item in body_items:
            if isinstance(item, PortDirData):
                for n in item.names:
                    port_dirs[n] = item.direction
                for n, rng in item.ranges.items():
                    buses.setdefault(n, rng)
            elif isinstance(item, DisciplineDeclData):
                for n in item.names:
                    types[n] = item.discipline
                for n, rng in item.ranges.items():
                    buses.setdefault(n, rng)
            elif isinstance(item, list) and item and isinstance(item[0], tuple):
                for entry in item:
                    if len(entry) == 3:
                        pname, pval, ptype_tag = entry
                        props: dict[str, str] = {}
                        if ptype_tag.startswith("localparam"):
                            props["localparam"] = "true"
                            ptype = (
                                ptype_tag.removeprefix("localparam:")
                                if ":" in ptype_tag
                                else ""
                            )
                        else:
                            ptype = ptype_tag
                        if ptype:
                            props["type"] = ptype
                        parameters.append(
                            Parameter(name=pname, default_value=pval, properties=props)
                        )
                    elif len(entry) == 2:
                        pname, pval = entry
                        parameters.append(Parameter(name=pname, default_value=pval))
            elif isinstance(item, InstanceData):
                instances.append(item)
            elif isinstance(item, GroundData):
                ground_net = item.net
            elif isinstance(item, AnalogData) and item.index < len(self.analog_blocks):
                analog_block = self.analog_blocks[item.index]

        ports: list[Port] = []
        for pn in port_names:
            rng = buses.get(pn)
            ports.append(
                Port(
                    name=pn,
                    direction=port_dirs.get(pn, PortDirection.INOUT),
                    domain=domain_of(pn),
                    discipline=types.get(pn, ""),
                    width=range_width(rng) if rng else 0,
                    properties={"range": f"{rng[0]}:{rng[1]}"} if rng else {},
                )
            )

        if ground_net:
            properties["ground_net"] = ground_net
        if analog_block:
            properties["analog_block"] = analog_block

        return VamsModule(
            module_name, ports, parameters, instances, properties, buses, types
        )

    def _build_circuit(
        self, module: VamsModule, modules: dict[str, VamsModule]
    ) -> Circuit:
        net_map: NetMap = {}
        for port in module.ports:
            rng = module.buses.get(port.name)
            for pin in bits(port.name, *rng) if rng else [port.name]:
                add_port_to_net(net_map, pin, "", pin)

        subcircuits: list[SubCircuit] = []
        for inst in module.instances:
            params: list[Parameter] = []
            if inst.named_params:
                params = [
                    Parameter(name=pname, default_value=pval)
                    for pname, pval in inst.named_params.items()
                ]
            elif inst.positional_params:
                params = [
                    Parameter(name=f"p{pi}", default_value=pv)
                    for pi, pv in enumerate(inst.positional_params)
                ]

            target = modules.get(inst.module_type)
            target_ports = [p.name for p in target.ports] if target else []
            rng = decl_range(inst.name, inst.dims)
            if inst.dims and rng is None:
                raise ValueError(
                    f"{inst.name}{inst.dims[0]}: instance array range must be constant"
                )
            names = instance_names(inst.name, rng)
            conns = list(inst.named_ports.items()) + [
                (target_ports[pi] if pi < len(target_ports) else f"p{pi}", expr)
                for pi, expr in enumerate(inst.positional_ports)
            ]
            for port_name, expr in conns:
                if expr is None:
                    continue  # unconnected
                for name, pin, net in connect(
                    names,
                    port_name,
                    expr,
                    module.buses,
                    target.port_ranges() if target else None,
                ):
                    add_port_to_net(net_map, net, name, pin)

            subcircuits += [
                SubCircuit(name=n, circuit_name=inst.module_type, parameters=params)
                for n in names
            ]

        return Circuit(
            name=module.name,
            ports=module.ports,
            parameters=module.parameters,
            subcircuits=subcircuits,
            connections=typed_connections(net_map, module.types),
            properties=module.properties,
        )

    # ── Top-level ──────────────────────────────────────────────────────

    def start(self, items: list[Any]) -> Netlist:
        modules = {m.name: m for m in items if isinstance(m, VamsModule)}
        circuits = [self._build_circuit(m, modules) for m in modules.values()]
        ext_circuits: dict[str, ExternalCircuit] = {}

        for item in items:
            if item is None:
                continue
            if isinstance(item, NatureData):
                props: dict[str, str] = {"ext_kind": "nature"}
                for k, v in item.attrs.items():
                    if v.prefixed_value is not None:
                        from kfnetlist.morphnet.netlist.value_utils import (
                            format_si_value,
                        )

                        props[f"nature_{k}"] = format_si_value(v.prefixed_value)
                    else:
                        props[f"nature_{k}"] = ""
                ext_circuits[item.name] = ExternalCircuit(
                    name=item.name,
                    kind=ExternalCircuitKind.NATURE,
                    properties=props,
                )
            elif isinstance(item, DisciplineData):
                props = {"ext_kind": "discipline"}
                for role, nature_name in item.natures.items():
                    props[f"discipline_{role}"] = nature_name
                if item.domain:
                    props["discipline_domain"] = item.domain
                ext_circuits[item.name] = ExternalCircuit(
                    name=item.name,
                    kind=ExternalCircuitKind.DISCIPLINE,
                    properties=props,
                )
            elif isinstance(item, ParamsetData):
                params = [
                    Parameter(name=pn, default_value=pv)
                    for pn, pv in item.params.items()
                ]
                ext_circuits[item.name] = ExternalCircuit(
                    name=item.name,
                    kind=ExternalCircuitKind.MODEL,
                    parameters=params,
                    properties={"ext_kind": "model", "model_type": item.base_type},
                )

        top_circuit = circuits[-1].name if circuits else ""

        netlist = Netlist(
            name="",
            top_circuit=top_circuit,
            circuits=circuits,
            ext_circuits=list(ext_circuits.values()),
        )
        propagate_domains(netlist, self.disciplines, self.pin_domains)
        return netlist
