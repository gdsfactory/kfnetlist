use crate::instance::{NetlistArray, NetlistInstance, NetlistInstanceWire};
use crate::net::{Net, NetMember};
use crate::port::{NetlistPort, PortRef};
use crate::{normalize_value, Error, Result};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

/// Wire format used by serde for `Netlist`. Mirrors the JSON shape but
/// stores instances by name without redundant `name` fields.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NetlistWire {
    #[serde(default)]
    pub instances: indexmap::IndexMap<String, NetlistInstanceWire>,
    #[serde(default)]
    pub nets: Vec<Net>,
    #[serde(default)]
    pub ports: Vec<NetlistPort>,
}

/// A netlist: instances, nets, and top-level ports.
///
/// Instances preserve insertion order. Placement is layered on by `PlacedNetlist`.
#[derive(Clone, Default, Debug, Serialize, Deserialize)]
#[serde(from = "NetlistWire", into = "NetlistWire")]
pub struct Netlist {
    /// Instance name → instance. Insertion order preserved.
    pub instances: indexmap::IndexMap<String, NetlistInstance>,
    pub nets: Vec<Net>,
    pub ports: Vec<NetlistPort>,
}

impl Netlist {
    pub fn to_wire(&self) -> NetlistWire {
        NetlistWire {
            instances: self
                .instances
                .iter()
                .map(|(k, v)| (k.clone(), v.to_wire()))
                .collect(),
            nets: self.nets.clone(),
            ports: self.ports.clone(),
        }
    }

    pub fn from_wire(wire: NetlistWire) -> Self {
        Netlist {
            instances: wire
                .instances
                .into_iter()
                .map(|(k, v)| {
                    let inst = NetlistInstance::from_wire(k.clone(), v);
                    (k, inst)
                })
                .collect(),
            nets: wire.nets,
            ports: wire.ports,
        }
    }

    fn normalize_settings(&mut self) {
        for inst in self.instances.values_mut() {
            normalize_value(&mut inst.settings);
        }
    }

    fn equals(&self, other: &Netlist) -> bool {
        if self.ports != other.ports || self.nets != other.nets {
            return false;
        }
        if self.instances.len() != other.instances.len() {
            return false;
        }
        for ((ka, va), (kb, vb)) in self.instances.iter().zip(other.instances.iter()) {
            if ka != kb {
                return false;
            }
            if va.kcl != vb.kcl
                || va.component != vb.component
                || va.settings != vb.settings
                || va.array != vb.array
                || va.name != vb.name
            {
                return false;
            }
        }
        true
    }
}

impl Netlist {
    pub fn instance_names(&self) -> Vec<String> {
        self.instances.keys().cloned().collect()
    }

    pub fn has_instance(&self, name: &str) -> bool {
        self.instances.contains_key(name)
    }

    pub fn get_instance(&self, name: &str) -> Result<NetlistInstance> {
        self.instances
            .get(name)
            .cloned()
            .ok_or_else(|| Error::MissingInstance(name.to_string()))
    }

    pub fn create_port(&mut self, name: String) -> NetlistPort {
        let p = NetlistPort { name };
        self.ports.push(p.clone());
        p
    }

    /// Create or replace an instance. A zero dimension disables array metadata;
    /// otherwise both dimensions must be positive. Returns an owned snapshot.
    pub fn create_inst(
        &mut self,
        name: String,
        kcl: String,
        component: String,
        settings: serde_json::Value,
        na: i64,
        nb: i64,
    ) -> Result<NetlistInstance> {
        let array = if na != 0 && nb != 0 {
            if na < 1 || nb < 1 {
                return Err(Error::InvalidArrayDimensions { na, nb });
            }
            Some(NetlistArray { na, nb })
        } else {
            None
        };
        let inst = NetlistInstance {
            kcl,
            component,
            settings,
            array,
            name: name.clone(),
        };
        self.instances.insert(name, inst.clone());
        Ok(inst)
    }

