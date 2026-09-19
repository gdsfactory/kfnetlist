use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::PyType;
use serde::{Deserialize, Serialize};

use crate::{cmp_to_py, from_py_any, hash64, json_parse, json_string, to_py_dict};

/// Array dimensions for an array instance (`na` × `nb`).
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug, Hash, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct NetlistArray(pub kfnetlist_core::NetlistArray);
crate::core_wrapper!(NetlistArray, kfnetlist_core::NetlistArray);

#[pymethods]
impl NetlistArray {
    #[getter]
    fn na(&self) -> i64 {
        self.0.na
    }
    #[setter]
    fn set_na(&mut self, value: i64) {
        self.0.na = value;
    }
    #[getter]
    fn nb(&self) -> i64 {
        self.0.nb
    }
    #[setter]
    fn set_nb(&mut self, value: i64) {
        self.0.nb = value;
    }
    #[new]
    #[pyo3(signature = (na, nb))]
    fn new(na: i64, nb: i64) -> Self {
        Self(kfnetlist_core::NetlistArray { na, nb })
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

/// Instance of a sub-cell within a netlist.
///
/// `name` is set by the parent `Netlist` from the dict key on deserialization
/// and is intentionally excluded from the JSON wire format.
///
/// Declared `subclass` so `PlacedInstance` (which adds placement geometry) can
/// extend it; this adds no fields and does not change the wire format.
#[pyclass(module = "kfnetlist._native", subclass)]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(transparent)]
pub struct NetlistInstance(pub kfnetlist_core::NetlistInstance);
crate::core_wrapper!(NetlistInstance, kfnetlist_core::NetlistInstance);

use kfnetlist_core::instance::NetlistInstanceWire;

impl NetlistInstance {
    pub(crate) fn from_wire(name: String, wire: NetlistInstanceWire) -> Self {
        Self(kfnetlist_core::NetlistInstance::from_wire(name, wire))
    }
}

#[pymethods]
impl NetlistInstance {
    #[getter]
    fn kcl(&self) -> String {
        self.0.kcl.clone()
    }
    #[setter]
    fn set_kcl(&mut self, value: String) {
        self.0.kcl = value;
    }
    #[getter]
    fn component(&self) -> String {
        self.0.component.clone()
    }
    #[setter]
    fn set_component(&mut self, value: String) {
        self.0.component = value;
    }
    #[getter]
    fn name(&self) -> String {
        self.0.name.clone()
    }
    #[setter]
    fn set_name(&mut self, value: String) {
        self.0.name = value;
    }
    #[new]
    #[pyo3(signature = (kcl, component, settings=None, array=None, name=String::new(), *, info=None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        kcl: String,
        component: String,
        settings: Option<&Bound<'_, PyAny>>,
        array: Option<NetlistArray>,
        name: String,
        info: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<Self>> {
        make_leaf(kcl, component, settings, array, name, info)?.into_py_variant(py)
    }

    /// Only reference variants expose a reference; leaves raise AttributeError.
    #[getter]
    fn r#ref(&self) -> PyResult<String> {
        self.0.netlist_ref().map(str::to_owned).ok_or_else(|| {
            pyo3::exceptions::PyAttributeError::new_err("a leaf instance has no ref")
        })
    }

    /// Fresh metadata snapshot; assign a whole dictionary to replace it.
    #[getter]
    fn info<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, &self.info)
    }

    #[setter]
    fn set_info(&mut self, value: &Bound<'_, PyAny>) -> PyResult<()> {
        self.info = from_py_any(value)?;
        Ok(())
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
        self.0.array.clone().map(NetlistArray)
    }

    #[setter]
    fn set_array(&mut self, value: Option<NetlistArray>) {
        self.0.array = value.map(|value| value.0);
    }

    /// Normalize this instance's settings in place: integer-valued floats are
    /// stored as integers (`1.0` -> `1`; `1.5` is left as-is).
    fn normalize(&mut self) {
        self.0.normalize();
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> PyResult<PyObject> {
        let py = other.py();
        let Ok(other) = other.downcast::<NetlistInstance>() else {
            return Ok(py.NotImplemented());
        };
        let other = other.borrow();
        let eq = self.0.netlist_ref() == other.0.netlist_ref()
            && self.kcl == other.kcl
            && self.component == other.component
            && self.settings == other.settings
            && self.info == other.info
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
    #[pyo3(signature = (data, name=String::new()))]
    fn from_json(cls: &Bound<'_, PyType>, data: &str, name: String) -> PyResult<Py<Self>> {
        let wire: NetlistInstanceWire = json_parse(data)?;
        Self::from_wire(name, wire).for_class(cls)
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, &self.to_wire())
    }

    #[classmethod]
    #[pyo3(signature = (obj, name=String::new()))]
    fn from_dict(
        cls: &Bound<'_, PyType>,
        obj: &Bound<'_, PyAny>,
        name: String,
    ) -> PyResult<Py<Self>> {
        let wire: NetlistInstanceWire = from_py_any(obj)?;
        Self::from_wire(name, wire).for_class(cls)
    }
}

