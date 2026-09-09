//! Physical geometry and placement-aware connectivity values.
use crate::{Net, Netlist, NetlistArray, NetlistInstance, NetlistPort};
use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

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
/// of the instance and lives on [`PlacedExtra::cell`], not here.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Placement {
    /// Origin x displacement, micrometres.
    pub x: f64,
    /// Origin y displacement, micrometres.
    pub y: f64,
    /// Rotation about the origin, degrees.
    pub orientation: f64,
    /// Mirror flag (reflection before rotation, klayout convention).
    pub mirror: bool,
    /// Bounding box in the parent cell's coordinates, micrometres.
    pub bbox: BBox,
}

/// Physical attributes a `PlacedInstance` carries beyond its base
/// `NetlistInstance`: the placed cell name and its placement geometry.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlacedExtra {
    pub cell: String,
    pub placement: Placement,
}

/// Wire format for a placed instance: the base instance fields plus the placed
/// cell name and placement.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlacedInstanceWire {
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
    pub fn from_parts(inst: &NetlistInstance, extra: &PlacedExtra) -> Self {
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

    pub fn into_instance(self, name: String) -> (NetlistInstance, PlacedExtra) {
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

/// Wire format for a placed netlist: instances merge base fields + placement.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlacedNetlistWire {
    #[serde(default)]
    pub instances: IndexMap<String, PlacedInstanceWire>,
    #[serde(default)]
    pub nets: Vec<Net>,
    #[serde(default)]
    pub ports: Vec<NetlistPort>,
}

/// Merge the optional `placements` and `cells` maps into a single per-instance
/// `extras` map (the union of both key sets).
pub fn merge_extras(
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

/// A connectivity instance and its physical attributes.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(from = "PlacedInstanceWire", into = "PlacedInstanceWire")]
pub struct PlacedInstance {
    pub instance: NetlistInstance,
    pub extra: PlacedExtra,
}
impl From<PlacedInstanceWire> for PlacedInstance {
    fn from(wire: PlacedInstanceWire) -> Self {
        let (instance, extra) = wire.into_instance(String::new());
        Self { instance, extra }
    }
}
impl From<PlacedInstance> for PlacedInstanceWire {
    fn from(value: PlacedInstance) -> Self {
        Self::from_parts(&value.instance, &value.extra)
    }
}
/// Connectivity with physical attributes keyed by instance name.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(from = "PlacedNetlistWire", into = "PlacedNetlistWire")]
pub struct PlacedNetlist {
    pub netlist: Netlist,
    pub extras: IndexMap<String, PlacedExtra>,
}
impl PlacedNetlist {
    pub fn new(netlist: Netlist, mut extras: IndexMap<String, PlacedExtra>) -> Self {
        extras.retain(|name, _| netlist.instances.contains_key(name));
        Self { netlist, extras }
    }
    pub fn remove_instances(&mut self, names: Vec<String>) -> crate::Result<()> {
        self.netlist.remove_instances(names.clone())?;
        for name in names {
            self.extras.shift_remove(&name);
        }
        Ok(())
    }
    #[deprecated(note = "use remove_instances; flatten now means hierarchical inlining")]
    pub fn flatten_instances(&mut self, names: Vec<String>) -> crate::Result<()> {
        self.remove_instances(names)
    }
    pub fn to_wire(&self) -> PlacedNetlistWire {
        PlacedNetlistWire::from_parts(&self.netlist, &self.extras)
    }
    /// Create an instance and attach physical attributes after validation succeeds.
    #[allow(clippy::too_many_arguments)]
    pub fn create_inst(
        &mut self,
        name: String,
        kcl: String,
        component: String,
        settings: serde_json::Value,
        na: i64,
        nb: i64,
        extra: PlacedExtra,
    ) -> crate::Result<PlacedInstance> {
        let instance = self
            .netlist
            .create_inst(name.clone(), kcl, component, settings, na, nb)?;
        self.extras.insert(name, extra.clone());
        Ok(PlacedInstance { instance, extra })
    }
    /// Return a snapshot; absent physical attributes use their default values.
    pub fn get_instance(&self, name: &str) -> crate::Result<PlacedInstance> {
        Ok(PlacedInstance {
            instance: self.netlist.get_instance(name)?,
            extra: self.extras.get(name).cloned().unwrap_or_default(),
        })
    }
    pub fn from_wire(wire: PlacedNetlistWire) -> Self {
        let mut netlist = Netlist {
            nets: wire.nets,
            ports: wire.ports,
            ..Netlist::default()
        };
        let mut extras = IndexMap::new();
        for (name, wire) in wire.instances {
            let (inst, extra) = wire.into_instance(name.clone());
            netlist.instances.insert(name.clone(), inst);
            extras.insert(name, extra);
        }
        Self::new(netlist, extras)
    }
}
impl From<PlacedNetlistWire> for PlacedNetlist {
    fn from(wire: PlacedNetlistWire) -> Self {
        Self::from_wire(wire)
    }
}
impl From<PlacedNetlist> for PlacedNetlistWire {
    fn from(value: PlacedNetlist) -> Self {
        value.to_wire()
    }
}

impl PlacedNetlistWire {
    pub fn from_parts(
        netlist: &Netlist,
        extras: &IndexMap<String, PlacedExtra>,
    ) -> PlacedNetlistWire {
        PlacedNetlistWire {
            instances: netlist
                .instances
                .iter()
                .map(|(name, inst)| {
                    (
                        name.clone(),
                        PlacedInstanceWire::from_parts(
                            inst,
                            &extras.get(name).cloned().unwrap_or_default(),
                        ),
                    )
                })
                .collect(),
            nets: netlist.nets.clone(),
            ports: netlist.ports.clone(),
        }
    }
}
