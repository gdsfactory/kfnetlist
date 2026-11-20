"""Parse and print parameter expressions (the schema's ``Expression`` tree).

``parse_expression`` reads any dialect's expression text with one shared grammar
(``grammars/expression.lark``); ``format_expression`` prints the canonical infix text
(``0.13 * 1e-6``), wrapped as the dialect wants it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import cache
from importlib.resources import files as resource_files

from lark import Lark, Token, Transformer
from lark.exceptions import LarkError

from kfnetlist.morphnet.morphnet_schema import (
    BinaryOp,
    Call,
    Expression,
    Operator,
    ParameterValue,
    PrefixedValue,
    SIPrefix,
    Ternary,
    UnaryOp,
)
from kfnetlist.morphnet.netlist.value_utils import (
    format_si_value,
    is_si_number,
    parse_parameter_number,
    parse_si_number,
    to_float,
)

__all__ = ["format_expression", "parameter_value", "parse_expression", "value_text"]

# A netlist identifier (the SPICE/Spectre IDENT token): a bare reference by name.
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.\[\]:!#]*")
WORD_RE = re.compile(r"\b[A-Za-z_]\w*", re.ASCII)  # what nyancad substitutes in text

# Dialect -> (open, close) around a compound expression.
WRAP: dict[str, tuple[str, str]] = {
    "ngspice": ("{", "}"),
    "xyce": ("{", "}"),
    "hspice": ("'", "'"),
    "spectre": ("", ""),
    "vacask": ("", ""),
    "systemverilog": ("", ""),
    "vams": ("", ""),
    "gsch": ("", ""),
}
SYMBOL = {
    Operator.OR: "||",
    Operator.AND: "&&",
    Operator.EQ: "==",
    Operator.NE: "!=",
    Operator.LT: "<",
    Operator.LE: "<=",
    Operator.GT: ">",
    Operator.GE: ">=",
    Operator.ADD: "+",
    Operator.SUB: "-",
    Operator.MUL: "*",
    Operator.DIV: "/",
    Operator.MOD: "%",
    Operator.POW: "**",
    Operator.NEG: "-",
    Operator.NOT: "!",
}
# Binding strength of a printed node; raw text inside a tree is always parenthesised.
RAW, TERNARY, UNARY, CALL, ATOM = -1, 0, 7, 9, 10
PREC = {
    **dict.fromkeys([Operator.OR], 1),
    **dict.fromkeys([Operator.AND], 2),
    **dict.fromkeys([Operator.EQ, Operator.NE], 3),
    **dict.fromkeys([Operator.LT, Operator.LE, Operator.GT, Operator.GE], 4),
    **dict.fromkeys([Operator.ADD, Operator.SUB], 5),
    **dict.fromkeys([Operator.MUL, Operator.DIV, Operator.MOD], 6),
    Operator.POW: 8,
}

Resolve = Callable[[str], Expression | None]


class _Build(Transformer):
    """Grammar tree -> ``Expression``; rule aliases are lowercase ``Operator`` names."""

    def literal(self, children: list[Token]) -> Expression:
        return Expression(literal=parse_si_number(children[0]))

    def reference(self, children: list[Token]) -> Expression:
        return Expression(reference=str(children[0]))

    def call(self, children: list) -> Expression:
        return Expression(call=Call(name=str(children[0]), args=children[1:]))

    def ternary(self, children: list[Expression]) -> Expression:
        cond, then, otherwise = children
        return Expression(ternary=Ternary(cond=cond, then=then, otherwise=otherwise))

    def __default__(self, data: str, children: list, meta: object) -> Expression:
        op = Operator[data.upper()]
        if op in (Operator.NEG, Operator.NOT):
            return Expression(unary=UnaryOp(op=op, operand=children[0]))
        lhs, rhs = children
        return Expression(binary=BinaryOp(op=op, lhs=lhs, rhs=rhs))


@cache
def _parser() -> Lark:
    grammar = (
        resource_files("kfnetlist.morphnet.netlist.grammars")
        .joinpath("expression.lark")
        .read_text(encoding="utf-8")
    )
    return Lark(grammar, parser="lalr")


def parse_expression(text: str) -> Expression:
    """The expression tree of ``text``; ``Expression(raw=text)`` when it does not parse.

    One outer ``{…}`` or ``'…'`` (SPICE dialect wrapping) is stripped first. Never raises.
    """
    body = text.strip()
    if len(body) >= 2 and (body[0], body[-1]) in (("{", "}"), ("'", "'")):
        body = body[1:-1]
    try:
        return _Build().transform(_parser().parse(body))
    except (LarkError, ValueError, RecursionError):
        return Expression(raw=text)


def parameter_value(text: str) -> ParameterValue:
    """A number's ``prefixed_value``; an identifier's ``reference``; else the
    expression tree of ``text`` (``raw`` when it does not parse)."""
    if is_si_number(text):
        return parse_parameter_number(text)
    if IDENT_RE.fullmatch(text):
        return ParameterValue(expression=Expression(reference=text))
    return ParameterValue(expression=parse_expression(text))


def value_text(value: ParameterValue, dialect: str) -> str:
    """``value`` as the text of a ``k=v`` directive in ``dialect``; "" when empty."""
    if value.prefixed_value is not None:
        return format_si_value(value.prefixed_value)
    if value.expression is not None:
        return format_expression(value.expression, dialect, named=True)
    return ""


def _number(pv: PrefixedValue, dialect: str) -> str:
    """nyancad's spelling: SI suffix kept, else the shortest repr (``1e-6``, ``2``)."""
    if pv.prefix != SIPrefix.UNSPECIFIED and dialect != "systemverilog":
        return format_si_value(pv)  # SystemVerilog has no SI suffixes
    value = to_float(pv)
    text = repr(value) if pv.prefix == SIPrefix.UNSPECIFIED else f"{value:.12g}"
    mantissa, e, exponent = text.removesuffix(".0").partition("e")
    return f"{mantissa}e{int(exponent)}" if e else mantissa


