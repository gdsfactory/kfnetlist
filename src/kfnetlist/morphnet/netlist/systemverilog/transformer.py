from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from lark import Token, Transformer

from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    Directive,
    Netlist,
    Parameter,
    ParameterValue,
    Port,
    PortDirection,
    SignalDomain,
    SubCircuit,
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
    resolve,
    to_int,
)
from kfnetlist.morphnet.netlist.net_utils import (
    NetMap,
    add_port_to_net,
    domain_of,
    propagate_domains,
    typed_connections,
)
from kfnetlist.morphnet.netlist.value_utils import (
    is_si_number,
    parse_parameter_number,
)

DIR_MAP = {
    "input": PortDirection.INPUT,
    "output": PortDirection.OUTPUT,
    "inout": PortDirection.INOUT,
    "ref": PortDirection.INOUT,
}

SIZED_RE = re.compile(r"(?:\d[\d_]*\s*)?'[sS]?([bBoOdDhH])\s*([0-9a-fA-F_]+)")
BASES = {"b": 2, "o": 8, "d": 10, "h": 16}


class TypeSpec(str):
    """Type name (``wire``, ``connection``, ``""``) carrying its packed dims."""

    dims: list[Dim]

    @classmethod
    def make(cls, name: str, dims: list[Dim]) -> TypeSpec:
        spec = cls(name)
        spec.dims = dims
        return spec


@dataclass
class PortSpec:
    name: str
    direction: str | None
    type: TypeSpec | None
    dims: list[Dim] = field(default_factory=list)  # unpacked


@dataclass
class ParamSpec:
    name: str
    expr: str
    type: str
    local: bool


@dataclass
class PortDecl:
    direction: str
    ports: list[PortSpec]


@dataclass
class DataDecl:
    type: TypeSpec
    assigns: list[tuple[str, list[Dim], str | None]]


@dataclass
class HierInst:
    name: str
    dims: list[Dim]
    named: dict[str, str | None] = field(default_factory=dict)
    ordered: list[str | None] = field(default_factory=list)
    wildcard: bool = False


@dataclass
class InstanceStmt:
    module: str
    named_params: dict[str, str]
    ordered_params: list[str]
    instances: list[HierInst]


@dataclass
class Merge:
    nets: list[str]


@dataclass
class Placeholder:
    index: int


@dataclass
class ModuleData:
    name: str
    ports: list[PortSpec]
    params: list[ParamSpec]
    items: list[Any]

    def port_names(self) -> list[str]:
        return [p.name for p in self.ports]

    def declarations(self) -> tuple[dict[str, str], dict[str, str], dict[str, Range]]:
        """Port directions, net/port types and bus ranges declared in this module."""
        directions: dict[str, str] = {}
        types: dict[str, str] = {}
        ranges: dict[str, Range] = {}

        def declare(name: str, ptype: TypeSpec | None, dims: list[Dim]) -> None:
            if ptype:
                types.setdefault(name, ptype)
            rng = decl_range(name, (ptype.dims if ptype is not None else []) + dims)
            if rng is not None:
                ranges.setdefault(name, rng)

        # ANSI header: a bare name inherits the previous port's direction and type
        ansi = any(p.direction or p.type is not None for p in self.ports)
        prev_dir, prev_type = "inout", None
        for spec in self.ports:
            if ansi and spec.direction is None and spec.type is None:
                spec.direction, spec.type = prev_dir, prev_type
            elif ansi and spec.direction is None:
                spec.direction = prev_dir
            if spec.direction:
                directions[spec.name] = spec.direction
                prev_dir, prev_type = spec.direction, spec.type
            declare(spec.name, spec.type, spec.dims)
        for item in self.items:
            if isinstance(item, PortDecl):
                for spec in item.ports:
                    directions[spec.name] = item.direction
                    declare(spec.name, spec.type, spec.dims)
            elif isinstance(item, DataDecl):
                for n, dims, _ in item.assigns:
                    declare(n, item.type, dims)
        return directions, types, ranges

    def port_ranges(self) -> dict[str, Range | None]:
        ranges = self.declarations()[2]
        return {n: ranges.get(n) for n in self.port_names()}

    def param_names(self) -> list[str]:
        params = self.params + [p for i in self.items if isinstance(i, list) for p in i]
        return [p.name for p in params if not p.local]


