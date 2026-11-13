from __future__ import annotations

import re
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
    SubCircuit,
)
from kfnetlist.morphnet.netlist.net_utils import (
    NetMap,
    add_port_to_net,
    domain_of,
    net_map_to_connections,
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


class NetRef(str):
    """Expression text that names a net (``a``, ``a[3]``, ``a[3:0]``)."""


class Literal(str):
    """Numeric literal text (``0``, ``1'b0``) — a constant tie when used as a net."""


@dataclass
class PortSpec:
    name: str
    direction: str | None
    type: str | None


@dataclass
class ParamSpec:
    name: str
    expr: str
    type: str
    local: bool


@dataclass
class PortDecl:
    direction: str
    type: str
    names: list[str]


@dataclass
class DataDecl:
    type: str
    assigns: list[tuple[str, str | None]]


@dataclass
class HierInst:
    name: str
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
    ) -> None:
        super().__init__()
        self.blocks = blocks or []
        self.directives = directives or []

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

    def range(self, items: list[Any]) -> str:
        return f"[{':'.join(items)}]"

    def dims(self, items: list[str]) -> str:
        return "".join(items)

    def net_ref(self, items: list[Any]) -> NetRef:
        return NetRef(_ident(items[0]) + "".join(items[1:]))

    # ── Types ───────────────────────────────────────────────────────────

    def builtin_type(self, items: list[Any]) -> str:
        return str(items[0])

    def implicit_type(self, items: list[Any]) -> str:
        return ""

    def user_type(self, items: list[Token]) -> str:
        return _ident(items[0])

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

    def ansi_port(self, items: list[Any]) -> PortSpec:
        direction = ptype = None
        name = ""
        for item in items:
            if isinstance(item, Token) and item.type == "PORT_DIR":
                direction = str(item)
            elif isinstance(item, Token) and item.type == "IDENT":
                name = _ident(item)
            elif not name and isinstance(item, str):
                ptype = item
        return PortSpec(name, direction, ptype)

    def port_list(self, items: list[PortSpec]) -> list[PortSpec]:
        return items

    def port_decl(self, items: list[Any]) -> PortDecl:
        direction, ptype, names = str(items[0]), "", []
        for item in items[1:]:
            if isinstance(item, Token) and item.type == "IDENT":
                names.append(_ident(item))
            elif isinstance(item, str) and not names:
                ptype = item
        return PortDecl(direction, ptype, names)

    # ── Net / variable declarations ─────────────────────────────────────

    def decl_assign(self, items: list[Any]) -> tuple[str, str | None]:
        return _ident(items[0]), (items[2] if len(items) > 2 else None)

    def data_decl(self, items: list[Any]) -> DataDecl:
        return DataDecl(str(items[0]), items[1:])

    def user_decl(self, items: list[Any]) -> DataDecl:
        return DataDecl(_ident(items[0]), items[1:])

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
        inst = HierInst(name=_ident(items[0]) + items[1])
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
        return Netlist(
            top_circuit=tops[-1] if tops else "",
            circuits=circuits,
            properties=properties,
            directives=self.directives,
        )

    def _build_circuit(
        self, module: ModuleData, modules: dict[str, ModuleData]
    ) -> Circuit:
        # ── ports: ANSI header specs, completed by non-ANSI body declarations
        directions: dict[str, str] = {}
        types: dict[str, str] = {}
        ansi = any(p.direction or p.type for p in module.ports)
        prev_dir, prev_type = "inout", ""
        for spec in module.ports:
            if ansi and spec.direction is None and spec.type is None:
                spec.direction, spec.type = prev_dir, prev_type
            elif ansi and spec.direction is None:
                spec.direction = prev_dir
            if spec.direction:
                directions[spec.name] = spec.direction
                prev_dir, prev_type = spec.direction, spec.type or ""
            if spec.type:
                types[spec.name] = spec.type

        parameters: list[Parameter] = [self._parameter(p) for p in module.params]
        properties: dict[str, str] = {}
        merges: list[list[str]] = []
        instances: list[InstanceStmt] = []
        for item in module.items:
            if isinstance(item, PortDecl):
                for n in item.names:
                    directions[n] = item.direction
                    if item.type:
                        types[n] = item.type
            elif isinstance(item, DataDecl):
                for n, rhs in item.assigns:
                    types[n] = types.get(n) or item.type
                    if isinstance(rhs, NetRef):
                        merges.append([n, rhs])  # wire a = b;
            elif isinstance(item, list):
                parameters.extend(self._parameter(p) for p in item)
            elif isinstance(item, Merge):
                merges.append(item.nets)
            elif isinstance(item, InstanceStmt):
                instances.append(item)
            elif isinstance(item, Placeholder) and item.index < len(self.blocks):
                properties[f"behavioral_block_{item.index}"] = self.blocks[item.index]

        port_names = module.port_names()
        ports = [
            Port(
                name=n,
                direction=DIR_MAP.get(directions.get(n, "inout"), PortDirection.INOUT),
                domain=domain_of(n),
                discipline=types.get(n, ""),
            )
            for n in port_names
        ]

        # ── nets: assign/alias merge nets; a module port names its merged net
        parent: dict[str, str] = {}

        def find(net: str) -> str:
            while parent.get(net, net) != net:
                net = parent[net]
            return net

        for group in merges:
            for other in group[1:]:
                a, b = find(group[0]), find(other)
                if a != b:
                    keep, drop = (
                        (b, a) if b in port_names and a not in port_names else (a, b)
                    )
                    parent[drop] = keep

        net_map: NetMap = {}
        for n in port_names:
            add_port_to_net(net_map, find(n), "", n)

        subcircuits: list[SubCircuit] = []
        for stmt in instances:
            target = modules.get(stmt.module)
            param_names = target.param_names() if target else []
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
                for port, net in self._connections(inst, stmt.module, target):
                    add_port_to_net(net_map, find(net), inst.name, port)
                subcircuits.append(
                    SubCircuit(
                        name=inst.name,
                        circuit_name=stmt.module,
                        parameters=params,
                    )
                )

        return Circuit(
            name=module.name,
            ports=ports,
            parameters=parameters,
            subcircuits=subcircuits,
            connections=net_map_to_connections(net_map),
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
    ) -> list[tuple[str, str]]:
        """``(instance port, net)`` pairs for one instance."""
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
                net = port
            elif not isinstance(net, (NetRef, Literal)):
                raise ValueError(
                    f"{inst.name}.{port}: unsupported port expression {net!r}"
                )
            pairs.append((port, str(net)))
        return pairs
