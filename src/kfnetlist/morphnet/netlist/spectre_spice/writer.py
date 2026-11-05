from __future__ import annotations

from kfnetlist.morphnet.morphnet_schema import Netlist
from kfnetlist.morphnet.netlist.spice.writer import SpiceWriter


class SpectreSpiceWriter(SpiceWriter):
    """Convert a Netlist model to Spectre-SPICE netlist text.

    Outputs everything in SPICE syntax. HSPICE and Spectre-SPICE both
    accept standard .SUBCKT/.ENDS syntax.
    """


def write_spectre_spice(netlist: Netlist) -> str:
    """Convert a Netlist model to Spectre-SPICE netlist text."""
    return SpectreSpiceWriter().write(netlist)
