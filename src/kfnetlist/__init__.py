"""Standalone netlist schema decoupled from kfactory's release cadence."""

from ._errors import LvsError
from ._native import (
    Net,
    Netlist,
    NetlistArray,
    NetlistInstance,
    NetlistPort,
    PortArrayRef,
    PortRef,
    exclude_from_rdb as exclude_from_rdb_xml,
    filter_rdb as filter_rdb_xml,
    include_from_rdb as include_from_rdb_xml,
)
from ._rdb import exclude_from_rdb, filter_rdb, include_from_rdb
from ._summary import error_summary
from .port_check import PortCheck, check_connection

__version__ = "0.1.4"

__all__ = [
    "LvsError",
    "Net",
    "Netlist",
    "NetlistArray",
    "NetlistInstance",
    "NetlistPort",
    "PortArrayRef",
    "PortCheck",
    "PortRef",
    "check_connection",
    "error_summary",
    "exclude_from_rdb",
    "exclude_from_rdb_xml",
    "filter_rdb",
    "filter_rdb_xml",
    "include_from_rdb",
    "include_from_rdb_xml",
]
