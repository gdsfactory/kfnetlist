from __future__ import annotations

from typing import Any

from kfnetlist.morphnet.netlist.simulation_data import AnalysisData
from kfnetlist.morphnet.netlist.spice.transformer import SpiceTransformer


class HspiceTransformer(SpiceTransformer):
    """Extend the SPICE transformer with HSPICE-specific handling.

    Additions:
    - .MACRO/.EOM treated as synonyms for .SUBCKT/.ENDS
    - .FFT analysis statement
    """

    dialect = "hspice"

    def macro_def(self, items: list[Any]) -> Any:
        return self.subckt_def(items)

    def fft_stmt(self, items: list[Any]) -> AnalysisData:
        args, opts = self._extract_sim_args(items)
        return AnalysisData(kind="fft", arguments=args, options=opts)
