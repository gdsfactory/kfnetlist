//! Hierarchical PIC documents and protobuf messages, with no Python dependency.
//!
//! Both follow one hierarchy: a netlist (container) holds circuit definitions, and
//! each circuit holds subcircuit instances.
//!
//! Protobuf structs are generated from `proto/circuit.proto` by prost in OUT_DIR.
//! YAML and netlist conversions operate on native Rust values throughout.
mod convert;
mod document;
mod expression;
pub mod paths;
pub use document::{ArraySpec, CircuitDocument, NetlistDocument, SubCircuitDocument};

#[deprecated(note = "renamed to NetlistDocument")]
pub type TopLevelModule = NetlistDocument;
#[deprecated(note = "renamed to CircuitDocument")]
pub type Module = CircuitDocument;
#[deprecated(note = "renamed to SubCircuitDocument")]
pub type Instance = SubCircuitDocument;

pub mod proto {
    include!(concat!(env!("OUT_DIR"), "/circuit.rs"));
}

#[derive(Debug)]
pub struct Error(pub String);
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Error {}
pub type Result<T> = std::result::Result<T, Error>;
pub(crate) fn error(e: impl std::fmt::Display) -> Error {
    Error(e.to_string())
}

// Preserve the ergonomic JSON fields while enforcing protobuf oneof semantics
// in the schema crate for every caller (including nested dict and YAML construction).
#[derive(Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default, deny_unknown_fields)]
struct ParameterValueWire {
    #[serde(skip_serializing_if = "Option::is_none")]
    prefixed_value: Option<proto::PrefixedValue>,
    #[serde(skip_serializing_if = "Option::is_none")]
    model_ref: Option<proto::ModelReference>,
    #[serde(skip_serializing_if = "Option::is_none")]
    expression: Option<proto::Expression>,
}
impl TryFrom<ParameterValueWire> for proto::ParameterValue {
    type Error = Error;
    fn try_from(w: ParameterValueWire) -> Result<Self> {
        use proto::parameter_value::Value;
        let mut values = [
            w.prefixed_value.map(Value::PrefixedValue),
            w.model_ref.map(Value::ModelRef),
            w.expression.map(Value::Expression),
        ]
        .into_iter()
        .flatten();
        let value = values.next();
        if values.next().is_some() {
            return Err(Error("ParameterValue accepts only one value".into()));
        }
        Ok(Self { value })
    }
}
impl From<proto::ParameterValue> for ParameterValueWire {
    fn from(p: proto::ParameterValue) -> Self {
        use proto::parameter_value::Value;
        match p.value {
            Some(Value::PrefixedValue(p)) => Self {
                prefixed_value: Some(p),
                ..Self::default()
            },
            Some(Value::ModelRef(m)) => Self {
                model_ref: Some(m),
                ..Self::default()
            },
            Some(Value::Expression(e)) => Self {
                expression: Some(e),
                ..Self::default()
            },
            None => Self::default(),
        }
    }
}

// Expression's oneof is flat in JSON (`{"binary": {...}}`), as in protobuf JSON and
// the pydantic mirror, rather than serde's `{"node": {"binary": {...}}}`.
#[derive(Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default, deny_unknown_fields)]
struct ExpressionWire {
    #[serde(skip_serializing_if = "Option::is_none")]
    literal: Option<proto::PrefixedValue>,
    #[serde(skip_serializing_if = "Option::is_none")]
    reference: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    unary: Option<Box<proto::UnaryOp>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    binary: Option<Box<proto::BinaryOp>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    call: Option<proto::Call>,
    #[serde(skip_serializing_if = "Option::is_none")]
    ternary: Option<Box<proto::Ternary>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    raw: Option<String>,
}
impl TryFrom<ExpressionWire> for proto::Expression {
    type Error = Error;
    fn try_from(w: ExpressionWire) -> Result<Self> {
        use proto::expression::Node;
        let mut nodes = [
            w.literal.map(Node::Literal),
            w.reference.map(Node::Reference),
            w.unary.map(Node::Unary),
            w.binary.map(Node::Binary),
            w.call.map(Node::Call),
            w.ternary.map(Node::Ternary),
            w.raw.map(Node::Raw),
        ]
        .into_iter()
        .flatten();
        let node = nodes.next();
        if nodes.next().is_some() {
            return Err(Error("Expression accepts only one node".into()));
        }
        Ok(Self { node })
    }
}
impl From<proto::Expression> for ExpressionWire {
    fn from(e: proto::Expression) -> Self {
        use proto::expression::Node;
        let mut w = Self::default();
        match e.node {
            Some(Node::Literal(v)) => w.literal = Some(v),
            Some(Node::Reference(v)) => w.reference = Some(v),
            Some(Node::Unary(v)) => w.unary = Some(v),
            Some(Node::Binary(v)) => w.binary = Some(v),
            Some(Node::Call(v)) => w.call = Some(v),
            Some(Node::Ternary(v)) => w.ternary = Some(v),
            Some(Node::Raw(v)) => w.raw = Some(v),
            None => {}
        }
        w
    }
}
