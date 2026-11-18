from __future__ import annotations

from kfnetlist.morphnet.morphnet_schema import Netlist, ParameterValue
from kfnetlist.morphnet.netlist.spice.writer import SpiceWriter


class XyceWriter(SpiceWriter):
    """Convert a Netlist model to Xyce netlist text.

    Xyce output is structurally identical to SPICE — the only difference
    is the PARAMS: keyword Xyce requires before parameters on .SUBCKT lines
    and on X (subcircuit call) lines.
    """

    params_kw = "PARAMS:"

    def format_param_value(self, pval: ParameterValue) -> str:
        return super().format_param_value(pval)


def write_xyce(netlist: Netlist) -> str:
    """Convert a Netlist model to Xyce netlist text."""
    return XyceWriter().write(netlist)
