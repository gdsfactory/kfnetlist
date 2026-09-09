//! Pure Rust connectivity and placement model, independent of Python.
//! Serde representations match the kfnetlist JSON format. Instance names are
//! restored from their parent map keys when deserializing netlists.
mod error;
pub mod flatten;
pub mod instance;
pub mod net;
pub mod netlist;
pub mod placement;
pub mod port;
pub use error::{ArrayDirection, Error, Result};
pub use flatten::{compose_placement, flatten_netlist, FlattenOptions, FlattenOutput, NetlistData};
pub use instance::{NetlistArray, NetlistInstance};
pub use net::{Net, NetMember};
pub use netlist::{EquivalentPorts, NetDifference, Netlist, Opens, PortMapping};
pub use placement::{BBox, PlacedExtra, PlacedInstance, PlacedNetlist, Placement};
pub use port::{NetlistPort, PortArrayRef, PortRef};
use serde::{Deserialize, Serialize};

/// Normalize a free-form settings value in place so that integer-valued floats
/// are stored as integers (e.g. `1.0` -> `1`, but `1.5` is left untouched).
/// This is the lossless direction (`float -> int` only when `is_integer()`), so
/// a value defined by the user/system matches the same value recovered by
/// extraction once both sides are normalized. Recurses through arrays/objects.
pub fn normalize_value(value: &mut serde_json::Value) {
    use serde_json::Value::{Array, Number, Object};
    match value {
        Number(n) if n.is_f64() => {
            if let Some(f) = n.as_f64() {
                if f.is_finite() && f.fract() == 0.0 {
                    if f >= i64::MIN as f64 && f <= i64::MAX as f64 {
                        *n = serde_json::Number::from(f as i64);
                    } else if f >= 0.0 && f <= u64::MAX as f64 {
                        *n = serde_json::Number::from(f as u64);
                    }
                    // Otherwise it has no exact integer representation; leave it.
                }
            }
        }
        Array(items) => items.iter_mut().for_each(normalize_value),
        Object(map) => map.values_mut().for_each(normalize_value),
        _ => {}
    }
}

/// Serialize any core value using the public JSON wire format.
pub fn to_json<T: Serialize>(value: &T) -> Result<String> {
    serde_json::to_string(value).map_err(Error::Serialize)
}
/// Deserialize a core value from the public JSON wire format.
pub fn from_json<'de, T: Deserialize<'de>>(value: &'de str) -> Result<T> {
    serde_json::from_str(value).map_err(Error::Deserialize)
}
