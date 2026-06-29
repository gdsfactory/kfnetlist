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
use crate::net::Net;
use crate::netlist::Netlist;
use crate::port::NetlistPort;
use crate::{cmp_to_py, from_py_any, json_parse, json_string, richcmp_result, to_py_dict};

/// Axis-aligned bounding box in micrometres, klayout `left/bottom/right/top`
/// convention. Serialized as a plain dict, never as a Python class.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct BBox {
    pub left: f64,
    pub bottom: f64,
    pub right: f64,
    pub top: f64,
}

/// Physical placement of an instance: origin transform and bounding box.
///
/// This is purely geometric. The placed cell's *name* is an intrinsic property
/// of the instance and lives on [`PlacedInstance::cell`], not here.
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Placement {
    /// Origin x displacement, micrometres.
    #[pyo3(get, set)]
    pub x: f64,
    /// Origin y displacement, micrometres.
    #[pyo3(get, set)]
    pub y: f64,
    /// Rotation about the origin, degrees.
    #[pyo3(get, set)]
    pub orientation: f64,
    /// Mirror flag (reflection before rotation, klayout convention).
    #[pyo3(get, set)]
    pub mirror: bool,
    /// Bounding box in the parent cell's coordinates, micrometres.
    pub bbox: BBox,
}

#[pymethods]
impl Placement {
    #[new]
    #[pyo3(signature = (x, y, orientation, mirror, bbox))]
    fn new(
        x: f64,
        y: f64,
        orientation: f64,
        mirror: bool,
        bbox: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        Ok(Self {
            x,
            y,
            orientation,
            mirror,
            bbox: from_py_any(bbox)?,
        })
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

/// Physical attributes a `PlacedInstance` carries beyond its base
/// `NetlistInstance`: the placed cell name and its placement geometry.
#[derive(Clone, Debug, Default)]
pub(crate) struct PlacedExtra {
    pub cell: String,
    pub placement: Placement,
}

/// Instance carrying placement geometry. Subclass of [`NetlistInstance`]: the
/// connectivity fields (`kcl`, `component`, `settings`, `array`, `name`) live
/// on the parent layer; the placed `cell` name and `placement` are stored here.
#[pyclass(module = "kfnetlist._native", extends = NetlistInstance)]
#[derive(Clone, Debug)]
pub struct PlacedInstance {
    /// The placed cell's name (`inst.cell.name`) — distinct from the base
    /// `component`, which is the factory name (falling back to the cell name).
    #[pyo3(get, set)]
    pub cell: String,
    pub placement: Placement,
}

/// Wire format for a placed instance: the base instance fields plus the placed
/// cell name and placement.
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PlacedInstanceWire {
    pub kcl: String,
    pub component: String,
    #[serde(default)]
    pub settings: serde_json::Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub array: Option<NetlistArray>,
    #[serde(default)]
    pub cell: String,
    pub placement: Placement,
}

impl PlacedInstanceWire {
    fn from_parts(inst: &NetlistInstance, extra: &PlacedExtra) -> Self {
        Self {
            kcl: inst.kcl.clone(),
            component: inst.component.clone(),
            settings: if inst.settings.is_null() {
                serde_json::Value::Object(Default::default())
            } else {
                inst.settings.clone()
            },
            array: inst.array.clone(),
            cell: extra.cell.clone(),
            placement: extra.placement.clone(),
        }
    }

    fn into_instance(self, name: String) -> (NetlistInstance, PlacedExtra) {
        let inst = NetlistInstance {
            kcl: self.kcl,
            component: self.component,
            settings: self.settings,
            array: self.array,
            name,
        };
        let extra = PlacedExtra {
            cell: self.cell,
            placement: self.placement,
        };
        (inst, extra)
    }
}

/// Build the `(parent, child)` initializer for a `PlacedInstance`.
fn placed_inst_init(
    inst: NetlistInstance,
    extra: PlacedExtra,
) -> PyClassInitializer<PlacedInstance> {
    PyClassInitializer::from(inst).add_subclass(PlacedInstance {
        cell: extra.cell,
        placement: extra.placement,
    })
}

#[pymethods]
impl PlacedInstance {
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
        let inst = NetlistInstance {
            kcl,
            component,
            settings,
            array,
            name,
        };
        Ok(placed_inst_init(
            inst,
            PlacedExtra {
                cell,
                placement: placement.unwrap_or_default(),
            },
        ))
    }

    #[getter]
    fn placement(&self) -> Placement {
        self.placement.clone()
    }

    #[setter]
    fn set_placement(&mut self, value: Placement) {
        self.placement = value;
    }

    fn __repr__(slf: PyRef<'_, Self>) -> String {
        let parent = slf.as_ref();
        format!(
            "PlacedInstance(name={:?}, cell={:?}, component={:?}, placement={})",
            parent.name,
            slf.cell,
            parent.component,
            slf.placement.__repr__()
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
        json_string(&PlacedInstanceWire::from_parts(slf.as_ref(), &slf.extra()))
    }

    #[classmethod]
    #[pyo3(signature = (data, name=String::new()))]
    fn from_json(cls: &Bound<'_, PyType>, data: &str, name: String) -> PyResult<Py<Self>> {
        let wire: PlacedInstanceWire = json_parse(data)?;
        let (inst, extra) = wire.into_instance(name);
        Py::new(cls.py(), placed_inst_init(inst, extra))
    }

    fn to_dict<'py>(slf: PyRef<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(
            py,
            &PlacedInstanceWire::from_parts(slf.as_ref(), &slf.extra()),
        )
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
        Py::new(cls.py(), placed_inst_init(inst, extra))
    }
}

