from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files as resource_files
from typing import ClassVar

from lark import Lark
from lark.exceptions import VisitError

from kfnetlist.morphnet.morphnet_schema import (
    Directive,
    DirectiveKind,
    Netlist,
    SignalDomain,
)
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
    def parse(
        cls,
        text: str,
        defines: Mapping[str, str] | None = None,
        disciplines: Mapping[str, SignalDomain] | None = None,
    ) -> Netlist:
        result = preprocess_systemverilog(text, defines)
        directives: list[Directive] = []
        for kind_str, value in result.directives:
            dk = DIRECTIVE_KIND_MAP.get(kind_str, DirectiveKind.UNSPECIFIED)
            if dk == DirectiveKind.INCLUDE:
                value = value.strip("\"'")
            directives.append(Directive(kind=dk, value=value))
        tree = cls.get_lark().parse(result.text)
        try:
            return SystemVerilogTransformer(
                result.blocks, directives, disciplines
            ).transform(tree)
        except VisitError as e:
            raise e.orig_exc from None


def parse_systemverilog(
    text: str,
    defines: Mapping[str, str] | None = None,
    disciplines: Mapping[str, SignalDomain] | None = None,
) -> Netlist:
    """Parse structural SystemVerilog text into a Netlist model.

    Nets are bit level: a bus port ``input [3:0] in`` is one ``Port`` with
    ``width=4`` whose bits ``in[3]`` … ``in[0]`` are the net members, so a
    bit-select ``.a(in[0])`` meets the port. Instance arrays ``X I[3:0] (...)``
    expand to instances ``I[3]`` … ``I[0]``. Width mismatches and selects of
    undeclared buses raise ``ValueError``.

    Args:
        text: SystemVerilog source.
        defines: Predefined macros for `` `ifdef `` (``{"IS_SIM": "1"}``). With
            none, the `` `else `` branches are taken.
        disciplines: Port/net type -> domain, e.g. ``{"connection":
            SignalDomain.WAVEGUIDE}``. A net touching a typed waveguide port is
            waveguide, as are the other terminals on it. Untyped terminals
            named ``o1``, ``o2``, ... are waveguide; all others are electrical.
            Types often exist only in a simulation view (`` `ifdef IS_SIM``):
            pass the matching ``defines``, or every port is a plain ``wire``.
    """
    return SystemVerilogParser.parse(text, defines, disciplines)
