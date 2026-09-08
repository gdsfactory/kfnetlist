use serde::{Deserialize, Serialize};

/// Cell-level port of a netlist (top-level pin).
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NetlistPort {
    pub name: String,
}

/// Reference to a port on an instance.
///
/// Array references are represented separately by [`PortArrayRef`].
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortRef {
    pub instance: String,
    pub port: String,
}

#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortArrayRef {
    pub instance: String,
    pub port: String,
    pub ia: i64,
    pub ib: i64,
}
