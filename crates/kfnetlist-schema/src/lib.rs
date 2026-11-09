//! Hierarchical PIC documents and protobuf messages, with no Python dependency.
//!
//! Both follow one hierarchy: a netlist (container) holds circuit definitions, and
//! each circuit holds subcircuit instances.
//!
//! Protobuf structs are generated from `proto/circuit.proto` by prost in OUT_DIR.
//! YAML and netlist conversions operate on native Rust values throughout.
mod convert;
mod document;
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
}
impl TryFrom<ParameterValueWire> for proto::ParameterValue {
    type Error = Error;
    fn try_from(w: ParameterValueWire) -> Result<Self> {
        use proto::parameter_value::Value;
        let value = match (w.prefixed_value, w.model_ref) {
            (Some(_), Some(_)) => {
                return Err(Error("ParameterValue accepts only one value".into()))
            }
            (Some(p), None) => Some(Value::PrefixedValue(p)),
            (None, Some(m)) => Some(Value::ModelRef(m)),
            (None, None) => None,
        };
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
            None => Self::default(),
        }
    }
}
