"""Standalone netlist schema decoupled from kfactory's release cadence."""

from ._native import (
    Net,
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    PortArrayRef,
    PortRef,
)

__version__ = "0.1.0"

__all__ = [
    "Net",
    "Netlist",
    "NetlistArray",
    "NetlistInstance",
    "NetlistPort",
    "PortArrayRef",
    "PortRef",
]
