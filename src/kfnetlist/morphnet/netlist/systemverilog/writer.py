from __future__ import annotations

import re

from kfnetlist.morphnet.morphnet_schema import (
    Circuit,
    Directive,
    DirectiveKind,
    ExternalCircuit,
    Netlist,
    Parameter,
    SubCircuit,
)
from kfnetlist.morphnet.netlist.net_utils import connections_to_instance_nets
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
            " ".join(
                part
                for part in (
                    port.direction.name.lower(),
                    port.discipline,
                    sv_name(port.name),
                )
                if part
            )
            for port in circuit.ports
        )
        ports = f"(\n  {ports}\n)" if ports else "()"
        lines.append(f"module {sv_name(circuit.name)}{params} {ports};")

        for p in circuit.parameters:
            if p.properties.get("localparam") == "true":
                lines.append(f"  {self.param_decl(p, 'localparam')};")

        inst_nets = connections_to_instance_nets(circuit.connections)
        for ref in circuit.subcircuits:
            lines.append(
                self.write_instance(ref, inst_nets, ext_by_name, circuit_by_name)
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
            port_order = [p.name for p in target.ports]
        else:
            port_order = [pn for (inst, pn) in inst_nets if inst == ref.name]

        conns = ", ".join(
            f".{sv_name(pn)}({sv_name(inst_nets[(ref.name, pn)]) if (ref.name, pn) in inst_nets else ''})"
            for pn in port_order
        )
        return f"  {sv_name(ref.circuit_name)}{params} {sv_name(ref.name)} ({conns});"


def write_systemverilog(netlist: Netlist) -> str:
    """Convert a Netlist model to structural SystemVerilog text."""
    return SystemVerilogWriter().write(netlist)
