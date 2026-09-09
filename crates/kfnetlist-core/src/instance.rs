use serde::{Deserialize, Serialize};

/// Array dimensions for an array instance (`na` × `nb`).
#[derive(Clone, Debug, Hash, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NetlistArray {
    pub na: i64,
    pub nb: i64,
}

/// Instance of a sub-cell within a netlist.
///
/// `name` is set by the parent `Netlist` from the dict key on deserialization
/// and is intentionally excluded from the JSON wire format.
///
/// Placement-aware instances compose this value with physical attributes.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(from = "NetlistInstanceWire", into = "NetlistInstanceWire")]
pub struct NetlistInstance {
    pub kcl: String,
    pub component: String,
    /// Free-form JSON-serializable settings.
    pub settings: serde_json::Value,
    pub array: Option<NetlistArray>,
    pub name: String,
}

/// Wire format used by serde to (de)serialize NetlistInstance without `name`.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NetlistInstanceWire {
    pub kcl: String,
    pub component: String,
    #[serde(default)]
    pub settings: serde_json::Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub array: Option<NetlistArray>,
}

impl NetlistInstance {
    pub fn to_wire(&self) -> NetlistInstanceWire {
        NetlistInstanceWire {
            kcl: self.kcl.clone(),
            component: self.component.clone(),
            settings: if self.settings.is_null() {
                serde_json::Value::Object(Default::default())
            } else {
                self.settings.clone()
            },
            array: self.array.clone(),
        }
    }

    pub fn from_wire(name: String, wire: NetlistInstanceWire) -> Self {
        Self {
            kcl: wire.kcl,
            component: wire.component,
            settings: wire.settings,
            array: wire.array,
            name,
        }
    }
}

impl NetlistInstance {
    pub fn normalize(&mut self) {
        crate::normalize_value(&mut self.settings);
    }
}
impl From<NetlistInstanceWire> for NetlistInstance {
    fn from(wire: NetlistInstanceWire) -> Self {
        Self::from_wire(String::new(), wire)
    }
}
impl From<NetlistInstance> for NetlistInstanceWire {
    fn from(value: NetlistInstance) -> Self {
        value.to_wire()
    }
}
