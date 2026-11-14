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
from kfnetlist.morphnet.netlist.net_utils import PinDomains
from kfnetlist.morphnet.netlist.vams.preprocess import preprocess_vams
from kfnetlist.morphnet.netlist.vams.transformer import VamsTransformer

DIRECTIVE_KIND_MAP: dict[str, DirectiveKind] = {
    "include": DirectiveKind.INCLUDE,
    "define": DirectiveKind.DEFINE,
    "timescale": DirectiveKind.TIMESCALE,
}


class VamsParser:
    """Parse Verilog-AMS netlist text into a Netlist model."""

    lark_instance: ClassVar[Lark | None] = None

    @classmethod
    def get_lark(cls) -> Lark:
        if cls.lark_instance is None:
            grammar_text = (
                resource_files("kfnetlist.morphnet.netlist.grammars")
                .joinpath("vams.lark")
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
        pin_domains: PinDomains | None = None,
    ) -> Netlist:
        result = preprocess_vams(text, defines)
        lark = cls.get_lark()
        tree = lark.parse(result.text)
        transformer = VamsTransformer(result.analog_blocks, disciplines, pin_domains)
        try:
            netlist = transformer.transform(tree)
        except VisitError as e:
            raise e.orig_exc from None

        directives: list[Directive] = []
        for kind_str, value in result.directives:
            dk = DIRECTIVE_KIND_MAP.get(kind_str, DirectiveKind.UNSPECIFIED)
            if dk == DirectiveKind.INCLUDE:
                value = value.strip("\"'")
            directives.append(Directive(kind=dk, value=value))

        if directives:
            netlist = Netlist(
                name=netlist.name,
                top_circuit=netlist.top_circuit,
                circuits=netlist.circuits,
                ext_circuits=netlist.ext_circuits,
                properties=netlist.properties,
                directives=directives,
            )

        return netlist


def parse_vams(
    text: str,
    defines: Mapping[str, str] | None = None,
    disciplines: Mapping[str, SignalDomain] | None = None,
    pin_domains: PinDomains | None = None,
) -> Netlist:
    """Parse Verilog-AMS netlist text into a Netlist model.

    Nets are bit level, as in ``parse_systemverilog``: a bus ``input [3:0] in;``
    is one ``Port`` with ``width=4`` whose bits ``in[3]`` … ``in[0]`` are the
    net members, and instance arrays ``X I[3:0] (...)`` expand to ``I[3]`` …
    ``I[0]``. Width mismatches and selects of undeclared buses raise ``ValueError``.

    Args:
        text: Verilog-AMS source.
        defines: Predefined macros for `` `ifdef ``; with none, the `` `else ``
            branches are taken.
        disciplines: Discipline -> domain, e.g. ``{"optical":
            SignalDomain.WAVEGUIDE}``. A net touching a waveguide port or net is
            waveguide; untyped terminals named ``o1``, ``o2``, ... are waveguide.
        pin_domains: Cell -> pin -> domain for leaf cells, e.g. ``{"MZM_1X2":
            {"in0": SignalDomain.WAVEGUIDE}}``; see ``parse_systemverilog``.
    """
    return VamsParser.parse(text, defines, disciplines, pin_domains)
