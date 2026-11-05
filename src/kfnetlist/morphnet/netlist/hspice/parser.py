from __future__ import annotations

from importlib.resources import files as resource_files
from typing import ClassVar

from lark import Lark

from kfnetlist.morphnet.morphnet_schema import Netlist
from kfnetlist.morphnet.netlist.hspice.preprocess import preprocess_hspice
from kfnetlist.morphnet.netlist.hspice.transformer import HspiceTransformer


class HspiceParser:
    """Parse HSPICE netlist text into a Netlist model.

    Extends SpiceParser with HSPICE grammar and preprocessor.
    """

    lark_instance: ClassVar[Lark | None] = None

    @classmethod
    def get_lark(cls) -> Lark:
        if cls.lark_instance is None:
            grammar_text = (
                resource_files("kfnetlist.morphnet.netlist.grammars")
                .joinpath("hspice.lark")
                .read_text(encoding="utf-8")
            )
            cls.lark_instance = Lark(grammar_text, parser="earley", ambiguity="resolve")
        return cls.lark_instance

    @classmethod
    def parse(cls, text: str) -> Netlist:
        cleaned = preprocess_hspice(text)
        lark = cls.get_lark()
        tree = lark.parse(cleaned)
        transformer = HspiceTransformer()
        netlist = transformer.transform(tree)
        return Netlist(
            name=netlist.name,
            top_circuit=netlist.top_circuit,
            circuits=netlist.circuits,
            ext_modules=netlist.ext_modules,
            directives=netlist.directives,
            simulation=netlist.simulation,
        )


def parse_hspice(text: str) -> Netlist:
    """Parse HSPICE netlist text into a Netlist model."""
    return HspiceParser.parse(text)
