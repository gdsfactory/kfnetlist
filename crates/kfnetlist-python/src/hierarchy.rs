//! Python ownership and mapping interface for a validated Rust hierarchy.

use indexmap::IndexMap;
use kfnetlist_core::{
    FlattenOptions, HierarchicalNetlist as CoreHierarchy, Netlist as CoreNetlist,
};
use pyo3::exceptions::{PyKeyError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyType};

use crate::netlist::Netlist;
use crate::{core_error, from_py_any, to_py_dict};

/// An ordered document of mutable plain netlists.
///
/// Child handles are live. Call `validate()` after editing one; operations that
/// consume the complete hierarchy validate before they run.
#[pyclass(module = "kfnetlist._native")]
#[derive(Default)]
pub struct HierarchicalNetlist {
    pub(crate) netlists: IndexMap<String, Py<Netlist>>,
}

impl HierarchicalNetlist {
    pub(crate) fn to_core(&self, py: Python<'_>) -> PyResult<CoreHierarchy> {
        let netlists = self
            .netlists
            .iter()
            .map(|(name, netlist)| (name.clone(), netlist.borrow(py).0.clone()))
            .collect();
        CoreHierarchy::from_netlists(netlists).map_err(core_error)
    }

    fn from_core(py: Python<'_>, core: CoreHierarchy) -> PyResult<Self> {
        let mut netlists = IndexMap::new();
        for (name, netlist) in core.iter() {
            netlists.insert(name.clone(), Py::new(py, Netlist(netlist.clone()))?);
        }
        Ok(Self { netlists })
    }

    fn read_mapping(py: Python<'_>, mapping: &Bound<'_, PyAny>) -> PyResult<Self> {
        let dict = mapping.downcast::<PyDict>().map_err(|_| {
            PyTypeError::new_err("HierarchicalNetlist expects a dict of netlist IDs to Netlist")
        })?;
        let mut netlists = IndexMap::new();
        for (key, value) in dict.iter() {
            let name: String = key
                .extract()
                .map_err(|_| PyTypeError::new_err("hierarchy netlist IDs must be strings"))?;
            let netlist = if value.get_type().is(&py.get_type::<Netlist>()) {
                value.extract::<Py<Netlist>>()?
            } else if value.is_instance_of::<PyDict>() {
                let wire: kfnetlist_core::netlist::NetlistWire = from_py_any(&value)?;
                Py::new(py, Netlist(CoreNetlist::from_wire(wire)))?
            } else {
                return Err(PyTypeError::new_err(format!(
                    "netlist {name:?} must be a plain Netlist or a netlist dict"
                )));
            };
            netlists.insert(name, netlist);
        }
        let hierarchy = Self { netlists };
        hierarchy.to_core(py)?;
        Ok(hierarchy)
    }
}

#[pymethods]
impl HierarchicalNetlist {
    #[new]
    #[pyo3(signature = (netlists=None))]
    fn new(py: Python<'_>, netlists: Option<&Bound<'_, PyAny>>) -> PyResult<Self> {
        match netlists {
            Some(value) => Self::read_mapping(py, value),
            None => Ok(Self::default()),
        }
    }

    fn validate(&self, py: Python<'_>) -> PyResult<()> {
        self.to_core(py)?;
        Ok(())
    }

    fn __len__(&self) -> usize {
        self.netlists.len()
    }

    fn __contains__(&self, key: &str) -> bool {
        self.netlists.contains_key(key)
    }

    fn __getitem__(&self, py: Python<'_>, key: &str) -> PyResult<Py<Netlist>> {
        self.netlists
            .get(key)
            .map(|value| value.clone_ref(py))
            .ok_or_else(|| PyKeyError::new_err(key.to_string()))
    }

