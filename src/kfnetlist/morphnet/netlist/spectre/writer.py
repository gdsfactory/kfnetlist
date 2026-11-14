from __future__ import annotations

from kfnetlist.morphnet.morphnet_schema import (
    Analysis,
    AnalysisKind,
    Netlist,
    Directive,
    DirectiveKind,
    ExternalCircuit,
    Circuit,
    SubCircuit,
    OutputRequest,
    OutputRequestKind,
    ParameterValue,
    Simulation,
)
from kfnetlist.morphnet.netlist.net_utils import connections_to_instance_nets
from kfnetlist.morphnet.netlist.value_utils import (
    DEVICE_PORT_TEMPLATES,
    DEVICE_PREFIX_TO_CIRCUIT,
    format_si_value,
)

CIRCUIT_TO_PREFIX: dict[str, str] = {v: k for k, v in DEVICE_PREFIX_TO_CIRCUIT.items()}


class SpectreWriter:
    """Convert a Netlist model to Spectre netlist text."""

    def format_param_value(self, pval: ParameterValue) -> str:
        """Format any ParameterValue variant as a Spectre-compatible string."""
        if pval.prefixed_value is not None:
            return format_si_value(pval.prefixed_value)
        return "0"

    def write(self, netlist: Netlist) -> str:
        lines: list[str] = []

        ext_by_name: dict[str, ExternalCircuit] = {
            e.name: e for e in netlist.ext_circuits
        }
        circuit_by_name: dict[str, Circuit] = {m.name: m for m in netlist.circuits}

        self.write_directives(netlist.directives, lines)

        for ext in netlist.ext_circuits:
            model_type = ext.properties.get("model_type")
            if model_type:
                self.write_model(ext, model_type, lines)

        for circuit in netlist.circuits:
            if circuit.name == "__top__":
                self.write_top_instances(circuit, ext_by_name, circuit_by_name, lines)
            else:
                self.write_subckt(circuit, ext_by_name, circuit_by_name, lines)

        if netlist.simulation:
            self.write_simulation(netlist.simulation, lines)

        lines.append("")
        return "\n".join(lines)

    def write_directives(self, directives: list[Directive], lines: list[str]) -> None:
        params: dict[str, str] = {}
        for d in directives:
            if d.kind == DirectiveKind.INCLUDE:
                lines.append(f'include "{d.value}"')
            elif d.kind == DirectiveKind.PARAM:
                params[d.name] = d.value
        if params:
            assigns = " ".join(f"{k}={v}" for k, v in params.items())
            lines.append(f"parameters {assigns}")

    def write_model(
        self, ext: ExternalCircuit, model_type: str, lines: list[str]
    ) -> None:
        param_strs: list[str] = []
        for p in ext.parameters:
            if p.default_value:
                param_strs.append(
                    f"{p.name}={self.format_param_value(p.default_value)}"
                )
        params_text = " ".join(param_strs)
        lines.append(f"model {ext.name} {model_type} ({params_text})")

    def write_subckt(
        self,
        circuit: Circuit,
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
        lines: list[str],
    ) -> None:
        port_names = " ".join(p.name for p in circuit.ports)

        param_strs: list[str] = []
        for param in circuit.parameters:
            if param.default_value:
                param_strs.append(
                    f"{param.name}={self.format_param_value(param.default_value)}"
                )
        params_suffix = " " + " ".join(param_strs) if param_strs else ""

        lines.append(f"subckt {circuit.name} ({port_names}){params_suffix}")

        inst_nets = connections_to_instance_nets(circuit.connections)

        for ref in circuit.subcircuits:
            lines.append(
                self.write_instance(ref, inst_nets, ext_by_name, circuit_by_name)
            )

        lines.append(f"ends {circuit.name}")

    def write_top_instances(
        self,
        circuit: Circuit,
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
        lines: list[str],
    ) -> None:
        inst_nets = connections_to_instance_nets(circuit.connections)
        for ref in circuit.subcircuits:
            lines.append(
                self.write_instance(ref, inst_nets, ext_by_name, circuit_by_name)
            )

    def write_instance(
        self,
        ref: SubCircuit,
        inst_nets: dict[tuple[str, str], str],
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
    ) -> str:
        ext_circuit = ext_by_name.get(ref.circuit_name)
        prefix = CIRCUIT_TO_PREFIX.get(ref.circuit_name)

        # Determine port order
        if prefix and ext_circuit:
            port_order = [p.name for p in ext_circuit.ports]
        else:
            ref_circuit = circuit_by_name.get(ref.circuit_name)
            if ref_circuit:
                port_order = [p.name for p in ref_circuit.ports]
            elif ext_circuit:
                port_order = [p.name for p in ext_circuit.ports]
            elif prefix and all(
                (ref.name, pn) in inst_nets for pn in DEVICE_PORT_TEMPLATES[prefix]
            ):
                port_order = DEVICE_PORT_TEMPLATES[prefix]
            else:
                port_order = self.infer_port_order(ref, inst_nets)

        nets = [inst_nets.get((ref.name, pn), "?") for pn in port_order]
        nets_str = " ".join(nets)

        cell_name = ref.properties.get("model_name") or ref.circuit_name

        # Params
        param_strs: list[str] = []
        for param in ref.parameters:
            if param.default_value:
                param_strs.append(
                    f"{param.name}={self.format_param_value(param.default_value)}"
                )

        params_text = " " + " ".join(param_strs) if param_strs else ""
        return f"{ref.name} ({nets_str}) {cell_name}{params_text}"

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

    # ── Simulation writing ──────────────────────────────────────────────

    def write_simulation(self, simulation: Simulation, lines: list[str]) -> None:
        for analysis in simulation.analyses:
            lines.append(self.format_analysis(analysis))
        for req in simulation.output_requests:
            lines.append(self.format_output_request(req))

    def format_analysis(self, analysis: Analysis) -> str:
        keyword = _ANALYSIS_KIND_TO_SPECTRE.get(analysis.kind, "dc")
        parts = [analysis.name or keyword, keyword]
        for k, v in analysis.options.items():
            parts.append(f"{k}={v}")
        return " ".join(parts)

    def format_output_request(self, req: OutputRequest) -> str:
        if req.kind == OutputRequestKind.SAVE:
            return "save " + " ".join(req.variables)
        return "save " + " ".join(req.variables)


_ANALYSIS_KIND_TO_SPECTRE: dict[AnalysisKind, str] = {
    AnalysisKind.OP: "op",
    AnalysisKind.DC: "dc",
    AnalysisKind.AC: "ac",
    AnalysisKind.TRAN: "tran",
    AnalysisKind.NOISE: "noise",
}


def write_spectre(netlist: Netlist) -> str:
    """Convert a Netlist model to Spectre netlist text."""
    return SpectreWriter().write(netlist)
