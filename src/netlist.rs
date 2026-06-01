use std::collections::{HashMap, HashSet};

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyType};
use serde::{Deserialize, Serialize};

use crate::instance::{NetlistArray, NetlistInstance, NetlistInstanceWire};
use crate::net::{Net, NetMember};
use crate::port::{NetlistPort, PortArrayRef, PortArrayRefData, PortRef};
use crate::{cmp_to_py, from_py_any, json_parse, json_string, richcmp_result, to_py_dict};

/// Wire format used by serde for `Netlist`. Mirrors the JSON shape but
/// stores instances by name without redundant `name` fields.
#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NetlistWire {
    #[serde(default)]
    pub instances: indexmap::IndexMap<String, NetlistInstanceWire>,
    #[serde(default)]
    pub nets: Vec<Net>,
    #[serde(default)]
    pub ports: Vec<NetlistPort>,
}

/// A netlist: instances, nets, and top-level ports.
#[pyclass(module = "kfnetlist._native")]
#[derive(Default, Debug)]
pub struct Netlist {
    /// Instance name → instance. Insertion order preserved.
    pub instances: indexmap::IndexMap<String, NetlistInstance>,
    pub nets: Vec<Net>,
    pub ports: Vec<NetlistPort>,
}

impl Netlist {
    fn deep_clone(&self) -> Self {
        Netlist {
            instances: self
                .instances
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
            nets: self.nets.clone(),
            ports: self.ports.clone(),
        }
    }

    fn to_wire(&self) -> NetlistWire {
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

    fn from_wire(wire: NetlistWire) -> Self {
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

#[pymethods]
impl Netlist {
    #[new]
    fn new() -> Self {
        Netlist::default()
    }

    // ---- Properties returning fresh snapshots ----

    /// Fresh dict of {name: NetlistInstance}. Mutating this dict does not
    /// affect the netlist; mutating the contained NetlistInstance does.
    #[getter]
    fn instances<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (name, inst) in &self.instances {
            dict.set_item(name, Py::new(py, inst.clone())?)?;
        }
        Ok(dict)
    }

    /// Fresh list of nets. Mutating this list does not affect the netlist.
    #[getter]
    fn nets<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let list = PyList::empty(py);
        for net in &self.nets {
            list.append(Py::new(py, net.clone())?)?;
        }
        Ok(list)
    }

    /// Fresh list of top-level ports.
    #[getter]
    fn ports<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let list = PyList::empty(py);
        for p in &self.ports {
            list.append(Py::new(py, p.clone())?)?;
        }
        Ok(list)
    }

    fn instance_names(&self) -> Vec<String> {
        self.instances.keys().cloned().collect()
    }

    fn has_instance(&self, name: &str) -> bool {
        self.instances.contains_key(name)
    }

    fn get_instance(&self, name: &str) -> PyResult<NetlistInstance> {
        self.instances
            .get(name)
            .cloned()
            .ok_or_else(|| PyKeyError::new_err(name.to_string()))
    }

    // ---- Mutation ----

    fn create_port(&mut self, name: String) -> NetlistPort {
        let p = NetlistPort { name };
        self.ports.push(p.clone());
        p
    }

    #[pyo3(signature = (name, kcl, component, settings=None, na=1, nb=1))]
    fn create_inst(
        &mut self,
        name: String,
        kcl: String,
        component: String,
        settings: Option<&Bound<'_, PyAny>>,
        na: i64,
        nb: i64,
    ) -> PyResult<NetlistInstance> {
        let settings_value = match settings {
            Some(obj) if !obj.is_none() => from_py_any::<serde_json::Value>(obj)?,
            _ => serde_json::Value::Object(Default::default()),
        };
        let array = if na != 0 && nb != 0 {
            if na < 1 || nb < 1 {
                return Err(PyValueError::new_err(format!(
                    "An instance array must have at least one instance in the array. \
                     na={na} and nb={nb} must be >= 1"
                )));
            }
            Some(NetlistArray { na, nb })
        } else {
            None
        };
        let inst = NetlistInstance {
            kcl,
            component,
            settings: settings_value,
            array,
            name: name.clone(),
        };
        self.instances.insert(name, inst.clone());
        Ok(inst)
    }

