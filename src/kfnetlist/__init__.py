"""Standalone netlist schema decoupled from kfactory's release cadence."""

from ._native import (
    Net,
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    Placement,
    PlacedInstance,
    PlacedNetlist,
    PortArrayRef,
    PortRef,
)
from .port_check import PortCheck, check_connection

__version__ = "0.2.1"

__all__ = [
    "Net",
    "Netlist",
    "NetlistArray",
    "NetlistInstance",
    "NetlistPort",
    "Placement",
    "PlacedInstance",
    "PlacedNetlist",
    "PortArrayRef",
    "PortCheck",
    "PortRef",
    "check_connection",
]
