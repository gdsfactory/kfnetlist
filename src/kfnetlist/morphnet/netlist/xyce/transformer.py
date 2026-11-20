from __future__ import annotations

from typing import Any

from lark import Token

from kfnetlist.morphnet.netlist.simulation_data import OutputRequestData
from kfnetlist.morphnet.netlist.spice.transformer import SpiceTransformer


class XyceTransformer(SpiceTransformer):
    """Extend the SPICE transformer with Xyce-specific handling.

    Additions:
    - {expression} blocks in tokens.
    - PARAMS: keyword in .SUBCKT (consumed by grammar, no transformer change needed).
    """

    dialect = "xyce"

    def token_expr(self, items: list[Token]) -> Token:
        return items[0]

    def params_kw(self, items: list[Any]) -> None:
        return None

    def instance_stmt(self, items: list[Any]) -> Any:
        # `X1 a b sub PARAMS: w=2`: the keyword is not a net or the subckt name
        items = [
            i
            for i in items
            if not (isinstance(i, Token) and str(i).upper() == "PARAMS:")
        ]
        return super().instance_stmt(items)

    def print_stmt(self, items: list[Any]) -> OutputRequestData:
        tokens = [
            str(t) for t in items if isinstance(t, Token) and not str(t).startswith(".")
        ]
        analysis_type = tokens[0] if tokens else ""
        variables = tokens[1:]
        return OutputRequestData(
            kind="print", analysis_type=analysis_type, variables=variables
        )
