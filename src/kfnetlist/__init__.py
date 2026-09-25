"""Standalone netlist schema decoupled from kfactory's release cadence."""

from ._flatten import flatten_netlists
from ._native import (
    HierarchicalNetlist,
    LeafNetlistInstance,
    Net,
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    PlacedInstance,
    PlacedNetlist,
    Placement,
    PortArrayRef,
    PortRef,
    RefNetlistInstance,
    hierarchy_from_json,
    validate_hierarchy,
)
from .port_check import PortCheck, check_connection

__version__ = "0.3.0"

__all__ = [
    "HierarchicalNetlist",
    "LeafNetlistInstance",
    "Net",
    "Netlist",
    "NetlistArray",
    "NetlistInstance",
    "NetlistPort",
    "PlacedInstance",
    "PlacedNetlist",
    "Placement",
    "PortArrayRef",
    "PortCheck",
    "PortRef",
    "RefNetlistInstance",
    "check_connection",
    "flatten_netlists",
    "hierarchy_from_json",
    "validate_hierarchy",
]
