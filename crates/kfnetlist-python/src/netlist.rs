use crate::instance::NetlistInstance;
use crate::net::{Net, NetMember, NetMemberPython};
use crate::port::NetlistPort;
use crate::{
    cmp_to_py, core_error, from_py_any, json_parse, json_string, richcmp_result, to_py_dict,
};
use kfnetlist_core::netlist::NetlistWire;
use pyo3::basic::CompareOp;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyType};

/// A netlist: instances, nets, and top-level ports.
///
/// Declared `subclass` so `PlacedNetlist` (which carries per-instance placement
/// geometry) can extend it; this adds no fields and does not change the wire
/// format.
#[pyclass(module = "kfnetlist._native", subclass)]
#[derive(Default, Debug)]
pub struct Netlist(pub kfnetlist_core::Netlist);
crate::core_wrapper!(Netlist, kfnetlist_core::Netlist);

impl Netlist {
    pub(crate) fn deep_clone(&self) -> Self {
        Self(self.0.clone())
    }
    fn from_wire(wire: NetlistWire) -> Self {
        Self(kfnetlist_core::Netlist::from_wire(wire))
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
    /// affect the netlist; contained instances are independent snapshots as well.
    #[getter]
    fn instances<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (name, inst) in &self.instances {
            dict.set_item(name, Py::new(py, NetlistInstance(inst.clone()))?)?;
        }
        Ok(dict)
    }

    /// Fresh list of nets. Mutating this list does not affect the netlist.
    #[getter]
    fn nets<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let list = PyList::empty(py);
        for net in &self.nets {
            list.append(Py::new(py, Net(net.clone()))?)?;
        }
        Ok(list)
    }

    /// Fresh list of top-level ports.
    #[getter]
    fn ports<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let list = PyList::empty(py);
        for p in &self.ports {
            list.append(Py::new(py, NetlistPort(p.clone()))?)?;
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
        self.0
            .get_instance(name)
            .map(NetlistInstance)
            .map_err(core_error)
    }

    // ---- Mutation ----

    fn create_port(&mut self, name: String) -> NetlistPort {
        NetlistPort(self.0.create_port(name))
    }

    #[pyo3(signature = (name, kcl, component, settings=None, na=1, nb=1))]
    pub(crate) fn create_inst(
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
        self.0
            .create_inst(name, kcl, component, settings_value, na, nb)
            .map(NetlistInstance)
            .map_err(core_error)
    }

    #[pyo3(signature = (*ports))]
    fn create_net(&mut self, ports: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut members = Vec::new();
        for item in ports.try_iter()? {
            members.push(NetMember::from_py(&item?).map_err(|_| {
                PyValueError::new_err("create_net expects NetlistPort, PortRef, or PortArrayRef")
            })?);
        }
        self.0.create_net(members).map_err(core_error)
    }

    /// Re-create a net using the members of an existing one.
    fn add_net(&mut self, net: &Net) -> PyResult<()> {
        self.0.add_net(&net.0).map_err(core_error)
    }

    /// Remove the named instances and merge any nets touching them into
    /// a single new net (per group of nets that referenced the same flattened
    /// instance), preserving every non-flattened port reference.
    pub(crate) fn flatten_instances(&mut self, names: Vec<String>) -> PyResult<()> {
        self.0.flatten_instances(names).map_err(core_error)
    }

    /// Detect open (unconnected) elements in this netlist.
    ///
    /// Returns a dict with:
    /// - ``unconnected_ports``: top-level port names not appearing in any net
    /// - ``singleton_nets``: nets with only a single member (dangling stubs)
    fn detect_opens<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let opens = self.0.detect_opens();
        let singletons = PyList::empty(py);
        for net in opens.singleton_nets {
            singletons.append(Py::new(py, Net(net))?)?;
        }
        let dict = PyDict::new(py);
        dict.set_item("unconnected_ports", opens.unconnected_ports)?;
        dict.set_item("singleton_nets", singletons)?;
        Ok(dict)
    }

    /// Return a dict with ``missing`` and ``extra`` net lists.
    ///
    /// * **missing** – nets in *reference* but not in ``self``
    /// * **extra** – nets in ``self`` but not in *reference*
    fn find_net_difference<'py>(
        &self,
        py: Python<'py>,
        reference: &Netlist,
    ) -> PyResult<Bound<'py, PyDict>> {
        let difference = self.0.find_net_difference(&reference.0);
        let missing = PyList::empty(py);
        for net in difference.missing {
            missing.append(Py::new(py, Net(net))?)?;
        }
        let extra = PyList::empty(py);
        for net in difference.extra {
            extra.append(Py::new(py, Net(net))?)?;
        }
        let dict = PyDict::new(py);
        dict.set_item("missing", missing)?;
        dict.set_item("extra", extra)?;
        Ok(dict)
    }

    /// Sort instances by name, ports by name, members within each net,
    /// and the nets list itself.
    fn sort(&mut self) {
        self.0.sort();
    }

    /// Return a deep copy of the netlist with normalized settings (integer-
    /// valued floats become integers) and sorted contents.
    ///
    /// When `cell_name` and `equivalent_ports` are given, equivalent ports
    /// are also collapsed to a single canonical port name and nets that share
    /// a canonical reference are merged.
    #[pyo3(signature = (cell_name=None, equivalent_ports=None, port_mapping=None))]
    fn normalize(
        &self,
        py: Python<'_>,
        cell_name: Option<String>,
        equivalent_ports: Option<&Bound<'_, PyAny>>,
        port_mapping: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let _ = py;
        // Historically equivalent_ports is parsed only when cell_name is supplied,
        // and port_mapping is parsed only when both are supplied.
        let equivalent_ports = if cell_name.is_some() {
            equivalent_ports.map(from_py_any).transpose()?
        } else {
            None
        };
        let port_mapping = if equivalent_ports.is_some() {
            port_mapping
                .filter(|obj| !obj.is_none())
                .map(from_py_any)
                .transpose()?
        } else {
            None
        };
        self.0
            .normalize(cell_name, equivalent_ports, port_mapping)
            .map(Self)
            .map_err(core_error)
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> PyResult<PyObject> {
        let py = other.py();
        let Ok(other) = other.downcast::<Netlist>() else {
            return Ok(py.NotImplemented());
        };
        let other = other.borrow();
        let eq = self.0 == other.0;
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
