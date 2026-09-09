//! Python conversion at the boundary of the pure-Rust flattening engine.

use std::collections::HashMap;

use indexmap::IndexMap;
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::netlist::Netlist;
use crate::placement::PlacedNetlist;

/// Read a `{cell name: Netlist | PlacedNetlist}` mapping into core values.
pub(crate) fn read_netlists(
    obj: &Bound<'_, PyAny>,
) -> PyResult<HashMap<String, kfnetlist_core::NetlistData>> {
    let dict = obj.downcast::<PyDict>().map_err(|_| {
        PyTypeError::new_err("netlists must be a dict of {cell name: Netlist | PlacedNetlist}")
    })?;
    let mut out = HashMap::with_capacity(dict.len());
    for (key, value) in dict.iter() {
        let name: String = key
            .extract()
            .map_err(|_| PyTypeError::new_err("netlists keys must be cell names (str)"))?;
        out.insert(name, read_netlist(&value)?);
    }
    Ok(out)
}

fn read_netlist(obj: &Bound<'_, PyAny>) -> PyResult<kfnetlist_core::NetlistData> {
    // PlacedNetlist first: it is a Python subclass of Netlist.
    if let Ok(placed) = obj.downcast::<PlacedNetlist>() {
        let child = placed.borrow();
        let base: &Netlist = child.as_ref();
        return Ok(kfnetlist_core::NetlistData {
            instances: base.instances.clone(),
            nets: base.nets.clone(),
            ports: base.ports.clone(),
            extras: child.extras.clone(),
        });
    }
    let plain = obj
        .downcast::<Netlist>()
        .map_err(|_| PyTypeError::new_err("netlists values must be Netlist or PlacedNetlist"))?
        .borrow();
    Ok(kfnetlist_core::NetlistData {
        instances: plain.instances.clone(),
        nets: plain.nets.clone(),
        ports: plain.ports.clone(),
        extras: IndexMap::new(),
    })
}

pub(crate) fn emit_warnings(py: Python<'_>, warnings: Vec<String>) -> PyResult<()> {
    for warning in warnings {
        crate::warn(py, &warning)?;
    }
    Ok(())
}
