//! Placement-aware netlist flavor.
//!
//! These types extend the plain connectivity model with physical placement
//! geometry, so a single object carries both the netlist (instances, nets,
//! ports) *and* where each instance sits in the layout.
//!
//! * [`Placement`] — a value object: the origin transform (x, y, orientation,
//!   mirror) plus a bounding box (as a dict). Purely geometric — *where* an
//!   instance sits, not *what* it is.
//! * [`PlacedInstance`] — subclass of [`NetlistInstance`] adding the placed
//!   `cell` name and a `placement`.
//! * [`PlacedNetlist`] — subclass of [`Netlist`] whose instances are
//!   [`PlacedInstance`] and which exposes a `placements` map keyed by name.

use std::collections::HashMap;

use indexmap::IndexMap;
use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyType};
use serde::{Deserialize, Serialize};

use crate::instance::{NetlistArray, NetlistInstance};
use crate::netlist::Netlist;
use crate::{cmp_to_py, from_py_any, json_parse, json_string, richcmp_result, to_py_dict};

use kfnetlist_core::placement::{merge_extras, PlacedExtra, PlacedInstanceWire, PlacedNetlistWire};

/// Physical placement of an instance: origin transform and bounding box.
///
/// This is purely geometric. The placed cell's *name* is an intrinsic property
/// of the instance and lives on [`PlacedInstance::cell`], not here.
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Placement(pub kfnetlist_core::Placement);
crate::core_wrapper!(Placement, kfnetlist_core::Placement);

#[pymethods]
impl Placement {
    #[getter]
    fn x(&self) -> f64 {
        self.0.x
    }
    #[setter]
    fn set_x(&mut self, value: f64) {
        self.0.x = value;
    }
    #[getter]
    fn y(&self) -> f64 {
        self.0.y
    }
    #[setter]
    fn set_y(&mut self, value: f64) {
        self.0.y = value;
    }
    #[getter]
    fn orientation(&self) -> f64 {
        self.0.orientation
    }
    #[setter]
    fn set_orientation(&mut self, value: f64) {
        self.0.orientation = value;
    }
    #[getter]
    fn mirror(&self) -> bool {
        self.0.mirror
    }
    #[setter]
    fn set_mirror(&mut self, value: bool) {
        self.0.mirror = value;
    }
    #[new]
    #[pyo3(signature = (x, y, orientation, mirror, bbox))]
    fn new(
        x: f64,
        y: f64,
        orientation: f64,
        mirror: bool,
        bbox: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        Ok(Self(kfnetlist_core::Placement {
            x,
            y,
            orientation,
            mirror,
            bbox: from_py_any(bbox)?,
        }))
    }

