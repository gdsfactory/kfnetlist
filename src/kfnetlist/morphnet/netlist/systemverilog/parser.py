from __future__ import annotations

from importlib.resources import files as resource_files
from typing import ClassVar

from lark import Lark
from lark.exceptions import VisitError

from kfnetlist.morphnet.morphnet_schema import Directive, DirectiveKind, Netlist
from kfnetlist.morphnet.netlist.systemverilog.preprocess import (
    preprocess_systemverilog,
)
from kfnetlist.morphnet.netlist.systemverilog.transformer import (
    SystemVerilogTransformer,
)
from kfnetlist.morphnet.netlist.vams.parser import DIRECTIVE_KIND_MAP


class SystemVerilogParser:
    """Parse structural SystemVerilog text into a Netlist model."""

    lark_instance: ClassVar[Lark | None] = None

    @classmethod
    def get_lark(cls) -> Lark:
        if cls.lark_instance is None:
            grammar_text = (
                resource_files("kfnetlist.morphnet.netlist.grammars")
                .joinpath("systemverilog.lark")
                .read_text(encoding="utf-8")
            )
            cls.lark_instance = Lark(grammar_text, parser="lalr")
        return cls.lark_instance

    @classmethod
    def parse(cls, text: str) -> Netlist:
        result = preprocess_systemverilog(text)
        directives: list[Directive] = []
        for kind_str, value in result.directives:
            dk = DIRECTIVE_KIND_MAP.get(kind_str, DirectiveKind.UNSPECIFIED)
            if dk == DirectiveKind.INCLUDE:
                value = value.strip("\"'")
            directives.append(Directive(kind=dk, value=value))
        tree = cls.get_lark().parse(result.text)
        try:
            return SystemVerilogTransformer(result.blocks, directives).transform(tree)
        except VisitError as e:
            raise e.orig_exc from None


def parse_systemverilog(text: str) -> Netlist:
    """Parse structural SystemVerilog text into a Netlist model.

    Terminals named ``o1``, ``o2``, ... are waveguide; all others are electrical.
    """
    return SystemVerilogParser.parse(text)
