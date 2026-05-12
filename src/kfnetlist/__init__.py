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
from .port_check import PortCheck, check_connection

__version__ = "0.1.2"

__all__ = [
    "Net",
    "Netlist",
    "NetlistArray",
    "NetlistInstance",
    "NetlistPort",
    "PortArrayRef",
    "PortCheck",
    "PortRef",
    "check_connection",
]
