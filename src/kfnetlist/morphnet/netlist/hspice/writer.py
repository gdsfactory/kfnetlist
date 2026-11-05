from __future__ import annotations

from kfnetlist.morphnet.morphnet_schema import Netlist
from kfnetlist.morphnet.netlist.spice.writer import SpiceWriter


class HspiceWriter(SpiceWriter):
    """Convert a Netlist model to HSPICE netlist text.

    HSPICE output is structurally identical to generic SPICE.
    Expressions are output in single quotes by the base format_param_value.
    """


def write_hspice(netlist: Netlist) -> str:
    """Convert a Netlist model to HSPICE netlist text."""
    return HspiceWriter().write(netlist)
