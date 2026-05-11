use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::PyType;
use serde::{Deserialize, Serialize};

use crate::{
    cmp_to_py, from_py_any, hash64, json_parse, json_string, py_repr, richcmp_result, to_py_dict,
};

/// Cell-level port of a netlist (top-level pin).
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NetlistPort {
    #[pyo3(get, set)]
    pub name: String,
}

/// Reference to a port on an instance.
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortRef {
    #[pyo3(get, set)]
    pub instance: String,
    #[pyo3(get, set)]
    pub port: String,
}

/// Reference to a port on an array instance.
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortArrayRef {
    #[pyo3(get, set)]
    pub instance: String,
    #[pyo3(get, set)]
    pub port: String,
    #[pyo3(get, set)]
    pub ia: i64,
    #[pyo3(get, set)]
    pub ib: i64,
}

// Type-tag ordering: NetlistPort (0) < PortRef (1) < PortArrayRef (2).
const KIND_NETLIST_PORT: u8 = 0;
const KIND_PORT_REF: u8 = 1;
const KIND_PORT_ARRAY_REF: u8 = 2;

fn kind_of(obj: &Bound<'_, PyAny>) -> Option<u8> {
    if obj.downcast::<NetlistPort>().is_ok() {
        Some(KIND_NETLIST_PORT)
    } else if obj.downcast::<PortArrayRef>().is_ok() {
        Some(KIND_PORT_ARRAY_REF)
    } else if obj.downcast::<PortRef>().is_ok() {
        Some(KIND_PORT_REF)
    } else {
        None
    }
}

#[pymethods]
impl NetlistPort {
    #[new]
    #[pyo3(signature = (name))]
    fn new(name: String) -> Self {
        Self { name }
    }

    fn __hash__(&self) -> u64 {
        hash64(&self.name)
    }

    fn __richcmp__(&self, py: Python<'_>, other: &Bound<'_, PyAny>, op: CompareOp) -> PyObject {
        let kind = match kind_of(other) {
            Some(k) => k,
            None => return richcmp_result(py, None),
        };
        let (lt, eq) = match kind {
            KIND_NETLIST_PORT => {
                let other = other.downcast::<NetlistPort>().unwrap().borrow();
                (self.name < other.name, self.name == other.name)
            }
            // NetlistPort always sorts before PortRef / PortArrayRef.
            _ => (true, false),
        };
        richcmp_result(py, Some(cmp_to_py(op, lt, eq)))
    }

    fn __repr__(&self) -> String {
        format!("NetlistPort(name={})", py_repr(&self.name))
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

#[pymethods]
impl PortRef {
    #[new]
    #[pyo3(signature = (instance, port))]
    fn new(instance: String, port: String) -> Self {
        Self { instance, port }
    }

    fn __hash__(&self) -> u64 {
        hash64(&(&self.instance, &self.port))
    }

    fn __richcmp__(&self, py: Python<'_>, other: &Bound<'_, PyAny>, op: CompareOp) -> PyObject {
        let kind = match kind_of(other) {
            Some(k) => k,
            None => return richcmp_result(py, None),
        };
        let (lt, eq) = match kind {
            KIND_NETLIST_PORT => (false, false),
            KIND_PORT_REF => {
                let other = other.downcast::<PortRef>().unwrap().borrow();
                let s = (&self.instance, &self.port);
                let o = (&other.instance, &other.port);
                (s < o, s == o)
            }
            KIND_PORT_ARRAY_REF => (true, false),
            _ => unreachable!(),
        };
        richcmp_result(py, Some(cmp_to_py(op, lt, eq)))
    }

    fn __repr__(&self) -> String {
        format!(
            "PortRef(instance={}, port={})",
            py_repr(&self.instance),
            py_repr(&self.port)
        )
    }

    fn __str__(&self) -> String {
        self.as_python_str(None)
    }

    #[pyo3(signature = (inst_name=None))]
    fn as_python_str(&self, inst_name: Option<String>) -> String {
        let inst = inst_name.unwrap_or_else(|| self.instance.clone());
        format!("{}[{}]", inst, py_repr(&self.port))
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

#[pymethods]
impl PortArrayRef {
    #[new]
    #[pyo3(signature = (instance, port, ia, ib))]
    fn new(instance: String, port: String, ia: i64, ib: i64) -> Self {
        Self {
            instance,
            port,
            ia,
            ib,
        }
    }

    fn __hash__(&self) -> u64 {
        hash64(&(&self.instance, &self.port, self.ia, self.ib))
    }

    fn __richcmp__(&self, py: Python<'_>, other: &Bound<'_, PyAny>, op: CompareOp) -> PyObject {
        let kind = match kind_of(other) {
            Some(k) => k,
            None => return richcmp_result(py, None),
        };
        let (lt, eq) = match kind {
            KIND_NETLIST_PORT | KIND_PORT_REF => (false, false),
            KIND_PORT_ARRAY_REF => {
                let other = other.downcast::<PortArrayRef>().unwrap().borrow();
                let s = (&self.instance, &self.port, self.ia, self.ib);
                let o = (&other.instance, &other.port, other.ia, other.ib);
                (s < o, s == o)
            }
            _ => unreachable!(),
        };
        richcmp_result(py, Some(cmp_to_py(op, lt, eq)))
    }

    fn __repr__(&self) -> String {
        format!(
            "PortArrayRef(instance={}, port={}, ia={}, ib={})",
            py_repr(&self.instance),
            py_repr(&self.port),
            self.ia,
            self.ib
        )
    }

    fn __str__(&self) -> String {
        self.as_python_str(None)
    }

    #[pyo3(signature = (inst_name=None))]
    fn as_python_str(&self, inst_name: Option<String>) -> String {
        let inst = inst_name.unwrap_or_else(|| self.instance.clone());
        format!(
            "{}[{}, {}, {}]",
            inst,
            py_repr(&self.port),
            self.ia,
            self.ib
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