def _text(expr: Expression, dialect: str, resolve: Resolve | None) -> tuple[str, int]:
    """Printed ``expr`` and its binding strength."""
    if expr.reference is not None:
        sub = resolve(expr.reference) if resolve else None
        if sub is not None:  # once, like nyancad's textual substitution
            return _text(sub, dialect, None)
        return expr.reference, ATOM
    if expr.literal is not None:
        return _number(expr.literal, dialect), ATOM
    if expr.call is not None:
        args = (_text(a, dialect, resolve)[0] for a in expr.call.args)
        return f"{expr.call.name}({', '.join(args)})", CALL

    def part(sub: Expression | None, needs_parens: Callable[[int], bool]) -> str:
        text, prec = _text(sub or Expression(raw=""), dialect, resolve)
        return f"({text})" if needs_parens(prec) else text

    if expr.unary is not None:
        operand = part(expr.unary.operand, lambda p: p < CALL)
        return SYMBOL[expr.unary.op] + operand, UNARY
    if expr.binary is not None:
        op = expr.binary.op
        prec, right = PREC[op], op == Operator.POW  # `**` groups to the right
        lhs = part(expr.binary.lhs, lambda p: p < prec or (p == prec and right))
        rhs = part(expr.binary.rhs, lambda p: p < prec or (p == prec and not right))
        return f"{lhs} {SYMBOL[op]} {rhs}", prec
    if expr.ternary is not None:
        t = expr.ternary
        cond = part(t.cond, lambda p: p <= TERNARY)
        then = part(t.then, lambda p: p == RAW)
        otherwise = part(t.otherwise, lambda p: p == RAW)
        return f"{cond} ? {then} : {otherwise}", TERNARY
    if resolve and expr.raw:  # unparsed: substitute words, as nyancad does

        def word(m: re.Match[str]) -> str:
            sub = resolve(m[0])
            return m[0] if sub is None else _text(sub, dialect, None)[0]

        return WORD_RE.sub(word, expr.raw), RAW
    return expr.raw or "", RAW


def format_expression(
    expr: Expression,
    dialect: str,
    resolve: Resolve | None = None,
    *,
    named: bool = False,
) -> str:
    """Canonical text of ``expr`` for ``dialect``.

    ngspice/xyce wrap a compound expression in ``{…}``, hspice in ``'…'``; spectre,
    vacask, systemverilog and vams print it bare. A literal or a reference is never
    wrapped. Raw text is wrapped only as the value of a ``named`` (``k=v``) param, and
    not when it is already wrapped or a bare word or number; a positional value
    (``DC 1 AC 1``) stays verbatim. ``resolve(name)`` may substitute a reference, or a
    word of raw text; the substitute is printed as is, not resolved again.
    """
    opening, closing = WRAP[dialect]
    text, prec = _text(expr, dialect, resolve)
    if prec == RAW:
        token = parse_expression(text)
        single = token.literal is not None or token.reference is not None
        if not named or single or text[:1] + text[-1:] in ("{}", "''"):
            return text
    elif prec == ATOM:
        return text
    return f"{opening}{text}{closing}"
