//! Canonical text of an `Expression`, as a kfnetlist setting shows it: the infix form
//! morphnet's `format_expression` prints (`0.13 * 1e-6`), with no dialect wrapping.
use crate::proto::{expression::Node, Expression, Operator, PrefixedValue};

// Binding strength of a printed node; raw text inside a tree is always parenthesised.
const RAW: i32 = -1;
const TERNARY: i32 = 0;
const UNARY: i32 = 7;
const CALL: i32 = 9;
const ATOM: i32 = 10;

// SIPrefix enum value -> power of ten (QUECTO = 1 ... QUETTA = 24).
const SI_EXPONENT: [i32; 25] = [
    0, -30, -27, -24, -21, -18, -15, -12, -9, -6, -3, -2, -1, 1, 2, 3, 6, 9, 12, 15, 18, 21, 24,
    27, 30,
];
// SIPrefix enum value -> the SPICE suffix morphnet writes (its `format_si_value`).
const SI_SUFFIX: [(i32, &str); 10] = [
    (5, "a"),
    (6, "f"),
    (7, "p"),
    (8, "n"),
    (9, "u"),
    (10, "m"),
    (15, "k"),
    (16, "meg"),
    (17, "g"),
    (18, "t"),
];

/// The plain value of `v` (`2.2` MICRO -> `2.2e-6`).
pub(crate) fn scaled(v: &PrefixedValue) -> f64 {
    let exponent = usize::try_from(v.prefix)
        .ok()
        .and_then(|i| SI_EXPONENT.get(i))
        .copied()
        .unwrap_or(0);
    v.double_value * 10f64.powi(exponent)
}

/// Python's `repr` without `.0` or exponent padding: `0.13`, `2`, `1e-6`, `1.5e20`.
fn shortest(x: f64) -> String {
    let sci = format!("{x:e}");
    let exponent: i32 = sci
        .split_once('e')
        .and_then(|(_, e)| e.parse().ok())
        .unwrap_or(0);
    if (-4..16).contains(&exponent) {
        format!("{x}")
    } else {
        sci
    }
}

fn number(v: &PrefixedValue) -> String {
    match SI_SUFFIX.iter().find(|(prefix, _)| *prefix == v.prefix) {
        Some((_, suffix)) => format!("{}{suffix}", shortest(v.double_value)),
        None => shortest(scaled(v)),
    }
}

fn operator(op: i32) -> (&'static str, i32) {
    match Operator::try_from(op).unwrap_or_default() {
        Operator::Or => ("||", 1),
        Operator::And => ("&&", 2),
        Operator::Eq => ("==", 3),
        Operator::Ne => ("!=", 3),
        Operator::Lt => ("<", 4),
        Operator::Le => ("<=", 4),
        Operator::Gt => (">", 4),
        Operator::Ge => (">=", 4),
        Operator::Add => ("+", 5),
        Operator::Sub => ("-", 5),
        Operator::Mul => ("*", 6),
        Operator::Div => ("/", 6),
        Operator::Mod => ("%", 6),
        Operator::Pow => ("**", 8),
        Operator::Neg => ("-", UNARY),
        Operator::Not => ("!", UNARY),
        Operator::Unspecified => ("?", RAW),
    }
}

fn part(sub: &Option<Box<Expression>>, parens: impl Fn(i32) -> bool) -> String {
    let (text, prec) = sub.as_deref().map_or((String::new(), RAW), text);
    if parens(prec) {
        format!("({text})")
    } else {
        text
    }
}

/// Printed `e` and its binding strength.
fn text(e: &Expression) -> (String, i32) {
    match &e.node {
        None => (String::new(), RAW),
        Some(Node::Raw(raw)) => (raw.clone(), RAW),
        Some(Node::Reference(name)) => (name.clone(), ATOM),
        Some(Node::Literal(v)) => (number(v), ATOM),
        Some(Node::Call(c)) => {
            let args: Vec<_> = c.args.iter().map(|a| text(a).0).collect();
            (format!("{}({})", c.name, args.join(", ")), CALL)
        }
        Some(Node::Unary(u)) => {
            let operand = part(&u.operand, |p| p < CALL);
            (format!("{}{operand}", operator(u.op).0), UNARY)
        }
        Some(Node::Binary(b)) => {
            let (symbol, prec) = operator(b.op);
            let right = b.op == Operator::Pow as i32; // `**` groups to the right
            let lhs = part(&b.lhs, |p| p < prec || (p == prec && right));
            let rhs = part(&b.rhs, |p| p < prec || (p == prec && !right));
            (format!("{lhs} {symbol} {rhs}"), prec)
        }
        Some(Node::Ternary(t)) => {
            let cond = part(&t.cond, |p| p <= TERNARY);
            let then = part(&t.then, |p| p == RAW);
            let otherwise = part(&t.otherwise, |p| p == RAW);
            (format!("{cond} ? {then} : {otherwise}"), TERNARY)
        }
    }
}