    /// Validate and add a net atomically. Array reference (1, 1) becomes a plain
    /// reference; other indices retain the historical upper-bound-only check.
    pub fn create_net(&mut self, ports: impl IntoIterator<Item = NetMember>) -> Result<()> {
        let mut members: Vec<NetMember> = Vec::new();
        for member in ports {
            match member {
                NetMember::ArrayRef(par) => {
                    let inst = self
                        .instances
                        .get(&par.instance)
                        .ok_or_else(|| Error::UnknownInstance(par.instance.clone()))?;
                    if par.ia == 1 && par.ib == 1 {
                        members.push(NetMember::Ref(PortRef {
                            instance: par.instance,
                            port: par.port,
                        }));
                        continue;
                    }
                    let array = inst
                        .array
                        .as_ref()
                        .ok_or_else(|| Error::NotArrayInstance(par.clone()))?;
                    if par.ia > array.na {
                        return Err(Error::ArrayIndexOutOfBounds {
                            instance: par.instance.clone(),
                            direction: crate::ArrayDirection::A,
                            size: array.na,
                            index: par.ia,
                        });
                    }
                    if par.ib > array.nb {
                        return Err(Error::ArrayIndexOutOfBounds {
                            instance: par.instance.clone(),
                            direction: crate::ArrayDirection::B,
                            size: array.nb,
                            index: par.ib,
                        });
                    }
                    members.push(NetMember::ArrayRef(par));
                }
                NetMember::Ref(pr) => {
                    if !self.instances.contains_key(&pr.instance) {
                        return Err(Error::UnknownInstance(pr.instance.clone()));
                    }
                    members.push(NetMember::Ref(pr));
                }
                NetMember::Port(np) => {
                    if !self.ports.iter().any(|p| p.name == np.name) {
                        return Err(Error::UndefinedPort(np.name.clone()));
                    }
                    members.push(NetMember::Port(NetlistPort { name: np.name }));
                }
            }
        }
        self.nets.push(Net::from_members(members));
        Ok(())
    }

    /// Validate and add a copy of an existing net.
    pub fn add_net(&mut self, net: &Net) -> Result<()> {
        self.create_net(net.members.clone())
    }
    /// Remove the named instances and merge any nets touching them into
    /// a single new net (per group of nets that referenced the same removed
    /// instance), preserving every surviving port reference.
    ///
    /// This *deletes* an instance: nothing of the cell it referenced is kept.
    /// To replace an instance by the contents of its cell instead, use the
    /// hierarchical flattening API in [`crate::flatten`].
    pub fn remove_instances(&mut self, names: Vec<String>) -> Result<()> {
        for inst_name in names {
            self.instances.shift_remove(&inst_name);
            let mut surviving: Vec<Net> = Vec::with_capacity(self.nets.len());
            let mut merged: Vec<NetMember> = Vec::new();
            for net in self.nets.drain(..) {
                let touches = net.members.iter().any(|m| match m {
                    NetMember::Ref(r) => r.instance == inst_name,
                    NetMember::ArrayRef(r) => r.instance == inst_name,
                    NetMember::Port(_) => false,
                });
                if touches {
                    for m in net.members {
                        let keep = match &m {
                            NetMember::Ref(r) => r.instance != inst_name,
                            NetMember::ArrayRef(r) => r.instance != inst_name,
                            NetMember::Port(_) => true,
                        };
                        if keep {
                            merged.push(m);
                        }
                    }
                } else {
                    surviving.push(net);
                }
            }
            self.nets = surviving;
            self.nets.push(Net::from_members(merged));
        }
        Ok(())
    }

    /// Backwards-compatible alias for [`Netlist::remove_instances`].
    #[deprecated(note = "use remove_instances; flatten now means hierarchical inlining")]
    pub fn flatten_instances(&mut self, names: Vec<String>) -> Result<()> {
        self.remove_instances(names)
    }

