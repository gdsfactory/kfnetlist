"""``parse_expression`` / ``format_expression``: canonical text, precedence, dialects."""

import pytest

from kfnetlist.morphnet.morphnet_schema import (
    BinaryOp,
    Expression,
    Operator,
    PrefixedValue,
    SIPrefix,
)
from kfnetlist.morphnet.netlist.expression import format_expression, parse_expression


def canonical(text: str) -> str:
    return format_expression(parse_expression(text), "spectre")


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        ("0.13*1e-6", "0.13 * 1e-6"),
        ("a+b*c", "a + b * c"),
        ("(a+b)*c", "(a + b) * c"),
        ("a-b-c", "a - b - c"),
        ("a-(b-c)", "a - (b - c)"),
        ("a/(b*c)", "a / (b * c)"),
        ("a%b", "a % b"),
        ("2**3**2", "2 ** 3 ** 2"),
        ("(2**3)**2", "(2 ** 3) ** 2"),
        ("((a))", "a"),
    ],
)
def test_binary_operators_print_with_minimal_parentheses(text, printed):
    assert canonical(text) == printed


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        ("-a", "-a"),
        ("+a", "a"),
        ("!a", "!a"),
        ("-(a+b)", "-(a + b)"),
        ("-a**2", "-(a ** 2)"),
        ("(-a)**2", "(-a) ** 2"),
        ("2**-1", "2 ** (-1)"),
        ("- -a", "-(-a)"),
        ("-a*b", "-a * b"),
    ],
)
def test_unary_operators(text, printed):
    assert canonical(text) == printed


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        ("a<b && c>=d || !e", "a < b && c >= d || !e"),
        ("a==b != c", "a == b != c"),
        ("a<=b", "a <= b"),
        ("a&&(b||c)", "a && (b || c)"),
        ("a>b?a:b", "a > b ? a : b"),
        ("a?b:c?d:e", "a ? b : c ? d : e"),
        ("(a?b:c)?d:e", "(a ? b : c) ? d : e"),
        ("(a?b:c)+1", "(a ? b : c) + 1"),
    ],
)
def test_comparisons_logic_and_ternary(text, printed):
    assert canonical(text) == printed


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        ("max(a,2*b)", "max(a, 2 * b)"),
        ("f()", "f()"),
        ("-sqrt(x)", "-sqrt(x)"),
        ("$clog2(N)", "$clog2(N)"),
    ],
)
def test_calls(text, printed):
    assert canonical(text) == printed


def test_si_literals_keep_their_prefix():
    expr = parse_expression("2.2u*w")
    assert expr.binary.lhs.literal == PrefixedValue(
        double_value=2.2, prefix=SIPrefix.MICRO
    )
    assert canonical("2.2u*w") == "2.2u * w"
    assert canonical("1meg") == "1meg"
    assert format_expression(expr, "systemverilog") == "2.2e-6 * w"


@pytest.mark.parametrize(
    ("text", "printed"),
    [("1e-06", "1e-6"), ("2.0", "2"), ("1e16", "1e16"), ("1.5e+20", "1.5e20")],
)
def test_unprefixed_numbers_print_shortest(text, printed):
    assert canonical(text) == printed


@pytest.mark.parametrize("text", ["{0.13 * 1e-6}", "'0.13*1e-6'", " 0.13*1e-6 "])
def test_one_outer_wrapper_is_stripped(text):
    assert parse_expression(text) == parse_expression("0.13*1e-6")


@pytest.mark.parametrize(
    "text", ["DC 1 AC 1", '"pulse"', "{{a}}", "a +", "", "{a} + {b}", "1_000", "a^b"]
)
def test_unparseable_text_is_kept_raw_and_printed_verbatim(text):
    expr = parse_expression(text)
    assert expr == Expression(raw=text)
    for dialect in ("ngspice", "hspice", "spectre"):
        assert format_expression(expr, dialect) == text


@pytest.mark.parametrize(
    ("dialect", "printed"),
    [
        ("ngspice", "{0.13 * 1e-6}"),
        ("xyce", "{0.13 * 1e-6}"),
        ("hspice", "'0.13 * 1e-6'"),
        ("spectre", "0.13 * 1e-6"),
        ("vacask", "0.13 * 1e-6"),
        ("systemverilog", "0.13 * 1e-6"),
        ("vams", "0.13 * 1e-6"),
    ],
)
def test_dialects_wrap_compound_expressions(dialect, printed):
    assert format_expression(parse_expression("0.13*1e-6"), dialect) == printed


@pytest.mark.parametrize("text", ["w", "2.2u", "{w}"])
def test_a_bare_literal_or_reference_is_never_wrapped(text):
    assert format_expression(parse_expression(text), "ngspice") == text.strip("{}")


def test_calls_and_unary_are_wrapped():
    assert format_expression(parse_expression("max(a,b)"), "hspice") == "'max(a, b)'"
    assert format_expression(parse_expression("-a"), "xyce") == "{-a}"


def test_resolve_substitutes_references():
    values = {"W": parse_expression("0.15*1e-6"), "N": parse_expression("2")}
    expr = parse_expression("W*N")
    assert format_expression(expr, "ngspice", values.get) == "{0.15 * 1e-6 * 2}"
    assert format_expression(parse_expression("N*W"), "spectre", values.get) == (
        "2 * (0.15 * 1e-6)"
    )
    # a reference resolving to a literal is bare; unresolved names stay
    assert format_expression(parse_expression("N"), "ngspice", values.get) == "2"
    assert format_expression(parse_expression("L"), "ngspice", values.get) == "L"


def test_a_built_tree_prints_like_its_parsed_text():
    tree = Expression(
        binary=BinaryOp(
            op=Operator.MUL,
            lhs=Expression(literal=PrefixedValue(double_value=0.13)),
            rhs=Expression(literal=PrefixedValue(double_value=1e-6)),
        )
    )
    assert parse_expression("0.13 * 1e-6") == tree
    assert format_expression(tree, "spectre") == "0.13 * 1e-6"


@pytest.mark.parametrize(
    "text",
    ["a + b * c", "(a + b) * c", "-(a ** 2)", "a > b ? max(a, 1k) : -b", "2.2u * w"],
)
def test_canonical_text_round_trips(text):
    assert canonical(canonical(text)) == canonical(text) == text
