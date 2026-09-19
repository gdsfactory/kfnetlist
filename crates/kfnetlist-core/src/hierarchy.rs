//! Explicit, serializable hierarchy without placement or layout generation.
use crate::{Error, Netlist, NetlistInstance, Result};
use indexmap::IndexMap;
use std::collections::{HashMap, HashSet};

/// Keys are document-local netlist identifiers, not necessarily layout cell names.
pub type HierarchicalNetlist = IndexMap<String, Netlist>;

/// Parse a complete document and validate all references before returning it.
pub fn hierarchy_from_json(data: &str) -> Result<HierarchicalNetlist> {
    let hierarchy = crate::from_json(data)?;
    validate_hierarchy(&hierarchy)?;
    Ok(hierarchy)
}

/// Validate reference targets and reject cycles. Leaves require no child definition.
/// Call again after editing the publicly mutable document.
pub fn validate_hierarchy(hierarchy: &HierarchicalNetlist) -> Result<()> {
    validate_instance_maps(
        hierarchy
            .iter()
            .map(|(name, netlist)| (name.as_str(), &netlist.instances)),
    )
}

pub(crate) fn validate_instance_maps<'a>(
    netlists: impl IntoIterator<Item = (&'a str, &'a IndexMap<String, NetlistInstance>)>,
) -> Result<()> {
    let maps: HashMap<_, _> = netlists.into_iter().collect();
    for (name, instances) in &maps {
        for (instance, value) in *instances {
            if let Some(reference) = value.netlist_ref() {
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
                if let Some(reference) = instance.netlist_ref() {
                    stack.push((reference, false));
                }
            }
        }
    }
    Ok(())
}
