from __future__ import annotations

import re

from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    Directive,
    DirectiveKind,
    ExternalCircuit,
    Netlist,
    Parameter,
    Port,
    SubCircuit,
)
from kfnetlist.morphnet.netlist.hdl import (
    Buses,
    Range,
    bus_pins,
    declared_range,
    connection_expr,
    net_buses,
    port_pins,
)
from kfnetlist.morphnet.netlist.net_utils import BIT_RE, connections_to_instance_nets
from kfnetlist.morphnet.netlist.value_utils import to_float

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
RESERVED = {
    "module", "macromodule", "endmodule", "assign", "alias", "parameter",
    "localparam", "input", "output", "inout", "ref", "signed", "unsigned",
    "wire", "tri", "triand", "trior", "tri0", "tri1", "supply0", "supply1",
    "trireg", "wand", "wor", "uwire", "logic", "bit", "reg", "byte", "shortint",
    "int", "longint", "integer", "time", "shortreal", "real", "realtime", "string",
}  # fmt: skip


def sv_name(name: str) -> str:
    """``name`` as a SystemVerilog identifier, escaped (``\\0 ``) when needed."""
    if IDENT_RE.fullmatch(name) and name not in RESERVED:
        return name
    return f"\\{name} "


BUILTIN_TYPES = RESERVED - {"input", "output", "inout", "ref", "module", "macromodule",
                            "endmodule", "assign", "alias", "parameter", "localparam"}  # fmt: skip


def port_range(port: Port) -> Range | None:
    return declared_range(port.width, port.properties.get("range"))


def declaration(type_name: str, name: str, rng: Range | None) -> str:
    """``wire [3:0] a`` for builtin types, ``connection a [3:0]`` for user types."""
    if rng is None:
        return " ".join(p for p in (type_name, sv_name(name)) if p)
    dim = f"[{rng[0]}:{rng[1]}]"
    if type_name and type_name not in BUILTIN_TYPES:
        return f"{type_name} {sv_name(name)} {dim}"
    return " ".join(p for p in (type_name, dim, sv_name(name)) if p)


def format_param_value(param: Parameter) -> str:
    """Plain number (SI suffixes are not SystemVerilog), else the expression text."""
    pval = param.default_value
    if pval is not None and pval.prefixed_value is not None:
        return f"{to_float(pval.prefixed_value):.12g}"
    return param.properties.get("expr", "0")


class SystemVerilogWriter:
    """Convert a Netlist model to structural SystemVerilog text."""

    def write(self, netlist: Netlist) -> str:
        lines: list[str] = []
        self.write_directives(netlist.directives, lines)
        lines.extend(
            v
            for k, v in netlist.properties.items()
            if k.startswith("behavioral_block_")
        )

        ext_by_name = {e.name: e for e in netlist.ext_circuits}
        circuit_by_name = {c.name: c for c in netlist.circuits}
        for circuit in netlist.circuits:
            if lines:
                lines.append("")
            self.write_module(circuit, ext_by_name, circuit_by_name, lines)
        lines.append("")
        return "\n".join(lines)

    def write_directives(self, directives: list[Directive], lines: list[str]) -> None:
        for d in directives:
            if d.kind == DirectiveKind.INCLUDE:
                lines.append(f'`include "{d.value}"')
            elif d.kind == DirectiveKind.DEFINE:
                lines.append(f"`define {d.value}")
            elif d.kind == DirectiveKind.TIMESCALE:
                lines.append(f"`timescale {d.value}")

    def write_module(
        self,
        circuit: Circuit,
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
        lines: list[str],
    ) -> None:
        header_params = [
            p for p in circuit.parameters if p.properties.get("localparam") != "true"
        ]
        params = ""
        if header_params:
            params = " #(" + ", ".join(self.param_decl(p) for p in header_params) + ")"
        ports = ",\n  ".join(
            f"{port.direction.name.lower()} "
            + declaration(port.discipline, port.name, port_range(port))
            for port in circuit.ports
        )
        ports = f"(\n  {ports}\n)" if ports else "()"
        lines.append(f"module {sv_name(circuit.name)}{params} {ports};")

        for p in circuit.parameters:
            if p.properties.get("localparam") == "true":
                lines.append(f"  {self.param_decl(p, 'localparam')};")

        # buses: declared port ranges, then internal `name[i]` nets (declared here)
        port_buses = {
            p.name: rng for p in circuit.ports if (rng := port_range(p)) is not None
        }
        port_names = {p.name for p in circuit.ports}
        net_types = {
            BIT_RE.sub("", c.name): c.properties.get("discipline", "")
            for c in circuit.connections
        }
        # a scalar port literally named `in[3]` (from kfnetlist) is not a bus bit
        internal = net_buses(
            [c.name for c in circuit.connections if c.name not in port_names]
        )
        buses: Buses = {
            **{b: r for b, r in internal.items() if b not in port_names},
            **port_buses,
        }
        for net, net_type in net_types.items():
            if net in port_names or (net not in internal and not net_type):
                continue
            rng = internal.get(net)
            lines.append(f"  {declaration(net_type or 'wire', net, rng)};")

        inst_nets = connections_to_instance_nets(circuit.connections)
        for ref in circuit.subcircuits:
            lines.append(
                self.write_instance(ref, inst_nets, ext_by_name, circuit_by_name, buses)
            )

        lines.extend(
            f"  {v}"
            for k, v in circuit.properties.items()
            if k.startswith("behavioral_block_")
        )
        lines.append("endmodule")

    @staticmethod
    def param_decl(p: Parameter, keyword: str = "parameter") -> str:
        ptype = p.properties.get("type", "")
        type_str = f" {ptype}" if ptype else ""
        return f"{keyword}{type_str} {sv_name(p.name)} = {format_param_value(p)}"

    def write_instance(
        self,
        ref: SubCircuit,
        inst_nets: dict[tuple[str, str], str],
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
        buses: Buses | None = None,
    ) -> str:
        params = ""
        if ref.parameters:
            params = (
                " #("
                + ", ".join(
                    f".{sv_name(p.name)}({format_param_value(p)})"
                    for p in ref.parameters
                )
                + ")"
            )

        target = circuit_by_name.get(ref.circuit_name) or ext_by_name.get(
            ref.circuit_name
        )
        if target is not None:
            port_order = [
                (p.name, port_pins(p.name, p.width, p.properties.get("range")))
                for p in target.ports
            ]
        else:
            port_order = bus_pins([pn for (inst, pn) in inst_nets if inst == ref.name])

        conns = []
        for name, pins in port_order:
            nets = [inst_nets.get((ref.name, pin)) for pin in pins]
            expr = connection_expr(f"{ref.name}.{name}", nets, buses or {}, sv_name)
            conns.append(f".{sv_name(name)}({expr})")
        conns = ", ".join(conns)
        return f"  {sv_name(ref.circuit_name)}{params} {sv_name(ref.name)} ({conns});"


def write_systemverilog(netlist: Netlist) -> str:
    """Convert a Netlist model to structural SystemVerilog text."""
    return SystemVerilogWriter().write(netlist)