/// Constructor default shared by plain and placed instances.
pub(crate) fn info_from_py(
    value: Option<&Bound<'_, PyAny>>,
) -> PyResult<serde_json::Map<String, serde_json::Value>> {
    match value {
        Some(obj) if !obj.is_none() => from_py_any(obj),
        _ => Ok(Default::default()),
    }
}

// These Python subclasses preserve the historical callable/isinstance interface.
// The domain representation is the Rust enum, not an inheritance hierarchy.
#[pyclass(module = "kfnetlist._native", extends = NetlistInstance)]
pub struct LeafNetlistInstance;

#[pyclass(module = "kfnetlist._native", extends = NetlistInstance)]
pub struct RefNetlistInstance;

fn make_leaf(
    kcl: String,
    component: String,
    settings: Option<&Bound<'_, PyAny>>,
    array: Option<NetlistArray>,
    name: String,
    info: Option<&Bound<'_, PyAny>>,
) -> PyResult<NetlistInstance> {
    let settings = match settings {
        Some(obj) if !obj.is_none() => from_py_any::<serde_json::Value>(obj)?,
        _ => serde_json::Value::Object(Default::default()),
    };
    Ok(NetlistInstance(kfnetlist_core::NetlistInstance::Leaf(
        kfnetlist_core::LeafNetlistInstance {
            kcl,
            component,
            settings,
            array: array.map(|a| a.0),
            name,
            info: info_from_py(info)?,
        },
    )))
}

impl NetlistInstance {
    pub(crate) fn into_py_variant(self, py: Python<'_>) -> PyResult<Py<Self>> {
        if self.0.netlist_ref().is_some() {
            Ok(Py::new(
                py,
                PyClassInitializer::from(self).add_subclass(RefNetlistInstance),
            )?
            .into_bound(py)
            .into_super()
            .unbind())
        } else {
            Ok(Py::new(
                py,
                PyClassInitializer::from(self).add_subclass(LeafNetlistInstance),
            )?
            .into_bound(py)
            .into_super()
            .unbind())
        }
    }
    fn for_class(self, cls: &Bound<'_, PyType>) -> PyResult<Py<Self>> {
        let py = cls.py();
        let is_ref = self.0.netlist_ref().is_some();
        if (cls.is(&py.get_type::<LeafNetlistInstance>()) && is_ref)
            || (cls.is(&py.get_type::<RefNetlistInstance>()) && !is_ref)
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "instance does not match the requested leaf/reference variant",
            ));
        }
        self.into_py_variant(py)
    }
}

#[pymethods]
impl LeafNetlistInstance {
    #[new]
    #[pyo3(signature = (kcl, component, settings=None, array=None, name=String::new(), *, info=None))]
    fn new(
        kcl: String,
        component: String,
        settings: Option<&Bound<'_, PyAny>>,
        array: Option<NetlistArray>,
        name: String,
        info: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(
            PyClassInitializer::from(make_leaf(kcl, component, settings, array, name, info)?)
                .add_subclass(Self),
        )
    }
}

#[pymethods]
impl RefNetlistInstance {
    #[new]
    #[pyo3(signature = (kcl, component, settings=None, array=None, name=String::new(), *, r#ref, info=None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        kcl: String,
        component: String,
        settings: Option<&Bound<'_, PyAny>>,
        array: Option<NetlistArray>,
        name: String,
        r#ref: String,
        info: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<PyClassInitializer<Self>> {
        let leaf = make_leaf(kcl, component, settings, array, name, info)?;
        let kfnetlist_core::NetlistInstance::Leaf(instance) = leaf.0 else {
            unreachable!()
        };
        Ok(
            PyClassInitializer::from(NetlistInstance(kfnetlist_core::NetlistInstance::Ref(
                kfnetlist_core::RefNetlistInstance {
                    instance,
                    netlist_ref: r#ref,
                },
            )))
            .add_subclass(Self),
        )
    }
}
