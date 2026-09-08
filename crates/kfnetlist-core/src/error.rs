use std::fmt;

use crate::PortArrayRef;

/// Errors from netlist validation, lookup, and JSON conversion.
#[derive(Debug)]
#[non_exhaustive]
pub enum Error {
    InvalidArrayDimensions {
        na: i64,
        nb: i64,
    },
    UnknownInstance(String),
    UndefinedPort(String),
    NotArrayInstance(PortArrayRef),
    ArrayIndexOutOfBounds {
        instance: String,
        direction: ArrayDirection,
        size: i64,
        index: i64,
    },
    MissingCanonicalPort(String),
    MissingInstance(String),
    Serialize(serde_json::Error),
    Deserialize(serde_json::Error),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ArrayDirection {
    A,
    B,
}

pub type Result<T> = std::result::Result<T, Error>;

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidArrayDimensions { na, nb } => write!(f,
                "An instance array must have at least one instance in the array. na={na} and nb={nb} must be >= 1"),
            Self::UnknownInstance(name) => write!(f, "Unknown instance {name}"),
            Self::UndefinedPort(name) => write!(f, "Undefined netlist port {name}"),
            Self::NotArrayInstance(reference) => write!(f,
                "Instance {} is not an array instance. But an array portref was requested PortArrayRefData {{ instance: {:?}, port: {:?}, ia: {}, ib: {} }}",
                reference.instance, reference.instance, reference.port, reference.ia, reference.ib),
            Self::ArrayIndexOutOfBounds { instance, direction, size, .. } => {
                let direction = match direction { ArrayDirection::A => "na", ArrayDirection::B => "nb" };
                write!(f, "Instance {instance} has only {size} elements in `{direction}` direction")
            }
            Self::MissingCanonicalPort(name) => write!(f,
                "normalize: canonical port {name:?} not present in netlist ports"),
            Self::MissingInstance(name) => f.write_str(name),
            Self::Serialize(error) => write!(f, "serialize: {error}"),
            Self::Deserialize(error) => write!(f, "deserialize: {error}"),
        }
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Serialize(e) | Self::Deserialize(e) => Some(e),
            _ => None,
        }
    }
}
