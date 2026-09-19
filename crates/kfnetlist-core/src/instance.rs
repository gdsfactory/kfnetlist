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
#[serde(from = "LeafNetlistInstanceWire", into = "LeafNetlistInstanceWire")]
pub struct LeafNetlistInstance {
    /// Per-instance JSON-compatible metadata.
    pub info: serde_json::Map<String, serde_json::Value>,
    pub kcl: String,
    pub component: String,
    /// Free-form JSON-serializable settings.
    pub settings: serde_json::Value,
    pub array: Option<NetlistArray>,
    pub name: String,
}

/// Wire format used by serde to (de)serialize LeafNetlistInstance without `name`.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LeafNetlistInstanceWire {
    #[serde(default, skip_serializing_if = "serde_json::Map::is_empty")]
    pub info: serde_json::Map<String, serde_json::Value>,
    pub kcl: String,
    pub component: String,
    #[serde(default)]
    pub settings: serde_json::Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub array: Option<NetlistArray>,
}

impl LeafNetlistInstance {
    pub fn to_wire(&self) -> LeafNetlistInstanceWire {
        LeafNetlistInstanceWire {
            info: self.info.clone(),
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

    pub fn from_wire(name: String, wire: LeafNetlistInstanceWire) -> Self {
        Self {
            info: wire.info,
            kcl: wire.kcl,
            component: wire.component,
            settings: wire.settings,
            array: wire.array,
            name,
        }
    }
}

impl LeafNetlistInstance {
    pub fn normalize(&mut self) {
        crate::normalize_value(&mut self.settings);
    }
}
impl From<LeafNetlistInstanceWire> for LeafNetlistInstance {
    fn from(wire: LeafNetlistInstanceWire) -> Self {
        Self::from_wire(String::new(), wire)
    }
}
impl From<LeafNetlistInstance> for LeafNetlistInstanceWire {
    fn from(value: LeafNetlistInstance) -> Self {
        value.to_wire()
    }
}

/// An instance with an explicit reference to a netlist in the same document.
/// The reference is independent of generated layout cell names.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "serde_json::Value", into = "serde_json::Value")]
pub struct RefNetlistInstance {
    pub instance: LeafNetlistInstance,
    pub netlist_ref: String,
}

/// A component leaf or an explicit reference to another netlist.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(from = "NetlistInstanceWire", into = "NetlistInstanceWire")]
pub enum NetlistInstance {
    Leaf(LeafNetlistInstance),
    Ref(RefNetlistInstance),
}

/// Untagged on the wire: the presence of `ref` selects the reference variant.
/// Invalid references cannot fall back to a leaf and lose their reference.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(try_from = "serde_json::Value", into = "serde_json::Value")]
pub enum NetlistInstanceWire {
    Leaf(LeafNetlistInstanceWire),
    Ref {
        instance: LeafNetlistInstanceWire,
        netlist_ref: String,
    },
}

impl TryFrom<serde_json::Value> for NetlistInstanceWire {
    type Error = serde_json::Error;
    fn try_from(mut value: serde_json::Value) -> Result<Self, Self::Error> {
        let reference = value.as_object_mut().and_then(|obj| obj.remove("ref"));
        let netlist_ref = reference
            .map(serde_json::from_value::<String>)
            .transpose()?;
        let instance = serde_json::from_value(value)?;
        Ok(match netlist_ref {
            Some(netlist_ref) => Self::Ref {
                instance,
                netlist_ref,
            },
            None => Self::Leaf(instance),
        })
    }
}

impl From<NetlistInstanceWire> for serde_json::Value {
    fn from(wire: NetlistInstanceWire) -> Self {
        let (instance, reference) = match wire {
            NetlistInstanceWire::Leaf(instance) => (instance, None),
            NetlistInstanceWire::Ref {
                instance,
                netlist_ref,
            } => (instance, Some(netlist_ref)),
        };
        let mut value =
            serde_json::to_value(instance).expect("instance wire contains only JSON values");
        if let Some(reference) = reference {
            value
                .as_object_mut()
                .expect("instance wire is an object")
                .insert("ref".into(), reference.into());
        }
        value
    }
}

impl NetlistInstance {
    pub fn netlist_ref(&self) -> Option<&str> {
        match self {
            Self::Leaf(_) => None,
            Self::Ref(inst) => Some(&inst.netlist_ref),
        }
    }
    pub fn to_wire(&self) -> NetlistInstanceWire {
        match self {
            Self::Leaf(inst) => NetlistInstanceWire::Leaf(inst.to_wire()),
            Self::Ref(inst) => NetlistInstanceWire::Ref {
                instance: inst.instance.to_wire(),
                netlist_ref: inst.netlist_ref.clone(),
            },
        }
    }
    pub fn from_wire(name: String, wire: NetlistInstanceWire) -> Self {
        match wire {
            NetlistInstanceWire::Leaf(wire) => {
                Self::Leaf(LeafNetlistInstance::from_wire(name, wire))
            }
            NetlistInstanceWire::Ref {
                instance,
                netlist_ref,
            } => Self::Ref(RefNetlistInstance {
                instance: LeafNetlistInstance::from_wire(name, instance),
                netlist_ref,
            }),
        }
    }
}

// Common fields retain their existing access syntax. Variant changes remain explicit.
impl std::ops::Deref for NetlistInstance {
    type Target = LeafNetlistInstance;
    fn deref(&self) -> &Self::Target {
        match self {
            Self::Leaf(inst) => inst,
            Self::Ref(inst) => &inst.instance,
        }
    }
}
impl std::ops::DerefMut for NetlistInstance {
    fn deref_mut(&mut self) -> &mut Self::Target {
        match self {
            Self::Leaf(inst) => inst,
            Self::Ref(inst) => &mut inst.instance,
        }
    }
}
impl From<LeafNetlistInstance> for NetlistInstance {
    fn from(value: LeafNetlistInstance) -> Self {
        Self::Leaf(value)
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
impl TryFrom<serde_json::Value> for RefNetlistInstance {
    type Error = serde_json::Error;
    fn try_from(value: serde_json::Value) -> Result<Self, Self::Error> {
        match NetlistInstance::from(NetlistInstanceWire::try_from(value)?) {
            NetlistInstance::Ref(instance) => Ok(instance),
            _ => Err(<serde_json::Error as serde::de::Error>::custom(
                "missing field `ref`",
            )),
        }
    }
}
impl From<RefNetlistInstance> for serde_json::Value {
    fn from(value: RefNetlistInstance) -> Self {
        NetlistInstance::Ref(value).to_wire().into()
    }
}
