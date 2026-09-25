//! Explicit, serializable hierarchy without placement or layout generation.
use crate::{Error, FlattenOptions, Netlist, NetlistData, NetlistInstance, Result};
use indexmap::IndexMap;
use serde::{de, ser, Deserialize, Deserializer, Serialize, Serializer};
use std::collections::{HashMap, HashSet};
use std::ops::{Deref, DerefMut};

/// Keys are document-local netlist identifiers, not necessarily layout cell names.
/// Mutable children can temporarily invalidate the hierarchy; call `validate`
/// after edits. Serialization and hierarchy-wide operations validate first.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct HierarchicalNetlist {
    netlists: IndexMap<String, Netlist>,
}

impl HierarchicalNetlist {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn from_netlists(netlists: IndexMap<String, Netlist>) -> Result<Self> {
        let hierarchy = Self { netlists };
        hierarchy.validate()?;
        Ok(hierarchy)
    }

    pub fn validate(&self) -> Result<()> {
        validate_instance_maps(
            self.netlists
                .iter()
                .map(|(name, netlist)| (name.as_str(), &netlist.instances)),
        )
    }

    pub fn to_json(&self) -> Result<String> {
        self.validate()?;
        crate::to_json(self)
    }

    /// Inline a selected root against the complete document.
    pub fn flatten(&self, root: &str, options: &FlattenOptions) -> Result<Netlist> {
        self.validate()?;
        let base = self
            .netlists
            .get(root)
            .ok_or_else(|| Error::MissingNetlist(root.to_string()))?
            .clone();
        let subs: HashMap<String, NetlistData> = self
            .netlists
            .iter()
            .map(|(name, netlist)| (name.clone(), netlist.clone().into()))
            .collect();
        let output = crate::flatten_netlist(base.into(), None, &subs, &HashMap::new(), options)?;
        Ok(Netlist {
            instances: output.data.instances,
            nets: output.data.nets,
            ports: output.data.ports,
        })
    }
}

impl Deref for HierarchicalNetlist {
    type Target = IndexMap<String, Netlist>;

    fn deref(&self) -> &Self::Target {
        &self.netlists
    }
}

impl DerefMut for HierarchicalNetlist {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.netlists
    }
}

impl<'de> Deserialize<'de> for HierarchicalNetlist {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        let netlists = IndexMap::<String, Netlist>::deserialize(deserializer)?;
        Self::from_netlists(netlists).map_err(de::Error::custom)
    }
}

impl Serialize for HierarchicalNetlist {
    fn serialize<S: Serializer>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error> {
        self.validate().map_err(ser::Error::custom)?;
        self.netlists.serialize(serializer)
    }
}

/// Parse a complete document and validate all references before returning it.
pub fn hierarchy_from_json(data: &str) -> Result<HierarchicalNetlist> {
    crate::from_json(data)
}

/// Validate reference targets and reject cycles. Leaves require no child definition.
/// Call again after editing the publicly mutable document.
pub fn validate_hierarchy(hierarchy: &HierarchicalNetlist) -> Result<()> {
    hierarchy.validate()
}

pub(crate) fn validate_instance_maps<'a>(
    netlists: impl IntoIterator<Item = (&'a str, &'a IndexMap<String, NetlistInstance>)>,
) -> Result<()> {
    let maps: HashMap<_, _> = netlists.into_iter().collect();
    for (name, instances) in &maps {
        for (instance, value) in *instances {
            if let Some(reference) = value.netlist_id() {
                if !maps.contains_key(reference) {
                    return Err(Error::MissingNetlistReference {
                        netlist: (*name).into(),
                        instance: instance.clone(),
                        reference: reference.into(),
                    });
                }
            }
        }
    }
    // Iterative DFS avoids consuming the call stack for deeply nested documents.
    let mut done = HashSet::new();
    let mut active = HashSet::new();
    for name in maps.keys().copied() {
        let mut stack = vec![(name, false)];
        while let Some((name, exiting)) = stack.pop() {
            if exiting {
                active.remove(name);
                done.insert(name);
                continue;
            }
            if done.contains(name) {
                continue;
            }
            if !active.insert(name) {
                return Err(Error::CyclicNetlistReference(name.into()));
            }
            stack.push((name, true));
            for instance in maps[name].values().rev() {
                if let Some(reference) = instance.netlist_id() {
                    stack.push((reference, false));
                }
            }
        }
    }
    Ok(())
}