    /// Report unconnected top-level ports and singleton nets.
    pub fn detect_opens(&self) -> Opens {
        let connected: HashSet<&str> = self
            .nets
            .iter()
            .flat_map(|n| &n.members)
            .filter_map(|m| match m {
                NetMember::Port(p) => Some(p.name.as_str()),
                _ => None,
            })
            .collect();
        let mut unconnected_ports: Vec<String> = self
            .ports
            .iter()
            .filter(|p| !connected.contains(p.name.as_str()))
            .map(|p| p.name.clone())
            .collect();
        unconnected_ports.sort();
        Opens {
            unconnected_ports,
            singleton_nets: self
                .nets
                .iter()
                .filter(|n| n.members.len() == 1)
                .cloned()
                .collect(),
        }
    }
    /// Compare net membership, retaining source order and duplicate unmatched nets.
    pub fn find_net_difference(&self, reference: &Self) -> NetDifference {
        let own: HashSet<&Net> = self.nets.iter().collect();
        let other: HashSet<&Net> = reference.nets.iter().collect();
        NetDifference {
            missing: reference
                .nets
                .iter()
                .filter(|n| !own.contains(n))
                .cloned()
                .collect(),
            extra: self
                .nets
                .iter()
                .filter(|n| !other.contains(n))
                .cloned()
                .collect(),
        }
    }
    /// Sort instances by name, ports by name, members within each net,
    /// and the nets list itself.
    pub fn sort(&mut self) {
        self.instances.sort_keys();
        for net in &mut self.nets {
            net.sort_in_place();
        }
        self.nets.sort();
        self.ports.sort();
    }

    /// Return a deep copy of the netlist with normalized settings (integer-
    /// valued floats become integers) and sorted contents.
    ///
    /// When `cell_name` and `equivalent_ports` are given, equivalent ports
    /// are also collapsed to a single canonical port name and nets that share
    /// a canonical reference are merged.
    pub fn normalize(
        &self,
        cell_name: Option<String>,
        equivalent_ports: Option<EquivalentPorts>,
        port_mapping: Option<PortMapping>,
    ) -> Result<Self> {
        let mut nl = self.clone();

        if let (Some(cell_name), Some(equivalent_ports)) = (cell_name, equivalent_ports) {
            let mut port_mapping: HashMap<String, HashMap<String, String>> = match port_mapping {
                Some(mapping) => mapping,
                _ => {
                    let mut m: HashMap<String, HashMap<String, String>> = HashMap::new();
                    for (cell, lists) in &equivalent_ports {
                        let entry = m.entry(cell.clone()).or_default();
                        for port_list in lists {
                            if let Some(canonical) = port_list.first() {
                                for port in port_list {
                                    entry.insert(port.clone(), canonical.clone());
                                }
                            }
                        }
                    }
                    m
                }
            };

            let matched_insts: HashSet<String> = nl
                .instances
                .iter()
                .filter(|(_, inst)| equivalent_ports.contains_key(&inst.component))
                .map(|(name, _)| name.clone())
                .collect();

            let mut canonical_groups: HashMap<CanonicalKey, Vec<usize>> = HashMap::new();
            let mut changed_net: Vec<bool> = vec![false; nl.nets.len()];

            for (net_idx, net) in nl.nets.iter_mut().enumerate() {
                for member in net.members.iter_mut() {
                    let (instance, port_name_ref): (&str, &mut String) = match member {
                        NetMember::Ref(r) => (r.instance.as_str(), &mut r.port),
                        NetMember::ArrayRef(r) => (r.instance.as_str(), &mut r.port),
                        NetMember::Port(_) => continue,
                    };
                    if !matched_insts.contains(instance) {
                        continue;
                    }
                    let component = &nl_component_lookup(&nl.instances, instance);
                    let Some(mapping) = port_mapping.get(component) else {
                        continue;
                    };
                    let Some(canonical) = mapping.get(port_name_ref.as_str()) else {
                        continue;
                    };
                    let canonical = canonical.clone();
                    *port_name_ref = canonical.clone();
                    changed_net[net_idx] = true;
                    let key = match member {
                        NetMember::Ref(r) => CanonicalKey::Ref {
                            instance: r.instance.clone(),
                            port: r.port.clone(),
                        },
                        NetMember::ArrayRef(r) => CanonicalKey::ArrayRef {
                            instance: r.instance.clone(),
                            port: r.port.clone(),
                            ia: r.ia,
                            ib: r.ib,
                        },
                        NetMember::Port(_) => unreachable!(),
                    };
                    canonical_groups.entry(key).or_default().push(net_idx);
                }
            }

            let mut uf = UnionFind::new(nl.nets.len());
            for indices in canonical_groups.values() {
                if indices.len() < 2 {
                    continue;
                }
                let first = indices[0];
                for &i in &indices[1..] {
                    uf.union(first, i);
                }
            }

            let port_index_by_name: HashMap<String, NetlistPort> = nl
                .ports
                .iter()
                .map(|p| (p.name.clone(), p.clone()))
                .collect();

            let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
            for (idx, &is_changed) in changed_net.iter().enumerate() {
                if !is_changed {
                    continue;
                }
                let root = uf.find(idx);
                groups.entry(root).or_default().push(idx);
            }

            let mut deleted: HashSet<usize> = HashSet::new();
            let mut new_nets: Vec<Net> = Vec::new();
            let cell_mapping = port_mapping.entry(cell_name).or_default().clone();

            for idxs in groups.values() {
                let mut seen: HashSet<NetMember> = HashSet::new();
                for &i in idxs {
                    deleted.insert(i);
                    for m in &nl.nets[i].members {
                        let resolved = match m {
                            NetMember::Port(p) => match cell_mapping.get(&p.name) {
                                Some(canon) => match port_index_by_name.get(canon) {
                                    Some(np) => NetMember::Port(np.clone()),
                                    None => {
                                        return Err(Error::MissingCanonicalPort(canon.clone()));
                                    }
                                },
                                None => NetMember::Port(p.clone()),
                            },
                            other => other.clone(),
                        };
                        seen.insert(resolved);
                    }
                }
                new_nets.push(Net::from_members(seen.into_iter().collect()));
            }

            let mut surviving: Vec<Net> = Vec::with_capacity(nl.nets.len());
            for (i, n) in nl.nets.drain(..).enumerate() {
                if !deleted.contains(&i) {
                    surviving.push(n);
                }
            }
            surviving.extend(new_nets);
            nl.nets = surviving;

            let mut seen_ports: HashSet<NetlistPort> = HashSet::new();
            nl.ports.retain(|p| seen_ports.insert(p.clone()));
        }

        nl.normalize_settings();
        nl.sort();
        Ok(nl)
    }
}
fn nl_component_lookup(
    instances: &indexmap::IndexMap<String, NetlistInstance>,
    name: &str,
) -> String {
    instances
        .get(name)
        .map(|i| i.component.clone())
        .unwrap_or_default()
}

