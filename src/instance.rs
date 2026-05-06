use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::PyType;
use serde::{Deserialize, Serialize};

use crate::{cmp_to_py, from_py_any, hash64, json_parse, json_string, to_py_dict};

/// Array dimensions for an array instance (`na` × `nb`).
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug, Hash, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NetlistArray {
    #[pyo3(get, set)]
    pub na: i64,
    #[pyo3(get, set)]
    pub nb: i64,
}

#[pymethods]
impl NetlistArray {
    #[new]
    #[pyo3(signature = (na, nb))]
    fn new(na: i64, nb: i64) -> Self {
        Self { na, nb }
    }

    fn __hash__(&self) -> u64 {
        hash64(&(self.na, self.nb))
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> PyResult<PyObject> {
        let py = other.py();
        let Ok(other) = other.downcast::<NetlistArray>() else {
            return Ok(py.NotImplemented());
        };
        let other = other.borrow();
        let eq = self.na == other.na && self.nb == other.nb;
        Ok(crate::richcmp_result(py, Some(cmp_to_py(op, false, eq))))
    }

    fn __repr__(&self) -> String {
        format!("NetlistArray(na={}, nb={})", self.na, self.nb)
    }

    fn to_json(&self) -> PyResult<String> {
        json_string(self)
    }

    #[classmethod]
    fn from_json(_cls: &Bound<'_, PyType>, data: &str) -> PyResult<Self> {
        json_parse(data)
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, self)
    }

    #[classmethod]
    fn from_dict(_cls: &Bound<'_, PyType>, obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        from_py_any(obj)
    }
}

/// Instance of a sub-cell within a netlist.
///
/// `name` is set by the parent `Netlist` from the dict key on deserialization
/// and is intentionally excluded from the JSON wire format.
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug)]
pub struct NetlistInstance {
    #[pyo3(get, set)]
    pub kcl: String,
    #[pyo3(get, set)]
    pub component: String,
    /// Free-form JSON-serializable settings.
    pub settings: serde_json::Value,
    pub array: Option<NetlistArray>,
    #[pyo3(get, set)]
    pub name: String,
}

/// Wire format used by serde to (de)serialize NetlistInstance without `name`.
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NetlistInstanceWire {
    pub kcl: String,
    pub component: String,
    #[serde(default)]
    pub settings: serde_json::Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub array: Option<NetlistArray>,
}

impl NetlistInstance {
    pub(crate) fn to_wire(&self) -> NetlistInstanceWire {
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

    pub(crate) fn from_wire(name: String, wire: NetlistInstanceWire) -> Self {
        Self {
            kcl: wire.kcl,
            component: wire.component,
            settings: wire.settings,
            array: wire.array,
            name,
        }
    }
}

#[pymethods]
impl NetlistInstance {
    #[new]
    #[pyo3(signature = (kcl, component, settings=None, array=None, name=String::new()))]
    fn new(
        py: Python<'_>,
        kcl: String,
        component: String,
        settings: Option<&Bound<'_, PyAny>>,
        array: Option<NetlistArray>,
        name: String,
    ) -> PyResult<Self> {
        let settings = match settings {
            Some(obj) if !obj.is_none() => from_py_any::<serde_json::Value>(obj)?,
            _ => serde_json::Value::Object(Default::default()),
        };
        let _ = py;
        Ok(Self {
            kcl,
            component,
            settings,
            array,
            name,
        })
    }

    #[getter]
    fn settings<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, &self.settings)
    }

    #[setter]
    fn set_settings(&mut self, value: &Bound<'_, PyAny>) -> PyResult<()> {
        self.settings = from_py_any(value)?;
        Ok(())
    }

    #[getter]
    fn array(&self) -> Option<NetlistArray> {
        self.array.clone()
    }

    #[setter]
    fn set_array(&mut self, value: Option<NetlistArray>) {
        self.array = value;
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> PyResult<PyObject> {
        let py = other.py();
        let Ok(other) = other.downcast::<NetlistInstance>() else {
            return Ok(py.NotImplemented());
        };
        let other = other.borrow();
        let eq = self.kcl == other.kcl
            && self.component == other.component
            && self.settings == other.settings
            && self.array == other.array
            && self.name == other.name;
        Ok(crate::richcmp_result(py, Some(cmp_to_py(op, false, eq))))
    }

    fn __repr__(&self) -> String {
        format!(
            "NetlistInstance(name={:?}, kcl={:?}, component={:?})",
            self.name, self.kcl, self.component
        )
    }

    fn to_json(&self) -> PyResult<String> {
        json_string(&self.to_wire())
    }

    #[classmethod]
    #[pyo3(signature = (data, name=String::new()))]
    fn from_json(_cls: &Bound<'_, PyType>, data: &str, name: String) -> PyResult<Self> {
        let wire: NetlistInstanceWire = json_parse(data)?;
        Ok(Self::from_wire(name, wire))
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, &self.to_wire())
    }

    #[classmethod]
    #[pyo3(signature = (obj, name=String::new()))]
    fn from_dict(
        _cls: &Bound<'_, PyType>,
        obj: &Bound<'_, PyAny>,
        name: String,
    ) -> PyResult<Self> {
        let wire: NetlistInstanceWire = from_py_any(obj)?;
        Ok(Self::from_wire(name, wire))
    }
}
