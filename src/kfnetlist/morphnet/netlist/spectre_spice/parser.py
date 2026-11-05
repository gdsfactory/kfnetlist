from __future__ import annotations

from kfnetlist.morphnet.morphnet_schema import (
    Analysis,
    Netlist,
    ExternalModule,
    InitialCondition,
    Measurement,
    Circuit,
    OutputRequest,
    Simulation,
)
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.spectre_spice.preprocess import preprocess_spectre_spice
from kfnetlist.morphnet.netlist.spice.parser import parse_spice


class SpectreSpiceParser:
    """Parse Spectre-SPICE netlist text into a Netlist model.

    Splits input on `simulator lang=` directives and delegates each
    section to the appropriate sub-parser.
    """

    @classmethod
    def parse(cls, text: str) -> Netlist:
        sections = preprocess_spectre_spice(text)

        all_circuits: list[Circuit] = []
        all_ext_modules: dict[str, ExternalModule] = {}
        all_directives = []
        all_analyses: list[Analysis] = []
        all_output_requests: list[OutputRequest] = []
        all_measurements: list[Measurement] = []
        all_temperatures: list[float] = []
        ic_conditions: dict[str, str] = {}
        ns_conditions: dict[str, str] = {}

        for section in sections:
            if not section.text.strip():
                continue
            if section.language == "spectre":
                netlist = parse_spectre(section.text)
            else:
                netlist = parse_spice(section.text)

            all_circuits.extend(netlist.circuits)
            for ext in netlist.ext_modules:
                all_ext_modules[ext.name] = ext
            all_directives.extend(netlist.directives)

            if netlist.simulation:
                all_analyses.extend(netlist.simulation.analyses)
                all_output_requests.extend(netlist.simulation.output_requests)
                all_measurements.extend(netlist.simulation.measurements)
                all_temperatures.extend(netlist.simulation.temperatures)
                if netlist.simulation.initial_conditions:
                    ic_conditions.update(
                        netlist.simulation.initial_conditions.conditions
                    )
                if netlist.simulation.node_sets:
                    ns_conditions.update(netlist.simulation.node_sets.conditions)

        top_circuit = all_circuits[-1].name if all_circuits else ""

        has_sim = (
            all_analyses
            or all_output_requests
            or all_measurements
            or ic_conditions
            or ns_conditions
            or all_temperatures
        )
        simulation: Simulation | None = None
        if has_sim:
            simulation = Simulation(
                analyses=all_analyses,
                output_requests=all_output_requests,
                measurements=all_measurements,
                initial_conditions=(
                    InitialCondition(conditions=ic_conditions)
                    if ic_conditions
                    else None
                ),
                node_sets=(
                    InitialCondition(conditions=ns_conditions)
                    if ns_conditions
                    else None
                ),
                temperatures=all_temperatures,
            )

        return Netlist(
            name="",
            top_circuit=top_circuit,
            circuits=all_circuits,
            ext_modules=list(all_ext_modules.values()),
            directives=all_directives,
            simulation=simulation,
        )


def parse_spectre_spice(text: str) -> Netlist:
    """Parse Spectre-SPICE netlist text into a Netlist model."""
    return SpectreSpiceParser.parse(text)