    /// Bounding box as a dict (`{"left", "bottom", "right", "top"}`).
    #[getter]
    fn bbox<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, &self.bbox)
    }

    #[setter]
    fn set_bbox(&mut self, value: &Bound<'_, PyAny>) -> PyResult<()> {
        self.bbox = from_py_any(value)?;
        Ok(())
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> PyObject {
        let py = other.py();
        let Ok(other) = other.downcast::<Placement>() else {
            return py.NotImplemented();
        };
        let other = other.borrow();
        let eq = self.x == other.x
            && self.y == other.y
            && self.orientation == other.orientation
            && self.mirror == other.mirror
            && self.bbox == other.bbox;
        richcmp_result(py, Some(cmp_to_py(op, false, eq)))
    }

    fn __repr__(&self) -> String {
        format!(
            "Placement(x={}, y={}, orientation={}, mirror={})",
            self.x, self.y, self.orientation, self.mirror
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

/// Instance carrying placement geometry. Subclass of [`NetlistInstance`]: the
/// connectivity fields (`kcl`, `component`, `settings`, `array`, `name`) live
/// on the parent layer; the placed `cell` name and `placement` are stored here.
#[pyclass(module = "kfnetlist._native", extends = NetlistInstance)]
#[derive(Clone, Debug)]
pub struct PlacedInstance(pub PlacedExtra);
crate::core_wrapper!(PlacedInstance, PlacedExtra);

/// Build the `(parent, child)` initializer for a `PlacedInstance`.
fn placed_inst_init(
    inst: NetlistInstance,
    extra: PlacedExtra,
) -> PyClassInitializer<PlacedInstance> {
    PyClassInitializer::from(inst).add_subclass(PlacedInstance(extra))
}

#[pymethods]
impl PlacedInstance {
    #[getter]
    fn cell(&self) -> String {
        self.0.cell.clone()
    }
    #[setter]
    fn set_cell(&mut self, value: String) {
        self.0.cell = value;
    }
    #[new]
    #[pyo3(signature = (kcl, component, settings=None, array=None, name=String::new(), cell=String::new(), placement=None))]
    fn new(
        kcl: String,
        component: String,
        settings: Option<&Bound<'_, PyAny>>,
        array: Option<NetlistArray>,
        name: String,
        cell: String,
        placement: Option<Placement>,
    ) -> PyResult<PyClassInitializer<Self>> {
        let settings = match settings {
            Some(obj) if !obj.is_none() => from_py_any::<serde_json::Value>(obj)?,
            _ => serde_json::Value::Object(Default::default()),
        };
        let inst = NetlistInstance(kfnetlist_core::NetlistInstance {
            kcl,
            component,
            settings,
            array: array.map(|value| value.0),
            name,
        });
        Ok(placed_inst_init(
            inst,
            PlacedExtra {
                cell,
                placement: placement.unwrap_or_default().0,
            },
        ))
    }

    #[getter]
    fn placement(&self) -> Placement {
        Placement(self.0.placement.clone())
    }

    #[setter]
    fn set_placement(&mut self, value: Placement) {
        self.0.placement = value.0;
    }

    fn __repr__(slf: PyRef<'_, Self>) -> String {
        let parent = slf.as_ref();
        format!(
            "PlacedInstance(name={:?}, cell={:?}, component={:?}, placement={})",
            parent.name,
            slf.cell,
            parent.component,
            Placement(slf.placement.clone()).__repr__()
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
        json_string(&PlacedInstanceWire::from_parts(slf.as_ref(), &slf.0))
    }

    #[classmethod]
    #[pyo3(signature = (data, name=String::new()))]
    fn from_json(cls: &Bound<'_, PyType>, data: &str, name: String) -> PyResult<Py<Self>> {
        let wire: PlacedInstanceWire = json_parse(data)?;
        let (inst, extra) = wire.into_instance(name);
        Py::new(cls.py(), placed_inst_init(inst.into(), extra))
    }

    fn to_dict<'py>(slf: PyRef<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, &PlacedInstanceWire::from_parts(slf.as_ref(), &slf.0))
    }

    #[classmethod]
    #[pyo3(signature = (obj, name=String::new()))]
    fn from_dict(
        cls: &Bound<'_, PyType>,
        obj: &Bound<'_, PyAny>,
        name: String,
    ) -> PyResult<Py<Self>> {
        let wire: PlacedInstanceWire = from_py_any(obj)?;
        let (inst, extra) = wire.into_instance(name);
        Py::new(cls.py(), placed_inst_init(inst.into(), extra))
    }
}

/// Netlist carrying per-instance placement geometry. Subclass of [`Netlist`]:
/// instances/nets/ports live on the parent layer, with a parallel `extras` map
/// (placed cell name + placement) keyed by instance name layered on top.
#[pyclass(module = "kfnetlist._native", extends = Netlist)]
#[derive(Default)]
pub struct PlacedNetlist {
    pub extras: IndexMap<String, PlacedExtra>,
}

impl PlacedNetlist {
    /// Assemble a `(Netlist, PlacedNetlist)` initializer from a base netlist
    /// and an extras map, keeping only entries for instances that exist.
    fn init_from(base: Netlist, extras: IndexMap<String, PlacedExtra>) -> PyClassInitializer<Self> {
        let placed = kfnetlist_core::PlacedNetlist::new(base.0, extras);
        PyClassInitializer::from(Netlist(placed.netlist)).add_subclass(PlacedNetlist {
            extras: placed.extras,
        })
    }
}

impl PlacedNetlist {
    /// Move the independently owned Python layers into the core for a domain
    /// operation, then restore both layers even if the operation returns an error.
    fn with_core<T>(
        mut slf: PyRefMut<'_, Self>,
        operation: impl FnOnce(&mut kfnetlist_core::PlacedNetlist) -> T,
    ) -> T {
        let extras = std::mem::take(&mut slf.extras);
        let base: &mut Netlist = slf.as_mut();
        let mut core = kfnetlist_core::PlacedNetlist {
            netlist: std::mem::take(&mut base.0),
            extras,
        };
        let result = operation(&mut core);
        let base: &mut Netlist = slf.as_mut();
        base.0 = core.netlist;
        slf.extras = core.extras;
        result
    }
}

#[pymethods]
impl PlacedNetlist {
    #[new]
    fn new() -> PyClassInitializer<Self> {
        PyClassInitializer::from(Netlist::default()).add_subclass(PlacedNetlist::default())
    }

    /// Upgrade a plain [`Netlist`] to a placed one by attaching, per instance
    /// name, the placed `cell` name and `placement` geometry.
    ///
    /// Entries for instances absent from `netlist` are dropped; instances
    /// without an entry get an empty cell name / default placement on access.
    #[classmethod]
    #[pyo3(signature = (netlist, placements=None, cells=None))]
    fn from_netlist(
        cls: &Bound<'_, PyType>,
        netlist: PyRef<'_, Netlist>,
        placements: Option<HashMap<String, Placement>>,
        cells: Option<HashMap<String, String>>,
    ) -> PyResult<Py<Self>> {
        let base = netlist.deep_clone();
        Py::new(
            cls.py(),
            Self::init_from(
                base,
                merge_extras(
                    placements.map(|values| values.into_iter().map(|(k, v)| (k, v.0)).collect()),
                    cells,
                ),
            ),
        )
    }

    /// Fresh dict of `{name: PlacedInstance}` (base instance + cell + placement).
    #[getter]
    fn instances<'py>(slf: PyRef<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let base = slf.as_ref();
        let dict = PyDict::new(py);
        for (name, inst) in &base.instances {
            let extra = slf.extras.get(name).cloned().unwrap_or_default();
            let obj = Py::new(py, placed_inst_init(inst.clone().into(), extra))?;
            dict.set_item(name, obj)?;
        }
        Ok(dict)
    }

    /// Fresh dict of `{name: Placement}` for instances that have one.
    #[getter]
    fn placements<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (name, extra) in &self.extras {
            dict.set_item(name, Py::new(py, Placement(extra.placement.clone()))?)?;
        }
        Ok(dict)
    }

    /// Add an instance with its placed `cell` name and `placement`. Mirrors
    /// [`Netlist::create_inst`] with trailing optional `cell`/`placement`;
    /// keeping the base parameter order makes this a substitutable override.
    #[pyo3(signature = (name, kcl, component, settings=None, na=1, nb=1, cell=String::new(), placement=None))]
    #[allow(clippy::too_many_arguments)] // Preserve the public Python signature.
    fn create_inst(
        slf: PyRefMut<'_, Self>,
        py: Python<'_>,
        name: String,
        kcl: String,
        component: String,
        settings: Option<&Bound<'_, PyAny>>,
        na: i64,
        nb: i64,
        cell: String,
        placement: Option<Placement>,
    ) -> PyResult<Py<PlacedInstance>> {
        let settings = match settings {
            Some(obj) if !obj.is_none() => from_py_any::<serde_json::Value>(obj)?,
            _ => serde_json::Value::Object(Default::default()),
        };
        let extra = PlacedExtra {
            cell,
            placement: placement.unwrap_or_default().0,
        };
        let placed = Self::with_core(slf, |core| {
            core.create_inst(name, kcl, component, settings, na, nb, extra)
        })
        .map_err(crate::core_error)?;
        Py::new(py, placed_inst_init(placed.instance.into(), placed.extra))
    }

    /// Remove the named instances (delegating to the base) and drop their
    /// placement extras so the two layers stay consistent.
    fn flatten_instances(slf: PyRefMut<'_, Self>, names: Vec<String>) -> PyResult<()> {
        Self::with_core(slf, |core| core.flatten_instances(names)).map_err(crate::core_error)
    }

    fn __repr__(slf: PyRef<'_, Self>) -> String {
        let base = slf.as_ref();
        format!(
            "PlacedNetlist(instances={}, nets={}, ports={})",
            base.instances.len(),
            base.nets.len(),
            base.ports.len()
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
        json_string(&placed_wire(&slf))
    }

    #[classmethod]
    fn from_json(cls: &Bound<'_, PyType>, data: &str) -> PyResult<Py<Self>> {
        let wire: PlacedNetlistWire = json_parse(data)?;
        Py::new(cls.py(), wire_to_init(wire))
    }

    fn to_dict<'py>(slf: PyRef<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, &placed_wire(&slf))
    }

    #[classmethod]
    fn from_dict(cls: &Bound<'_, PyType>, obj: &Bound<'_, PyAny>) -> PyResult<Py<Self>> {
        let wire: PlacedNetlistWire = from_py_any(obj)?;
        Py::new(cls.py(), wire_to_init(wire))
    }
}

/// Convert the Python inheritance layers to the core's composed value.
fn placed_wire(slf: &PyRef<'_, PlacedNetlist>) -> PlacedNetlistWire {
    PlacedNetlistWire::from_parts(&slf.as_ref().0, &slf.extras)
}

/// Rebuild a `(Netlist, PlacedNetlist)` initializer from the wire form.
fn wire_to_init(wire: PlacedNetlistWire) -> PyClassInitializer<PlacedNetlist> {
    let placed = kfnetlist_core::PlacedNetlist::from_wire(wire);
    PlacedNetlist::init_from(Netlist(placed.netlist), placed.extras)
}