    #[pyo3(signature = (*ports))]
    fn create_net(&mut self, ports: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut members: Vec<NetMember> = Vec::new();
        let iter = ports.try_iter()?;
        for item in iter {
            let item = item?;
            // PortArrayRef must be checked before PortRef because it
            // inherits from it.
            if let Ok(b) = item.downcast::<PortArrayRef>() {
                let par = PortArrayRefData::from_py(b);
                let inst = self.instances.get(&par.instance).ok_or_else(|| {
                    PyValueError::new_err(format!("Unknown instance {}", par.instance))
                })?;
                if par.ia == 1 && par.ib == 1 {
                    members.push(NetMember::Ref(PortRef {
                        instance: par.instance,
                        port: par.port,
                    }));
                    continue;
                }
                let array = inst.array.as_ref().ok_or_else(|| {
                    PyValueError::new_err(format!(
                        "Instance {} is not an array instance. \
                         But an array portref was requested {:?}",
                        par.instance, par
                    ))
                })?;
                if par.ia > array.na {
                    return Err(PyValueError::new_err(format!(
                        "Instance {} has only {} elements in `na` direction",
                        par.instance, array.na
                    )));
                }
                if par.ib > array.nb {
                    return Err(PyValueError::new_err(format!(
                        "Instance {} has only {} elements in `nb` direction",
                        par.instance, array.nb
                    )));
                }
                members.push(NetMember::ArrayRef(par));
            } else if let Ok(b) = item.downcast::<PortRef>() {
                let pr = b.borrow().clone();
                if !self.instances.contains_key(&pr.instance) {
                    return Err(PyValueError::new_err(format!(
                        "Unknown instance {}",
                        pr.instance
                    )));
                }
                members.push(NetMember::Ref(pr));
            } else if let Ok(b) = item.downcast::<NetlistPort>() {
                let np = b.borrow().clone();
                if !self.ports.iter().any(|p| p.name == np.name) {
                    return Err(PyValueError::new_err(format!(
                        "Undefined netlist port {}",
                        np.name
                    )));
                }
                members.push(NetMember::Port(NetlistPort { name: np.name }));
            } else {
                return Err(PyValueError::new_err(
                    "create_net expects NetlistPort, PortRef, or PortArrayRef",
                ));
            }
        }
        self.nets.push(Net::from_members(members));
        Ok(())
    }

    /// Re-create a net using the members of an existing one.
    fn add_net(&mut self, net: &Net) -> PyResult<()> {
        Python::with_gil(|py| {
            let list = PyList::empty(py);
            for m in &net.members {
                list.append(m.clone().into_py_obj(py)?)?;
            }
            self.create_net(list.as_any())
        })
    }

    /// Remove the named instances and merge any nets touching them into
    /// a single new net (per group of nets that referenced the same flattened
    /// instance), preserving every non-flattened port reference.
    fn flatten_instances(&mut self, names: Vec<String>) -> PyResult<()> {
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

    /// Detect open (unconnected) elements in this netlist.
    ///
    /// Returns a dict with:
    /// - ``unconnected_ports``: top-level port names not appearing in any net
    /// - ``singleton_nets``: nets with only a single member (dangling stubs)
    fn detect_opens<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let mut ports_in_nets: HashSet<String> = HashSet::new();
        for net in &self.nets {
            for m in &net.members {
                if let NetMember::Port(p) = m {
                    ports_in_nets.insert(p.name.clone());
                }
            }
        }
        let mut unconnected: Vec<String> = self
            .ports
            .iter()
            .filter(|p| !ports_in_nets.contains(&p.name))
            .map(|p| p.name.clone())
            .collect();
        unconnected.sort();

        let singleton_list = PyList::empty(py);
        for net in &self.nets {
            if net.members.len() == 1 {
                singleton_list.append(Py::new(py, net.clone())?)?;
            }
        }

        let dict = PyDict::new(py);
        dict.set_item("unconnected_ports", unconnected)?;
        dict.set_item("singleton_nets", singleton_list)?;
        Ok(dict)
    }