#[derive(Clone, Debug, Hash, PartialEq, Eq)]
enum CanonicalKey {
    Ref {
        instance: String,
        port: String,
    },
    ArrayRef {
        instance: String,
        port: String,
        ia: i64,
        ib: i64,
    },
}

/// Classic union-find with path compression and union-by-rank.
pub(crate) struct UnionFind {
    parent: Vec<usize>,
    rank: Vec<u8>,
}

impl UnionFind {
    pub(crate) fn new(n: usize) -> Self {
        Self {
            parent: (0..n).collect(),
            rank: vec![0; n],
        }
    }

    pub(crate) fn find(&mut self, mut x: usize) -> usize {
        while self.parent[x] != x {
            self.parent[x] = self.parent[self.parent[x]];
            x = self.parent[x];
        }
        x
    }

    pub(crate) fn union(&mut self, a: usize, b: usize) {
        let ra = self.find(a);
        let rb = self.find(b);
        if ra == rb {
            return;
        }
        match self.rank[ra].cmp(&self.rank[rb]) {
            std::cmp::Ordering::Less => self.parent[ra] = rb,
            std::cmp::Ordering::Greater => self.parent[rb] = ra,
            std::cmp::Ordering::Equal => {
                self.parent[rb] = ra;
                self.rank[ra] += 1;
            }
        }
    }
}

/// Equivalent port groups keyed by component name; first port is canonical.
pub type EquivalentPorts = HashMap<String, Vec<Vec<String>>>;
/// Explicit canonical port names keyed by component and original port name.
pub type PortMapping = HashMap<String, HashMap<String, String>>;
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Opens {
    pub unconnected_ports: Vec<String>,
    pub singleton_nets: Vec<Net>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetDifference {
    pub missing: Vec<Net>,
    pub extra: Vec<Net>,
}
impl PartialEq for Netlist {
    fn eq(&self, other: &Self) -> bool {
        self.equals(other)
    }
}
impl From<NetlistWire> for Netlist {
    fn from(wire: NetlistWire) -> Self {
        Self::from_wire(wire)
    }
}
impl From<Netlist> for NetlistWire {
    fn from(value: Netlist) -> Self {
        value.to_wire()
    }
}