    fn __setitem__(
        &mut self,
        py: Python<'_>,
        key: String,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        if !value.get_type().is(&py.get_type::<Netlist>()) {
            return Err(PyTypeError::new_err(
                "hierarchy values must be plain Netlist objects",
            ));
        }
        self.netlists.insert(key, value.extract::<Py<Netlist>>()?);
        Ok(())
    }

    fn __delitem__(&mut self, key: &str) -> PyResult<()> {
        self.netlists
            .shift_remove(key)
            .map(|_| ())
            .ok_or_else(|| PyKeyError::new_err(key.to_string()))
    }

    fn keys(&self) -> Vec<String> {
        self.netlists.keys().cloned().collect()
    }

    fn values(&self, py: Python<'_>) -> Vec<Py<Netlist>> {
        self.netlists.values().map(|nl| nl.clone_ref(py)).collect()
    }

    fn items(&self, py: Python<'_>) -> Vec<(String, Py<Netlist>)> {
        self.netlists
            .iter()
            .map(|(name, nl)| (name.clone(), nl.clone_ref(py)))
            .collect()
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(PyList::new(py, self.netlists.keys())?
            .call_method0("__iter__")?
            .unbind())
    }

    fn __repr__(&self) -> String {
        format!("HierarchicalNetlist(netlists={})", self.netlists.len())
    }

    #[classmethod]
    fn __get_pydantic_core_schema__(
        cls: &Bound<'_, PyType>,
        _source_type: &Bound<'_, PyAny>,
        _handler: &Bound<'_, PyAny>,
    ) -> PyResult<PyObject> {
        crate::pydantic_core_schema(cls)
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        self.validate(py)?;
        let out = PyDict::new(py);
        for (name, netlist) in &self.netlists {
            out.set_item(name, to_py_dict(py, &netlist.borrow(py).0.to_wire())?)?;
        }
        Ok(out)
    }

    #[classmethod]
    fn from_dict(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        data: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        Self::read_mapping(py, data)
    }

    fn to_json(&self, py: Python<'_>) -> PyResult<String> {
        self.to_core(py)?.to_json().map_err(core_error)
    }

    #[classmethod]
    fn from_json(_cls: &Bound<'_, PyType>, py: Python<'_>, data: &str) -> PyResult<Self> {
        let core = kfnetlist_core::hierarchy_from_json(data).map_err(core_error)?;
        Self::from_core(py, core)
    }

    /// Inline referenced child netlists in one named root.
    #[pyo3(signature = (root, *, exclude=None, recursive=true, allow_unconnected_ports=false, separator=".".to_string()))]
    fn flatten(
        &self,
        py: Python<'_>,
        root: &str,
        exclude: Option<Vec<String>>,
        recursive: bool,
        allow_unconnected_ports: bool,
        separator: String,
    ) -> PyResult<Netlist> {
        let options = FlattenOptions::new(
            None,
            exclude,
            recursive,
            allow_unconnected_ports,
            false,
            separator,
        );
        self.to_core(py)?
            .flatten(root, &options)
            .map(Netlist)
            .map_err(core_error)
    }

    /// Return a new document with every entry flattened against the original.
    #[pyo3(signature = (*, exclude=None, recursive=true, allow_unconnected_ports=false, separator=".".to_string()))]
    fn flatten_all(
        &self,
        py: Python<'_>,
        exclude: Option<Vec<String>>,
        recursive: bool,
        allow_unconnected_ports: bool,
        separator: String,
    ) -> PyResult<Self> {
        let core = self.to_core(py)?;
        let options = FlattenOptions::new(
            None,
            exclude,
            recursive,
            allow_unconnected_ports,
            false,
            separator,
        );
        let mut netlists = IndexMap::new();
        for name in core.keys() {
            let flat = core.flatten(name, &options).map_err(core_error)?;
            netlists.insert(name.clone(), Py::new(py, Netlist(flat))?);
        }
        let hierarchy = Self { netlists };
        hierarchy.validate(py)?;
        Ok(hierarchy)
    }
}