class HeaderParams(list[ParamSpec]):
    """Parameters from the ``#(...)`` module header."""


IMPLICIT = object()  # `.name` port connection


def _ident(tok: Token) -> str:
    return str(tok).removeprefix("\\")


def parameter_value(expr: str) -> tuple[ParameterValue | None, dict[str, str]]:
    """Numeric value when ``expr`` is a literal, else the expression text."""
    if is_si_number(expr):
        return parse_parameter_number(expr.replace("_", "")), {}
    m = SIZED_RE.fullmatch(expr)
    if m:
        value = int(m.group(2).replace("_", ""), BASES[m.group(1).lower()])
        return parse_parameter_number(str(value)), {}
    return None, {"expr": expr}


class SystemVerilogTransformer(Transformer[Token, Netlist]):
    """Transform a SystemVerilog parse tree into a Netlist model."""

    def __init__(
        self,
        blocks: list[str] | None = None,
        directives: list[Directive] | None = None,
        disciplines: Mapping[str, SignalDomain] | None = None,
    ) -> None:
        super().__init__()
        self.blocks = blocks or []
        self.directives = directives or []
        self.disciplines = disciplines or {}

    # ── Expressions ─────────────────────────────────────────────────────

    def number(self, items: list[Token]) -> Literal:
        return Literal(items[0])

    def sized_number(self, items: list[Token]) -> Literal:
        return Literal(re.sub(r"\s+", "", str(items[0])))

    def string(self, items: list[Token]) -> str:
        return str(items[0])

    def binop(self, items: list[Any]) -> str:
        return f"{items[0]}{items[1]}{items[2]}"

    def unop(self, items: list[Any]) -> str:
        return f"{items[0]}{items[1]}"

    def paren(self, items: list[Any]) -> str:
        return f"({items[0]})"

    def concat(self, items: list[Any]) -> Concat:
        return Concat.make(items)

    def replicate(self, items: list[Any]) -> Concat:
        n = to_int(items[0])
        if n is None or n < 1:
            raise ValueError(
                f"replication count {items[0]!r} must be a positive integer"
            )
        return Concat.make(items[1:] * n)

    def range(self, items: list[Any]) -> Dim:
        return Dim(str(i) for i in items)

    def dims(self, items: list[Dim]) -> list[Dim]:
        return items

    def net_ref(self, items: list[Any]) -> NetRef:
        if len(items) > 2:
            raise ValueError(
                f"{_ident(items[0])}{''.join(map(str, items[1:]))}: "
                "multi-dimensional selects are not supported"
            )
        return NetRef.make(_ident(items[0]), items[1] if len(items) > 1 else ())

    # ── Types ───────────────────────────────────────────────────────────

    def builtin_type(self, items: list[Any]) -> TypeSpec:
        return TypeSpec.make(str(items[0]), [i for i in items if isinstance(i, Dim)])

    def implicit_type(self, items: list[Any]) -> TypeSpec:
        return TypeSpec.make("", [i for i in items if isinstance(i, Dim)])

    def user_type(self, items: list[Token]) -> TypeSpec:
        return TypeSpec.make(_ident(items[0]), [])

    # ── Parameters ──────────────────────────────────────────────────────

    def param_assign(self, items: list[Any]) -> tuple[str, str]:
        return _ident(items[0]), str(items[2])

    def _param_specs(self, items: list[Any], local_default: bool) -> list[ParamSpec]:
        local, ptype = local_default, ""
        specs = []
        for item in items:
            if isinstance(item, Token) and item.type == "PARAM_KW":
                local = str(item) == "localparam"
            elif isinstance(item, tuple):
                specs.append(ParamSpec(item[0], item[1], ptype, local))
            else:
                ptype = str(item)
        return specs

    def param_port(self, items: list[Any]) -> ParamSpec:
        return self._param_specs(items, local_default=False)[0]

    def param_port_list(self, items: list[ParamSpec]) -> HeaderParams:
        # `#(parameter real a = 1, b = 2)`: b inherits `real` from a
        for prev, spec in zip(items, items[1:]):
            if not spec.type:
                spec.type = prev.type
        return HeaderParams(items)

    def param_decl(self, items: list[Any]) -> list[ParamSpec]:
        return self._param_specs(items, local_default=False)

    # ── Ports ───────────────────────────────────────────────────────────

    def port_name(self, items: list[Any]) -> PortSpec:
        if len(items) == 4:  # user type first: `connection [3:0] a [1:0]`
            ptype = TypeSpec.make(_ident(items[0]), items[1])
            return PortSpec(_ident(items[2]), None, ptype, items[3])
        return PortSpec(_ident(items[0]), None, None, items[1])

    def ansi_port(self, items: list[Any]) -> PortSpec:
        spec = items[-1]
        for item in items[:-1]:
            if isinstance(item, Token) and item.type == "PORT_DIR":
                spec.direction = str(item)
            elif isinstance(item, TypeSpec):
                spec.type = item
        return spec

    def port_list(self, items: list[PortSpec]) -> list[PortSpec]:
        return items

    def port_decl(self, items: list[Any]) -> PortDecl:
        # `input [3:0] a, b;` / `input connection a, b;`: names share the first type
        ptype = next((i for i in items[1:] if isinstance(i, TypeSpec)), None)
        specs = [i for i in items[1:] if isinstance(i, PortSpec)]
        for spec in specs:
            spec.type = ptype = spec.type if spec.type is not None else ptype
        return PortDecl(str(items[0]), specs)

    # ── Net / variable declarations ─────────────────────────────────────

    def decl_assign(self, items: list[Any]) -> tuple[str, list[Dim], str | None]:
        return _ident(items[0]), items[1], (items[2] if len(items) > 2 else None)

    def data_decl(self, items: list[Any]) -> DataDecl:
        return DataDecl(items[0], items[1:])

    def user_decl(self, items: list[Any]) -> DataDecl:
        dims = [i for i in items[1:] if isinstance(i, Dim)]
        assigns = [
            i for i in items[1:] if isinstance(i, tuple) and not isinstance(i, Dim)
        ]
        return DataDecl(TypeSpec.make(_ident(items[0]), dims), assigns)

    # ── Instances ───────────────────────────────────────────────────────

    def named_param(self, items: list[Any]) -> tuple[str, str]:
        return _ident(items[0]), (str(items[1]) if len(items) > 1 else "")

    def ordered_param(self, items: list[Any]) -> str:
        return str(items[0])

    def param_values(self, items: list[Any]) -> list[Any]:
        return items

    def named_conn(self, items: list[Any]) -> tuple[str, Any]:
        return _ident(items[0]), (items[1] if len(items) > 1 else None)

    def implicit_conn(self, items: list[Token]) -> tuple[str, Any]:
        return _ident(items[0]), IMPLICIT

    def wildcard_conn(self, items: list[Any]) -> str:
        return ".*"

    def ordered_conn(self, items: list[Any]) -> list[Any]:
        return [items[0] if items else None]

    def hier_inst(self, items: list[Any]) -> HierInst:
        inst = HierInst(name=_ident(items[0]), dims=items[1])
        for conn in items[2:]:
            if conn == ".*":
                inst.wildcard = True
            elif isinstance(conn, tuple):
                inst.named[conn[0]] = conn[1]
            else:
                inst.ordered.extend(conn)
        if inst.ordered == [None]:  # `X1 ()`
            inst.ordered = []
        return inst

    def instance_stmt(self, items: list[Any]) -> InstanceStmt:
        stmt = InstanceStmt(_ident(items[0]), {}, [], [])
        for item in items[1:]:
            if isinstance(item, HierInst):
                stmt.instances.append(item)
            else:
                for arg in item:
                    if isinstance(arg, tuple):
                        stmt.named_params[arg[0]] = arg[1]
                    else:
                        stmt.ordered_params.append(arg)
        return stmt

    # ── assign / alias / placeholders ───────────────────────────────────

    def assign_stmt(self, items: list[NetRef]) -> list[Merge]:
        return [Merge([a, b]) for a, b in zip(items[::2], items[1::2])]

    def alias_stmt(self, items: list[NetRef]) -> Merge:
        return Merge(list(items))

    def placeholder(self, items: list[Token]) -> Placeholder:
        return Placeholder(int(str(items[0])))

    # ── Module ──────────────────────────────────────────────────────────

    def end_label(self, items: list[Token]) -> None:
        return None

    def module_def(self, items: list[Any]) -> ModuleData:
        module = ModuleData(_ident(items[0]), [], [], [])
        for item in items[1:]:
            if isinstance(item, HeaderParams):
                module.params = item
            elif isinstance(item, list) and item and isinstance(item[0], ParamSpec):
                module.items.append(item)
            elif isinstance(item, list) and item and isinstance(item[0], PortSpec):
                module.ports = item
            elif isinstance(item, list):
                module.items.extend(item)  # assign a = b, c = d
            elif item is not None:
                module.items.append(item)
        return module

    # ── Top-level ───────────────────────────────────────────────────────

    def start(self, items: list[Any]) -> Netlist:
        modules = {m.name: m for m in items if isinstance(m, ModuleData)}
        circuits = [self._build_circuit(m, modules) for m in modules.values()]
        properties = {
            f"behavioral_block_{p.index}": self.blocks[p.index]
            for p in items
            if isinstance(p, Placeholder) and p.index < len(self.blocks)
        }
        used = {s.circuit_name for c in circuits for s in c.subcircuits}
        tops = [c.name for c in circuits if c.name not in used] or [
            c.name for c in circuits
        ]
        netlist = Netlist(
            top_circuit=tops[-1] if tops else "",
            circuits=circuits,
            properties=properties,
            directives=self.directives,
        )
        propagate_domains(netlist, self.disciplines)
        return netlist

    def _build_circuit(
        self, module: ModuleData, modules: dict[str, ModuleData]
    ) -> Circuit:
        directions, types, buses = module.declarations()

        parameters: list[Parameter] = [self._parameter(p) for p in module.params]
        properties: dict[str, str] = {}
        merges: list[list[Any]] = []
        instances: list[InstanceStmt] = []
        for item in module.items:
            if isinstance(item, DataDecl):
                for n, _, rhs in item.assigns:
                    if isinstance(rhs, (NetRef, Concat)):
                        merges.append([NetRef.make(n), rhs])  # wire a = b;
            elif isinstance(item, list):
                parameters.extend(self._parameter(p) for p in item)
            elif isinstance(item, Merge):
                merges.append(item.nets)
            elif isinstance(item, InstanceStmt):
                instances.append(item)
            elif isinstance(item, Placeholder) and item.index < len(self.blocks):
                properties[f"behavioral_block_{item.index}"] = self.blocks[item.index]

        port_names = module.port_names()
        ports = []
        port_bits: dict[str, list[str]] = {}
        for n in port_names:
            rng = buses.get(n)
            port_bits[n] = bits(n, *rng) if rng else [n]
            ports.append(
                Port(
                    name=n,
                    direction=DIR_MAP.get(
                        directions.get(n, "inout"), PortDirection.INOUT
                    ),
                    domain=domain_of(n),
                    discipline=types.get(n, ""),
                    width=range_width(rng) if rng else 0,
                    properties={"range": f"{rng[0]}:{rng[1]}"} if rng else {},
                )
            )
        pins = {b for bs in port_bits.values() for b in bs}

        # ── nets (bit level): assign/alias merge nets; a module port names its net
        parent: dict[str, str] = {}

        def find(net: str) -> str:
            while parent.get(net, net) != net:
                net = parent[net]
            return net

        for group in merges:
            sides = [resolve(expr, buses) for expr in group]
            if any(len(side) != len(sides[0]) for side in sides):
                raise ValueError(
                    f"{module.name}: width mismatch in {' = '.join(map(str, group))}"
                )
            for side in sides[1:]:
                for x, y in zip(sides[0], side):
                    a, b = find(x), find(y)
                    if a != b:
                        keep, drop = (b, a) if b in pins and a not in pins else (a, b)
                        parent[drop] = keep

        net_map: NetMap = {}
        for bs in port_bits.values():
            for b in bs:
                add_port_to_net(net_map, find(b), "", b)

        subcircuits: list[SubCircuit] = []
        for stmt in instances:
            target = modules.get(stmt.module)
            param_names = target.param_names() if target else []
            target_ranges = target.port_ranges() if target else None
            params = [
                Parameter(name=n, default_value=v, properties=props)
                for n, expr in stmt.named_params.items()
                for v, props in [parameter_value(expr)]
            ] + [
                Parameter(
                    name=param_names[i] if i < len(param_names) else f"p{i}",
                    default_value=v,
                    properties=props,
                )
                for i, expr in enumerate(stmt.ordered_params)
                for v, props in [parameter_value(expr)]
            ]
            for inst in stmt.instances:
                rng = decl_range(inst.name, inst.dims)
                if inst.dims and rng is None:
                    raise ValueError(
                        f"{inst.name}{inst.dims[0]}: instance array range must be constant"
                    )
                names = instance_names(inst.name, rng)
                for port, expr in self._connections(inst, stmt.module, target):
                    for name, pin, net in connect(
                        names, port, expr, buses, target_ranges
                    ):
                        add_port_to_net(net_map, find(net), name, pin)
                subcircuits += [
                    SubCircuit(name=n, circuit_name=stmt.module, parameters=params)
                    for n in names
                ]

        return Circuit(
            name=module.name,
            ports=ports,
            parameters=parameters,
            subcircuits=subcircuits,
            connections=typed_connections(net_map, types),
            properties=properties,
        )

    @staticmethod
    def _parameter(spec: ParamSpec) -> Parameter:
        value, props = parameter_value(spec.expr)
        if spec.local:
            props["localparam"] = "true"
        if spec.type:
            props["type"] = spec.type
        return Parameter(name=spec.name, default_value=value, properties=props)

    @staticmethod
    def _connections(
        inst: HierInst, module: str, target: ModuleData | None
    ) -> list[tuple[str, Any]]:
        """``(instance port, net expression)`` pairs for one instance."""
        target_ports = target.port_names() if target else []
        conns: list[tuple[str, Any]] = list(inst.named.items())
        conns += [
            (target_ports[i] if i < len(target_ports) else f"p{i}", net)
            for i, net in enumerate(inst.ordered)
        ]
        if inst.wildcard:
            if target is None:
                raise ValueError(
                    f"{inst.name}: `.*` needs the definition of module {module!r}"
                )
            conns += [(p, IMPLICIT) for p in target_ports if p not in inst.named]

        pairs = []
        for port, net in conns:
            if net is None:
                continue  # unconnected
            if net is IMPLICIT:
                net = NetRef.make(port)
            elif not isinstance(net, (NetRef, Literal, Concat)):
                raise ValueError(
                    f"{inst.name}.{port}: unsupported port expression {net!r}"
                )
            pairs.append((port, net))
        return pairs
