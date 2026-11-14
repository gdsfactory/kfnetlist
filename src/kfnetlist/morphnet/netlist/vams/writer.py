from __future__ import annotations

from kfnetlist.morphnet.morphnet_schema import (
    Netlist,
    Directive,
    DirectiveKind,
    ExternalCircuit,
    ExternalCircuitKind,
    Circuit,
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
from kfnetlist.morphnet.netlist.systemverilog.writer import sv_name
from kfnetlist.morphnet.netlist.value_utils import format_si_value


def declaration(keyword: str, names: list[str], rng: Range | None) -> str:
    """``input a, b`` / ``optical [3:0] bus``."""
    dim = f" [{rng[0]}:{rng[1]}]" if rng else ""
    return f"{keyword}{dim} {', '.join(names)}"


class VamsWriter:
    """Convert a Netlist model to Verilog-AMS netlist text."""

    def write(self, netlist: Netlist) -> str:
        lines: list[str] = []

        ext_by_name: dict[str, ExternalCircuit] = {
            e.name: e for e in netlist.ext_circuits
        }
        circuit_by_name: dict[str, Circuit] = {m.name: m for m in netlist.circuits}

        self.write_directives(netlist.directives, lines)

        for ext in netlist.ext_circuits:
            if ext.kind == ExternalCircuitKind.NATURE:
                self.write_nature(ext, lines)
            elif ext.kind == ExternalCircuitKind.DISCIPLINE:
                self.write_discipline(ext, lines)

        for circuit in netlist.circuits:
            self.write_module(circuit, ext_by_name, circuit_by_name, lines)

        if lines and lines[-1] != "":
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

    def write_nature(self, ext: ExternalCircuit, lines: list[str]) -> None:
        lines.append(f"nature {ext.name};")
        for key, val in ext.properties.items():
            if key.startswith("nature_"):
                attr = key.removeprefix("nature_")
                lines.append(f"  {attr} = {val};")
        lines.append("endnature")

    def write_discipline(self, ext: ExternalCircuit, lines: list[str]) -> None:
        lines.append(f"discipline {ext.name};")
        domain = ext.properties.get("discipline_domain")
        if domain:
            lines.append(f"  domain {domain};")
        for key, val in ext.properties.items():
            if key.startswith("discipline_") and key != "discipline_domain":
                role = key.removeprefix("discipline_")
                lines.append(f"  {role} {val};")
        lines.append("enddiscipline")

    def write_module(
        self,
        circuit: Circuit,
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
        lines: list[str],
    ) -> None:
        port_names = [p.name for p in circuit.ports]
        ports_str = ", ".join(port_names)
        lines.append(f"module {circuit.name} ({ports_str});")

        ranges = {
            p.name: declared_range(p.width, p.properties.get("range"))
            for p in circuit.ports
        }
        dirs_by_dir: dict[tuple[str, Range | None], list[str]] = {}
        for port in circuit.ports:
            d = port.direction.name.lower()
            dirs_by_dir.setdefault((d, ranges[port.name]), []).append(port.name)
        for (d, rng), names in dirs_by_dir.items():
            lines.append(f"  {declaration(d, names, rng)};")

        # disciplines of ports, then of internal nets (`name[i]` nets are buses)
        port_names = set(ranges)
        internal = net_buses(
            [c.name for c in circuit.connections if c.name not in port_names]
        )
        net_types = {
            BIT_RE.sub("", c.name): c.properties.get("discipline", "")
            for c in circuit.connections
        }
        disc_by_disc: dict[tuple[str, Range | None], list[str]] = {}
        for port in circuit.ports:
            if port.discipline:
                key = (port.discipline, ranges[port.name])
                disc_by_disc.setdefault(key, []).append(port.name)
        for net, net_type in net_types.items():
            if net not in port_names and (net in internal or net_type):
                key = (net_type or "wire", internal.get(net))
                disc_by_disc.setdefault(key, []).append(net)
        for (disc, rng), names in disc_by_disc.items():
            lines.append(f"  {declaration(disc, names, rng)};")
        buses: Buses = {
            **{b: r for b, r in internal.items() if b not in port_names},
            **{n: r for n, r in ranges.items() if r is not None},
        }

        for param in circuit.parameters:
            is_local = param.properties.get("localparam") == "true"
            kw = "localparam" if is_local else "parameter"
            ptype = param.properties.get("type", "")
            val = self.format_param_value(param.default_value)
            type_str = f" {ptype}" if ptype else ""
            lines.append(f"  {kw}{type_str} {param.name} = {val};")

        ground_net = circuit.properties.get("ground_net")
        if ground_net:
            lines.append(f"  ground {ground_net};")

        inst_nets = connections_to_instance_nets(circuit.connections)

        for ref in circuit.subcircuits:
            lines.append(
                self.write_instance(ref, inst_nets, ext_by_name, circuit_by_name, buses)
            )

        analog_block = circuit.properties.get("analog_block")
        if analog_block:
            lines.append(f"  {analog_block}")

        lines.append("endmodule")

    def write_instance(
        self,
        ref: SubCircuit,
        inst_nets: dict[tuple[str, str], str],
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
        buses: Buses | None = None,
    ) -> str:
        params_str = ""
        if ref.parameters:
            param_parts = [
                f".{p.name}({self.format_param_value(p.default_value)})"
                for p in ref.parameters
                if p.default_value
            ]
            params_str = f" #({', '.join(param_parts)})"

        ref_circuit = circuit_by_name.get(ref.circuit_name)
        ext_circuit = ext_by_name.get(ref.circuit_name)
        target = ref_circuit or ext_circuit
        if target is not None:
            port_order = [
                (p.name, port_pins(p.name, p.width, p.properties.get("range")))
                for p in target.ports
            ]
        else:
            port_order = bus_pins(self.infer_port_order(ref, inst_nets))

        port_parts: list[str] = []
        for pn, pins in port_order:
            nets = [inst_nets.get((ref.name, pin)) for pin in pins]
            expr = connection_expr(f"{ref.name}.{pn}", nets, buses or {}, sv_name)
            port_parts.append(f".{pn}({expr})")
        ports_str = ", ".join(port_parts)

        return f"  {ref.circuit_name}{params_str} {sv_name(ref.name)} ({ports_str});"

    def format_param_value(self, pval: object) -> str:
        from kfnetlist.morphnet.morphnet_schema import ParameterValue

        if pval is None:
            return "0"
        if not isinstance(pval, ParameterValue):
            return str(pval)
        if pval.prefixed_value is not None:
            return format_si_value(pval.prefixed_value)
        return "0"

    def infer_port_order(
        self,
        ref: SubCircuit,
        inst_nets: dict[tuple[str, str], str],
    ) -> list[str]:
        port_names: list[str] = []
        for iname, pname in inst_nets:
            if iname == ref.name and pname not in port_names:
                port_names.append(pname)
        return port_names


def write_vams(netlist: Netlist) -> str:
    """Convert a Netlist model to Verilog-AMS netlist text."""
    return VamsWriter().write(netlist)