    /// Return nets present in *reference* but absent from ``self``.
    ///
    /// This is the set difference ``set(reference.nets) - set(self.nets)``
    /// and represents nets that should exist (according to the reference
    /// netlist / schematic) but were not found during extraction.
    fn find_open_nets<'py>(
        &self,
        py: Python<'py>,
        reference: &Netlist,
    ) -> PyResult<Bound<'py, PyList>> {
        let own: HashSet<&Net> = self.nets.iter().collect();
        let list = PyList::empty(py);
        for net in &reference.nets {
            if !own.contains(net) {
                list.append(Py::new(py, net.clone())?)?;
            }
        }
        Ok(list)
    }

    /// Sort instances by name, ports by name, members within each net,
    /// and the nets list itself.
    fn sort(&mut self) {
        self.instances.sort_keys();
        for net in &mut self.nets {
            net.sort_in_place();
        }
        self.nets.sort();
        self.ports.sort();
    }

    /// Return a deep copy of the netlist with equivalent ports collapsed
    /// to a single canonical port name. Nets that, after relabeling, share
    /// the same canonical port reference are merged.
    #[pyo3(signature = (cell_name, equivalent_ports, port_mapping=None))]
    fn lvs_equivalent(
        &self,
        py: Python<'_>,
        cell_name: String,
        equivalent_ports: &Bound<'_, PyAny>,
        port_mapping: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let _ = py;
        let equivalent_ports: HashMap<String, Vec<Vec<String>>> = from_py_any(equivalent_ports)?;
        let mut port_mapping: HashMap<String, HashMap<String, String>> = match port_mapping {
            Some(obj) if !obj.is_none() => from_py_any(obj)?,
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

        let mut nl = self.deep_clone();

        let matched_insts: HashSet<String> = nl
            .instances
            .iter()
            .filter(|(_, inst)| equivalent_ports.contains_key(&inst.component))
            .map(|(name, _)| name.clone())
            .collect();

        // Group changed nets by the canonical port reference they touch.
        // Nets that share a canonical key get merged via union-find.
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

        // Union-find over net indices.
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

        // Top-level port lookup keyed by name.
        let port_index_by_name: HashMap<String, NetlistPort> = nl
            .ports
            .iter()
            .map(|p| (p.name.clone(), p.clone()))
            .collect();

        // Group changed nets by their UF root and merge them.
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
        let cell_mapping = port_mapping.entry(cell_name.clone()).or_default().clone();

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
                                    return Err(PyValueError::new_err(format!(
                                        "lvs_equivalent: canonical port {canon:?} not present \
                                         in netlist ports"
                                    )));
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

        // Replace deleted nets with merged ones.
        let mut surviving: Vec<Net> = Vec::with_capacity(nl.nets.len());
        for (i, n) in nl.nets.drain(..).enumerate() {
            if !deleted.contains(&i) {
                surviving.push(n);
            }
        }
        surviving.extend(new_nets);
        nl.nets = surviving;

        // Dedupe ports (the cell-level mapping may have made some redundant).
        let mut seen_ports: HashSet<NetlistPort> = HashSet::new();
        nl.ports.retain(|p| seen_ports.insert(p.clone()));

        nl.sort();
        Ok(nl)
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> PyResult<PyObject> {
        let py = other.py();
        let Ok(other) = other.downcast::<Netlist>() else {
            return Ok(py.NotImplemented());
        };
        let other = other.borrow();
        let eq = self.equals(&other);
        Ok(richcmp_result(py, Some(cmp_to_py(op, false, eq))))
    }

    fn __repr__(&self) -> String {
        format!(
            "Netlist(instances={}, nets={}, ports={})",
            self.instances.len(),
            self.nets.len(),
            self.ports.len()
        )
    }

    #[classmethod]
    fn __get_pydantic_core_schema__(
        cls: &Bound<'_, PyType>,
        _source_type: &Bound<'_, PyAny>,
        _handler: &Bound<'_, PyAny>,
    ) -> PyResult<PyObject> {
        crate::pydantic_core_schema(cls)
    }

    fn to_json(&self) -> PyResult<String> {
        json_string(&self.to_wire())
    }

    #[classmethod]
    fn from_json(_cls: &Bound<'_, PyType>, data: &str) -> PyResult<Self> {
        let wire: NetlistWire = json_parse(data)?;
        Ok(Netlist::from_wire(wire))
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, &self.to_wire())
    }

    #[classmethod]
    fn from_dict(_cls: &Bound<'_, PyType>, obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        let wire: NetlistWire = from_py_any(obj)?;
        Ok(Netlist::from_wire(wire))
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
struct UnionFind {
    parent: Vec<usize>,
    rank: Vec<u8>,
}

impl UnionFind {
    fn new(n: usize) -> Self {
        Self {
            parent: (0..n).collect(),
            rank: vec![0; n],
        }
    }

    fn find(&mut self, mut x: usize) -> usize {
        while self.parent[x] != x {
            self.parent[x] = self.parent[self.parent[x]];
            x = self.parent[x];
        }
        x
    }

    fn union(&mut self, a: usize, b: usize) {
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