impl PlacedInstance {
    fn extra(&self) -> PlacedExtra {
        PlacedExtra {
            cell: self.cell.clone(),
            placement: self.placement.clone(),
        }
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

/// Wire format for a placed netlist: instances merge base fields + placement.
#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PlacedNetlistWire {
    #[serde(default)]
    pub instances: IndexMap<String, PlacedInstanceWire>,
    #[serde(default)]
    pub nets: Vec<Net>,
    #[serde(default)]
    pub ports: Vec<NetlistPort>,
}

/// Merge the optional `placements` and `cells` maps into a single per-instance
/// `extras` map (the union of both key sets).
fn merge_extras(
    placements: Option<HashMap<String, Placement>>,
    cells: Option<HashMap<String, String>>,
) -> IndexMap<String, PlacedExtra> {
    let placements = placements.unwrap_or_default();
    let mut cells = cells.unwrap_or_default();
    let mut out: IndexMap<String, PlacedExtra> = IndexMap::with_capacity(placements.len());
    for (name, placement) in placements {
        let cell = cells.remove(&name).unwrap_or_default();
        out.insert(name, PlacedExtra { cell, placement });
    }
    for (name, cell) in cells {
        out.insert(
            name,
            PlacedExtra {
                cell,
                placement: Placement::default(),
            },
        );
    }
    out
}

impl PlacedNetlist {
    /// Assemble a `(Netlist, PlacedNetlist)` initializer from a base netlist
    /// and an extras map, keeping only entries for instances that exist.
    fn init_from(
        base: Netlist,
        mut extras: IndexMap<String, PlacedExtra>,
    ) -> PyClassInitializer<Self> {
        extras.retain(|name, _| base.instances.contains_key(name));
        PyClassInitializer::from(base).add_subclass(PlacedNetlist { extras })
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
            Self::init_from(base, merge_extras(placements, cells)),
        )
    }

    /// Fresh dict of `{name: PlacedInstance}` (base instance + cell + placement).
    #[getter]
    fn instances<'py>(slf: PyRef<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let base = slf.as_ref();
        let dict = PyDict::new(py);
        for (name, inst) in &base.instances {
            let extra = slf.extras.get(name).cloned().unwrap_or_default();
            let obj = Py::new(py, placed_inst_init(inst.clone(), extra))?;
            dict.set_item(name, obj)?;
        }
        Ok(dict)
    }

    /// Fresh dict of `{name: Placement}` for instances that have one.
    #[getter]
    fn placements<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (name, extra) in &self.extras {
            dict.set_item(name, Py::new(py, extra.placement.clone())?)?;
        }
        Ok(dict)
    }

    /// Add an instance with its placed `cell` name and `placement`. Mirrors
    /// [`Netlist::create_inst`] with trailing optional `cell`/`placement`;
    /// keeping the base parameter order makes this a substitutable override.
    #[pyo3(signature = (name, kcl, component, settings=None, na=1, nb=1, cell=String::new(), placement=None))]
    fn create_inst(
        mut slf: PyRefMut<'_, Self>,
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
        let extra = PlacedExtra {
            cell,
            placement: placement.unwrap_or_default(),
        };
        let inst = {
            let base: &mut Netlist = slf.as_mut();
            base.create_inst(name.clone(), kcl, component, settings, na, nb)?
        };
        slf.extras.insert(name, extra.clone());
        Py::new(py, placed_inst_init(inst, extra))
    }

    /// Remove the named instances (delegating to the base) and drop their
    /// placement extras so the two layers stay consistent.
    fn flatten_instances(mut slf: PyRefMut<'_, Self>, names: Vec<String>) -> PyResult<()> {
        {
            let base: &mut Netlist = slf.as_mut();
            base.flatten_instances(names.clone())?;
        }
        for name in &names {
            slf.extras.shift_remove(name);
        }
        Ok(())
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

/// Serialize a placed netlist (base instances + extras) into its wire form.
fn placed_wire(slf: &PyRef<'_, PlacedNetlist>) -> PlacedNetlistWire {
    let base = slf.as_ref();
    let mut instances = IndexMap::with_capacity(base.instances.len());
    for (name, inst) in &base.instances {
        let extra = slf.extras.get(name).cloned().unwrap_or_default();
        instances.insert(name.clone(), PlacedInstanceWire::from_parts(inst, &extra));
    }
    PlacedNetlistWire {
        instances,
        nets: base.nets.clone(),
        ports: base.ports.clone(),
    }
}

/// Rebuild a `(Netlist, PlacedNetlist)` initializer from the wire form.
fn wire_to_init(wire: PlacedNetlistWire) -> PyClassInitializer<PlacedNetlist> {
    let mut base = Netlist::default();
    let mut extras = IndexMap::with_capacity(wire.instances.len());
    for (name, iw) in wire.instances {
        let (inst, extra) = iw.into_instance(name.clone());
        base.instances.insert(name.clone(), inst);
        extras.insert(name, extra);
    }
    base.nets = wire.nets;
    base.ports = wire.ports;
    PlacedNetlist::init_from(base, extras)
}
