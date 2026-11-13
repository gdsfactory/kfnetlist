"""Backward-compatible re-exports — use per-format modules directly."""

from kfnetlist.morphnet.netlist.hspice.preprocess import preprocess_hspice
from kfnetlist.morphnet.netlist.spectre.preprocess import preprocess_spectre
from kfnetlist.morphnet.netlist.spectre_spice.preprocess import preprocess_spectre_spice
from kfnetlist.morphnet.netlist.spice.preprocess import preprocess_spice
from kfnetlist.morphnet.netlist.systemverilog.preprocess import (
    preprocess_systemverilog,
)
from kfnetlist.morphnet.netlist.vams.preprocess import preprocess_vams
from kfnetlist.morphnet.netlist.xyce.preprocess import preprocess_xyce

__all__ = [
    "preprocess_hspice",
    "preprocess_spectre",
    "preprocess_spectre_spice",
    "preprocess_spice",
    "preprocess_systemverilog",
    "preprocess_vams",
    "preprocess_xyce",
]