/// Canonical text of `e`, unwrapped (raw text verbatim).
pub(crate) fn canonical(e: &Expression) -> String {
    text(e).0
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::proto::{BinaryOp, Call, Ternary, UnaryOp};

    fn node(n: Node) -> Expression {
        Expression { node: Some(n) }
    }
    fn num(x: f64, prefix: i32) -> Expression {
        node(Node::Literal(PrefixedValue {
            double_value: x,
            prefix,
        }))
    }
    fn name(n: &str) -> Expression {
        node(Node::Reference(n.into()))
    }
    fn bin(op: Operator, lhs: Expression, rhs: Expression) -> Expression {
        node(Node::Binary(Box::new(BinaryOp {
            op: op as i32,
            lhs: Some(Box::new(lhs)),
            rhs: Some(Box::new(rhs)),
        })))
    }
    fn neg(x: Expression) -> Expression {
        node(Node::Unary(Box::new(UnaryOp {
            op: Operator::Neg as i32,
            operand: Some(Box::new(x)),
        })))
    }

    #[test]
    fn numbers_print_like_nyancad() {
        let cases = [
            (num(0.13, 0), "0.13"),
            (num(1e-6, 0), "1e-6"),
            (num(2.0, 0), "2"),
            (num(1e16, 0), "1e16"),
            (num(1.5e20, 0), "1.5e20"),
            (num(0.0001, 0), "0.0001"),
            (num(2.2, 9), "2.2u"),
            (num(1.0, 16), "1meg"),
            (num(3.0, 11), "0.03"), // CENTI: no SPICE suffix
        ];
        for (e, want) in cases {
            assert_eq!(canonical(&e), want);
        }
    }

    #[test]
    fn operators_print_with_minimal_parentheses() {
        use Operator::*;
        let (a, b, c) = (name("a"), name("b"), name("c"));
        let cases = [
            (bin(Mul, num(0.13, 0), num(1e-6, 0)), "0.13 * 1e-6"),
            (
                bin(Mul, bin(Add, a.clone(), b.clone()), c.clone()),
                "(a + b) * c",
            ),
            (
                bin(Add, a.clone(), bin(Mul, b.clone(), c.clone())),
                "a + b * c",
            ),
            (
                bin(Sub, a.clone(), bin(Sub, b.clone(), c.clone())),
                "a - (b - c)",
            ),
            (
                bin(Sub, bin(Sub, a.clone(), b.clone()), c.clone()),
                "a - b - c",
            ),
            (
                bin(Pow, a.clone(), bin(Pow, b.clone(), c.clone())),
                "a ** b ** c",
            ),
            (
                bin(Pow, bin(Pow, a.clone(), b.clone()), c.clone()),
                "(a ** b) ** c",
            ),
            (neg(bin(Pow, a.clone(), b.clone())), "-(a ** b)"),
            (bin(Pow, neg(a.clone()), b.clone()), "(-a) ** b"),
            (bin(Mul, neg(a.clone()), b.clone()), "-a * b"),
            (
                bin(Or, bin(Lt, a.clone(), b.clone()), c.clone()),
                "a < b || c",
            ),
        ];
        for (e, want) in cases {
            assert_eq!(canonical(&e), want);
        }
    }

    #[test]
    fn calls_ternaries_and_raw_text() {
        let max = node(Node::Call(Call {
            name: "max".into(),
            args: vec![name("a"), num(1.0, 15)],
        }));
        let pick = |cond: Expression| {
            node(Node::Ternary(Box::new(Ternary {
                cond: Some(Box::new(cond)),
                then: Some(Box::new(max.clone())),
                otherwise: Some(Box::new(neg(name("b")))),
            })))
        };
        let gt = bin(Operator::Gt, name("a"), name("b"));
        assert_eq!(canonical(&pick(gt)), "a > b ? max(a, 1k) : -b");
        assert_eq!(
            canonical(&pick(pick(name("c")))),
            "(c ? max(a, 1k) : -b) ? max(a, 1k) : -b"
        );
        let raw = node(Node::Raw("DC 1 AC 1".into()));
        assert_eq!(canonical(&raw), "DC 1 AC 1");
        assert_eq!(
            canonical(&bin(Operator::Add, raw, name("x"))),
            "(DC 1 AC 1) + x"
        );
        assert_eq!(canonical(&Expression::default()), "");
    }
}
