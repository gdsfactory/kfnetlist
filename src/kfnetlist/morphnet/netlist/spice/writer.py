from __future__ import annotations

from collections.abc import Callable

from kfnetlist.morphnet.morphnet_schema import (
    Analysis,
    AnalysisKind,
    Netlist,
    Directive,
    DirectiveKind,
    Expression,
    ExternalCircuit,
    Measurement,
    Circuit,
    Parameter,
    SubCircuit,
    OutputRequest,
    OutputRequestKind,
    ParameterValue,
    Simulation,
)
from kfnetlist.morphnet.netlist.net_utils import connections_to_instance_nets
from kfnetlist.morphnet.netlist.stimulus import spice_text, stimulus_of
from kfnetlist.morphnet.netlist.value_utils import (
    DEVICE_PORT_TEMPLATES,
    DEVICE_PREFIX_TO_CIRCUIT,
    SPICE_LANGUAGES,
    format_si_value,
    is_skipped,
    macro_lines,
    param_text,
    sim_params,
)

# Reverse lookup: module name → SPICE device prefix letter — O(1) per instance
CIRCUIT_TO_PREFIX: dict[str, str] = {v: k for k, v in DEVICE_PREFIX_TO_CIRCUIT.items()}


class SpiceWriter:
    """Convert a Netlist model to SPICE netlist text.

    All lookups use dict-based O(1) access.
    """

    ground: str = ""
    netlist: Netlist  # the one being written
    # Keyword placed before subckt header / X-call params (Xyce: "PARAMS:")
    params_kw: str = ""
    dialect: str = "ngspice"  # expression wrapping (see format_expression)
    macro_languages = dict.fromkeys(SPICE_LANGUAGES)

    def format_param_value(self, pval: ParameterValue) -> str:
        """Format any ParameterValue variant as a SPICE-compatible string."""
        if pval.prefixed_value is not None:
            return format_si_value(pval.prefixed_value)
        return "0"

    def param_text(
        self,
        param: Parameter,
        named: bool = True,
        resolve: Callable[[str], Expression | None] | None = None,
    ) -> str | None:
        return param_text(param, self.format_param_value, self.dialect, named, resolve)

    def write(self, netlist: Netlist) -> str:
        lines: list[str] = []
        self.ground = netlist.properties.get("ground_net", "")
        self.netlist = netlist

        # Title line
        title = netlist.name or "untitled"
        lines.append(f"* {title}")

        # Build lookups — O(e + m)
        ext_by_name: dict[str, ExternalCircuit] = {
            e.name: e for e in netlist.ext_circuits
        }
        circuit_by_name: dict[str, Circuit] = {m.name: m for m in netlist.circuits}

        self.write_directives(netlist.directives, lines)
        lines.extend(macro_lines(netlist.macros, self.macro_languages, "*"))

        for ext in netlist.ext_circuits:
            model_type = ext.properties.get("model_type", "")
            if model_type:
                self.write_model(ext, model_type, lines)

        # Emit subcircuit definitions
        for circuit in netlist.circuits:
            if circuit.name == "__top__":
                self.write_top_instances(circuit, ext_by_name, circuit_by_name, lines)
            else:
                self.write_subckt(circuit, ext_by_name, circuit_by_name, lines)

        if netlist.simulation:
            self.write_simulation(netlist.simulation, lines)

        lines.append(".end")
        lines.append("")
        return "\n".join(lines)

    def write_directives(self, directives: list[Directive], lines: list[str]) -> None:
        for d in directives:
            if d.kind == DirectiveKind.INCLUDE:
                lines.append(f'.include "{d.value}"')
            elif d.kind == DirectiveKind.LIB:
                lines.append(f".lib {d.value}")
            elif d.kind == DirectiveKind.GLOBAL:
                lines.append(f".global {d.value}")
            elif d.kind == DirectiveKind.OPTION:
                lines.append(f".option {d.name}={d.value}")
            elif d.kind == DirectiveKind.PARAM:
                lines.append(f".param {d.name}={d.value}")

    def write_model(
        self,
        ext: ExternalCircuit,
        model_type: str,
        lines: list[str],
    ) -> None:
        """Emit a .model statement."""
        param_strs: list[str] = []
        for p in ext.parameters:
            text = self.param_text(p)
            if text is not None:
                param_strs.append(f"{p.name}={text}")
        params_text = " ".join(param_strs)
        if params_text:
            lines.append(f".model {ext.name} {model_type} {params_text}")
        else:
            lines.append(f".model {ext.name} {model_type}")

    def write_subckt(
        self,
        circuit: Circuit,
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
        lines: list[str],
    ) -> None:
        """Emit a .subckt / .ends block."""
        port_names = " ".join(p.name for p in circuit.ports)
        header = [f".subckt {circuit.name}", port_names]
        kv = [
            f"{p.name}={t}"
            for p in circuit.parameters
            if (t := self.param_text(p)) is not None
        ]
        if kv and self.params_kw:
            header.append(self.params_kw)
        header.extend(kv)
        lines.append(" ".join(h for h in header if h))
        lines.extend(macro_lines(circuit.macros, self.macro_languages, "*"))
        lines.extend(self.instance_lines(circuit, ext_by_name, circuit_by_name))
        lines.append(f".ends {circuit.name}")

    def write_top_instances(
        self,
        circuit: Circuit,
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
        lines: list[str],
    ) -> None:
        """Emit top-level instances (outside any subcircuit)."""
        lines.extend(macro_lines(circuit.macros, self.macro_languages, "*"))
        lines.extend(self.instance_lines(circuit, ext_by_name, circuit_by_name))

    def instance_lines(
        self,
        circuit: Circuit,
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
    ) -> list[str]:
        # Build (instance_name, port_name) → net_name — O(c)
        inst_nets = connections_to_instance_nets(circuit.connections, self.ground)
        return [
            self.write_instance(ref, inst_nets, ext_by_name, circuit_by_name)
            for ref in circuit.subcircuits
            if not is_skipped(ref)
        ]

    def out_name(
        self,
        ref: SubCircuit,
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
    ) -> str:
        """Instance name with its SPICE device letter prepended when missing."""
        if ref.circuit_name in circuit_by_name:
            letter = "X"
        else:
            ext = ext_by_name.get(ref.circuit_name)
            letter = ext.properties.get("spice_prefix", "") if ext else ""
        if letter and not ref.name.lower().startswith(letter.lower()):
            return letter + ref.name
        return ref.name

    def write_instance(
        self,
        ref: SubCircuit,
        inst_nets: dict[tuple[str, str], str],
        ext_by_name: dict[str, ExternalCircuit],
        circuit_by_name: dict[str, Circuit],
    ) -> str:
        """Emit a single instance line.

        Device prefix and port order determined by O(1) dict lookups.
        """
        prefix = CIRCUIT_TO_PREFIX.get(ref.circuit_name)
        ext_circuit = ext_by_name.get(ref.circuit_name)

        params, resolve = sim_params(ref)
        if prefix:
            # Primitive device: R1 net1 net2 value param=val ...
            inst_name = ref.name
            out_name = self.out_name(ref, ext_by_name, circuit_by_name)
            port_order = (
                [p.name for p in ext_circuit.ports]
                if ext_circuit
                else DEVICE_PORT_TEMPLATES[prefix]
            )
            nets = [inst_nets.get((inst_name, pn), "?") for pn in port_order]
            nets_str = " ".join(nets)

            model_name = ref.properties.get("model_name", "")
            value_str = ""
            other_params: list[str] = []
            for param in params:
                positional = param.name == "value"
                text = self.param_text(param, not positional, resolve)
                if text is None:
                    continue
                if positional:
                    value_str = text
                else:
                    other_params.append(f"{param.name}={text}")

            stim = stimulus_of(self.netlist, ref)
            if stim is not None:
                value_str = spice_text(stim, self.dialect)
            parts = [out_name, nets_str]
            if model_name:
                parts.append(model_name)
            if value_str:
                parts.append(value_str)
            parts.extend(other_params)
            return " ".join(parts)

        # Subcircuit instance: X1 net1 net2 ... subckt_name param=val
        inst_name = ref.name
        subckt_name = ref.circuit_name

        ref_circuit = circuit_by_name.get(subckt_name)
        if ref_circuit is not None:
            port_order = [p.name for p in ref_circuit.ports]
        elif ext_circuit is not None:
            port_order = [p.name for p in ext_circuit.ports]
        else:
            port_order = self.infer_port_order(ref, inst_nets)

        nets = [inst_nets.get((inst_name, pn), "?") for pn in port_order]
        nets_str = " ".join(nets)

        params_parts = [
            f"{p.name}={text}"
            for p in params
            if (text := self.param_text(p, resolve=resolve)) is not None
        ]
        out_name = self.out_name(ref, ext_by_name, circuit_by_name)
        parts = [out_name, nets_str, subckt_name]
        if params_parts and self.params_kw and out_name[:1].upper() == "X":
            parts.append(self.params_kw)
        parts.extend(params_parts)
        return " ".join(parts)

    def infer_port_order(
        self,
        ref: SubCircuit,
        inst_nets: dict[tuple[str, str], str],
    ) -> list[str]:
        """Infer port order from the instance-net map when no circuit definition is available."""
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
        for meas in simulation.measurements:
            lines.append(self.format_measurement(meas))
        if simulation.initial_conditions:
            assigns = " ".join(
                f"{k}={v}" for k, v in simulation.initial_conditions.conditions.items()
            )
            lines.append(f".ic {assigns}")
        if simulation.node_sets:
            assigns = " ".join(
                f"{k}={v}" for k, v in simulation.node_sets.conditions.items()
            )
            lines.append(f".nodeset {assigns}")
        if simulation.temperatures:
            temps = " ".join(str(t) for t in simulation.temperatures)
            lines.append(f".temp {temps}")

    def format_analysis(self, analysis: Analysis) -> str:
        keyword = _ANALYSIS_KIND_TO_KW.get(analysis.kind, ".op")
        parts = [keyword]
        parts.extend(analysis.arguments)
        for k, v in analysis.options.items():
            parts.append(f"{k}={v}")
        return " ".join(parts)

    def format_output_request(self, req: OutputRequest) -> str:
        keyword = _OUTPUT_REQUEST_KIND_TO_KW.get(req.kind, ".print")
        parts = [keyword]
        if req.analysis_type:
            parts.append(req.analysis_type)
        parts.extend(req.variables)
        return " ".join(parts)

    def format_measurement(self, meas: Measurement) -> str:
        parts = [".meas"]
        if meas.analysis_type:
            parts.append(meas.analysis_type)
        if meas.name:
            parts.append(meas.name)
        if meas.body:
            parts.append(meas.body)
        return " ".join(parts)


_ANALYSIS_KIND_TO_KW: dict[AnalysisKind, str] = {
    AnalysisKind.OP: ".op",
    AnalysisKind.DC: ".dc",
    AnalysisKind.AC: ".ac",
    AnalysisKind.TRAN: ".tran",
    AnalysisKind.NOISE: ".noise",
    AnalysisKind.TF: ".tf",
    AnalysisKind.SENS: ".sens",
    AnalysisKind.PZ: ".pz",
    AnalysisKind.DISTO: ".disto",
    AnalysisKind.FOUR: ".four",
    AnalysisKind.FFT: ".fft",
}

_OUTPUT_REQUEST_KIND_TO_KW: dict[OutputRequestKind, str] = {
    OutputRequestKind.PRINT: ".print",
    OutputRequestKind.PLOT: ".plot",
    OutputRequestKind.PROBE: ".probe",
    OutputRequestKind.SAVE: "save",
}


def write_spice(netlist: Netlist) -> str:
    """Convert a Netlist model to SPICE netlist text."""
    return SpiceWriter().write(netlist)
