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
///
/// `PortArrayRef` extends this class, so `isinstance(x, PortRef)` is true
/// for both plain and array references.
#[pyclass(module = "kfnetlist._native", subclass)]
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortRef {
    #[pyo3(get, set)]
    pub instance: String,
    #[pyo3(get, set)]
    pub port: String,
}

/// Reference to a port on an array instance.
///
/// Subclass of [`PortRef`]. The `instance` and `port` fields live on the
/// parent layer; only the array indices are stored on the child.
#[pyclass(module = "kfnetlist._native", extends = PortRef)]
#[derive(Clone, Debug)]
pub struct PortArrayRef {
    #[pyo3(get, set)]
    pub ia: i64,
    #[pyo3(get, set)]
    pub ib: i64,
}

/// Plain serializable view of a `PortArrayRef` — used by `NetMember` and
/// the JSON/dict round-trips, since the PyO3 child struct only stores the
/// indices.
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortArrayRefData {
    pub instance: String,
    pub port: String,
    pub ia: i64,
    pub ib: i64,
}

impl PortArrayRefData {
    /// Read all four fields from a Python `PortArrayRef` (parent + child).
    pub fn from_py(par: &Bound<'_, PortArrayRef>) -> Self {
        let child = par.borrow();
        let parent = child.as_ref();
        Self {
            instance: parent.instance.clone(),
            port: parent.port.clone(),
            ia: child.ia,
            ib: child.ib,
        }
    }

    /// Construct a fresh Python `PortArrayRef` carrying these fields.
    pub fn into_py(self, py: Python<'_>) -> PyResult<Py<PortArrayRef>> {
        let init = PyClassInitializer::from(PortRef {
            instance: self.instance,
            port: self.port,
        })
        .add_subclass(PortArrayRef {
            ia: self.ia,
            ib: self.ib,
        });
        Py::new(py, init)
    }
}

// Type-tag ordering: NetlistPort (0) < PortRef (1) < PortArrayRef (2).
const KIND_NETLIST_PORT: u8 = 0;
const KIND_PORT_REF: u8 = 1;
const KIND_PORT_ARRAY_REF: u8 = 2;

fn kind_of(obj: &Bound<'_, PyAny>) -> Option<u8> {
    // PortArrayRef must be checked before PortRef because it inherits from it.
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

    /// Alias for `port`, preserving the historical `.name` accessor from
    /// the pre-spinout pydantic `PortRef`. Inherited by `PortArrayRef`.
    #[getter]
    fn name(&self) -> String {
        self.port.clone()
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
    fn new(instance: String, port: String, ia: i64, ib: i64) -> PyClassInitializer<Self> {
        PyClassInitializer::from(PortRef { instance, port }).add_subclass(Self { ia, ib })
    }

    fn __hash__(slf: PyRef<'_, Self>) -> u64 {
        let parent = slf.as_ref();
        hash64(&(&parent.instance, &parent.port, slf.ia, slf.ib))
    }

    fn __richcmp__(
        slf: PyRef<'_, Self>,
        py: Python<'_>,
        other: &Bound<'_, PyAny>,
        op: CompareOp,
    ) -> PyObject {
        let kind = match kind_of(other) {
            Some(k) => k,
            None => return richcmp_result(py, None),
        };
        let (lt, eq) = match kind {
            KIND_NETLIST_PORT | KIND_PORT_REF => (false, false),
            KIND_PORT_ARRAY_REF => {
                let other = other.downcast::<PortArrayRef>().unwrap().borrow();
                let other_parent = other.as_ref();
                let self_parent = slf.as_ref();
                let s = (&self_parent.instance, &self_parent.port, slf.ia, slf.ib);
                let o = (
                    &other_parent.instance,
                    &other_parent.port,
                    other.ia,
                    other.ib,
                );
                (s < o, s == o)
            }
            _ => unreachable!(),
        };
        richcmp_result(py, Some(cmp_to_py(op, lt, eq)))
    }

    fn __repr__(slf: PyRef<'_, Self>) -> String {
        let parent = slf.as_ref();
        format!(
            "PortArrayRef(instance={}, port={}, ia={}, ib={})",
            py_repr(&parent.instance),
            py_repr(&parent.port),
            slf.ia,
            slf.ib
        )
    }

    fn __str__(slf: PyRef<'_, Self>) -> String {
        Self::as_python_str(slf, None)
    }

    #[pyo3(signature = (inst_name=None))]
    fn as_python_str(slf: PyRef<'_, Self>, inst_name: Option<String>) -> String {
        let parent = slf.as_ref();
        let inst = inst_name.unwrap_or_else(|| parent.instance.clone());
        format!(
            "{}[{}, {}, {}]",
            inst,
            py_repr(&parent.port),
            slf.ia,
            slf.ib
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

    fn to_json(slf: PyRef<'_, Self>) -> PyResult<String> {
        let parent = slf.as_ref();
        let data = PortArrayRefData {
            instance: parent.instance.clone(),
            port: parent.port.clone(),
            ia: slf.ia,
            ib: slf.ib,
        };
        json_string(&data)
    }

    #[classmethod]
    fn from_json(cls: &Bound<'_, PyType>, data: &str) -> PyResult<Py<Self>> {
        let d: PortArrayRefData = json_parse(data)?;
        d.into_py(cls.py())
    }

    fn to_dict<'py>(slf: PyRef<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let parent = slf.as_ref();
        let data = PortArrayRefData {
            instance: parent.instance.clone(),
            port: parent.port.clone(),
            ia: slf.ia,
            ib: slf.ib,
        };
        to_py_dict(py, &data)
    }

    #[classmethod]
    fn from_dict(cls: &Bound<'_, PyType>, obj: &Bound<'_, PyAny>) -> PyResult<Py<Self>> {
        let d: PortArrayRefData = from_py_any(obj)?;
        d.into_py(cls.py())
    }
}
