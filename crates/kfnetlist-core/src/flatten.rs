//! Hierarchical netlist flattening.
//!
//! Flattening replaces selected instances by the contents of their *own* cell's
//! netlist: `mzi1` becomes `mzi1.mmi1`, `mzi1.wg_top`, … and the parent's nets
//! are rewired so every connection that landed on a port of `mzi1` now lands on
//! whatever that port is wired to inside the cell. Nothing is collapsed or
//! discarded — this is the inverse of [`Netlist::remove_instances`], which
//! deletes an instance and merges the nets it touched.
//!
//! Resolving an instance to its cell's netlist needs the *cell name*, which a
//! plain [`NetlistInstance`] does not carry (`component` is the factory name).
//! Two sources are supported, in priority order:
//!
//! 1. an explicit `instance name -> cell name` map (`instance_cell_map` for the netlist
//!    being flattened, `sub_instance_cell_maps` keyed by cell name for the levels below), and
//! 2. `PlacedInstance.cell`, which extraction fills in for the placed flavor.
//!
//! Instances whose cell cannot be resolved are left alone.

use std::collections::{BTreeMap, HashMap, HashSet};

use crate::instance::NetlistInstance;
use crate::net::{Net, NetMember};
use crate::netlist::UnionFind;
use crate::placement::{BBox, PlacedExtra, PlacedNetlist, Placement};
use crate::port::{NetlistPort, PortArrayRef, PortRef};
use crate::{Error, Netlist, Result};
use indexmap::IndexMap;

/// Flat view of a netlist's contents, independent of the Python flavor
/// (`Netlist` or `PlacedNetlist`) it came from. `extras` is empty for the plain
/// flavor.
#[derive(Clone, Debug, Default)]
pub struct NetlistData {
    pub instances: IndexMap<String, NetlistInstance>,
    pub nets: Vec<Net>,
    pub ports: Vec<NetlistPort>,
    pub extras: IndexMap<String, PlacedExtra>,
}

/// Knobs for [`flatten_netlist`].
pub struct FlattenOptions {
    /// Cell names to inline; `None` means "every instance we can resolve".
    cells: Option<HashSet<String>>,
    /// Cell names never to inline (wins over `cells`).
    exclude: HashSet<String>,
    /// Keep going into the instances that were just inlined.
    recursive: bool,
    /// Inline even when it would drop a parent connection (see
    /// [`expand_pass`]); by default that is an error.
    allow_unconnected_ports: bool,
    /// Emit a `UserWarning` for every instance left alone.
    warn_skipped: bool,
    /// Joins parent and inner instance name: `mzi1` + `wg1` -> `mzi1.wg1`.
    separator: String,
}

impl FlattenOptions {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        cells: Option<Vec<String>>,
        exclude: Option<Vec<String>>,
        recursive: bool,
        allow_unconnected_ports: bool,
        warn_skipped: bool,
        separator: String,
    ) -> Self {
        Self {
            cells: cells.map(|c| c.into_iter().collect()),
            exclude: exclude.unwrap_or_default().into_iter().collect(),
            recursive,
            allow_unconnected_ports,
            warn_skipped,
            separator,
        }
    }

    fn selected(&self, cell: &str) -> bool {
        if self.exclude.contains(cell) {
            return false;
        }
        match &self.cells {
            Some(cells) => cells.contains(cell),
            None => true,
        }
    }
}

impl From<Netlist> for NetlistData {
    fn from(netlist: Netlist) -> Self {
        Self {
            instances: netlist.instances,
            nets: netlist.nets,
            ports: netlist.ports,
            extras: IndexMap::new(),
        }
    }
}

impl From<PlacedNetlist> for NetlistData {
    fn from(placed: PlacedNetlist) -> Self {
        Self {
            instances: placed.netlist.instances,
            nets: placed.netlist.nets,
            ports: placed.netlist.ports,
            extras: placed.extras,
        }
    }
}

/// Flattened data plus non-fatal diagnostics requested by `warn_skipped`.
pub struct FlattenOutput {
    pub data: NetlistData,
    pub warnings: Vec<String>,
}

/// Compose an inner instance's placement (child-cell coordinates) with the
/// placement of the instance being inlined, giving parent-cell coordinates.
///
/// klayout convention: a placement maps `v` to `disp + R(angle) · M · v`, where
/// `M` mirrors about the x-axis before rotation. Composing two of those gives
/// `angle = ap ± ac` (minus when the parent mirrors, since `M·R(a) = R(-a)·M`)
/// and `mirror = mp XOR mc`. The bounding box is the child's box pushed through
/// the parent transform — exact for multiples of 90°, a conservative
/// axis-aligned hull otherwise.
pub fn compose_placement(parent: &Placement, child: &Placement) -> Placement {
    // Multiples of 90° — by far the common case — are taken from an exact
    // table, since `sin(90°.to_radians())` is 1 - 6e-17 and would smear that
    // error across every inlined coordinate.
    let angle = parent.orientation.rem_euclid(360.0);
    let (sin, cos) = if angle == 0.0 {
        (0.0, 1.0)
    } else if angle == 90.0 {
        (1.0, 0.0)
    } else if angle == 180.0 {
        (0.0, -1.0)
    } else if angle == 270.0 {
        (-1.0, 0.0)
    } else {
        angle.to_radians().sin_cos()
    };
    let map = |x: f64, y: f64| -> (f64, f64) {
        let y = if parent.mirror { -y } else { y };
        (parent.x + cos * x - sin * y, parent.y + sin * x + cos * y)
    };
    let (x, y) = map(child.x, child.y);
    let orientation = if parent.mirror {
        parent.orientation - child.orientation
    } else {
        parent.orientation + child.orientation
    };
    let corners = [
        map(child.bbox.left, child.bbox.bottom),
        map(child.bbox.right, child.bbox.bottom),
        map(child.bbox.left, child.bbox.top),
        map(child.bbox.right, child.bbox.top),
    ];
    let fold = |f: fn(f64, f64) -> f64, pick: fn(&(f64, f64)) -> f64| {
        corners
            .iter()
            .map(pick)
            .fold(f64::NAN, |acc, v| if acc.is_nan() { v } else { f(acc, v) })
    };
    Placement {
        x,
        y,
        orientation: orientation.rem_euclid(360.0),
        mirror: parent.mirror != child.mirror,
        bbox: BBox {
            left: fold(f64::min, |c| c.0),
            bottom: fold(f64::min, |c| c.1),
            right: fold(f64::max, |c| c.0),
            top: fold(f64::max, |c| c.1),
        },
    }
}

/// Netlist plus the bookkeeping that survives between passes.
struct State {
    data: NetlistData,
    /// Instance name -> cell name, extended as instances are inlined.
    cell_of: HashMap<String, String>,
    /// Instances already reported through `warn_skipped`.
    warned: HashSet<String>,
    warnings: Vec<String>,
}

impl State {
    /// Warn once per instance about instances left alone, if asked to.
    fn report_skipped(&mut self, opts: &FlattenOptions, skipped: Vec<(String, String)>) {
        if !opts.warn_skipped {
            return;
        }
        for (name, why) in skipped {
            if self.warned.insert(name.clone()) {
                self.warnings
                    .push(format!("not flattening instance {name:?}: {why}"));
            }
        }
    }
}

/// Flatten every currently eligible instance exactly one level deep.
///
/// Returns the new state and whether anything was inlined.
fn expand_pass(
    mut state: State,
    subs: &HashMap<String, NetlistData>,
    sub_instance_cell_maps: &HashMap<String, HashMap<String, String>>,
    opts: &FlattenOptions,
) -> Result<(State, bool)> {
    // ---- 1. pick the instances to inline ----
    let mut to_expand: Vec<String> = Vec::new();
    let mut skipped: Vec<(String, String)> = Vec::new();
    for (name, inst) in &state.data.instances {
        let mut skip = |why: String| skipped.push((name.clone(), why));
        let Some(cell) = state.cell_of.get(name).cloned() else {
            skip(
                "its cell name is unknown (pass instance_cell_map/sub_instance_cell_maps, or use a PlacedNetlist)"
                    .to_string(),
            );
            continue;
        };
        if !opts.selected(&cell) {
            continue;
        }
        let Some(sub) = subs.get(&cell) else {
            skip(format!("no netlist given for its cell {cell:?}"));
            continue;
        };
        if sub.instances.is_empty() {
            skip(format!("cell {cell:?} has no instances of its own"));
            continue;
        }
        if inst.array.as_ref().is_some_and(|a| a.na > 1 || a.nb > 1) {
            skip("it is an array instance, which cannot be inlined".to_string());
            continue;
        }
        to_expand.push(name.clone());
    }
    state.report_skipped(opts, skipped);
    if to_expand.is_empty() {
        return Ok((state, false));
    }

    let State {
        data: cur,
        cell_of,
        warned,
        warnings,
    } = state;
    let expanded: HashSet<&str> = to_expand.iter().map(String::as_str).collect();

    // ---- 2. instances: keep the survivors in place, splice in the inner ones ----
    let mut instances: IndexMap<String, NetlistInstance> = IndexMap::new();
    let mut extras: IndexMap<String, PlacedExtra> = IndexMap::new();
    let mut next_cell_of: HashMap<String, String> = HashMap::new();
    let surviving: HashSet<&str> = cur
        .instances
        .keys()
        .map(String::as_str)
        .filter(|name| !expanded.contains(name))
        .collect();

    for (name, inst) in &cur.instances {
        if !expanded.contains(name.as_str()) {
            instances.insert(name.clone(), inst.clone());
            if let Some(extra) = cur.extras.get(name) {
                extras.insert(name.clone(), extra.clone());
            }
            if let Some(cell) = cell_of.get(name) {
                next_cell_of.insert(name.clone(), cell.clone());
            }
            continue;
        }
        let cell = &cell_of[name];
        let sub = &subs[cell];
        let parent_extra = cur.extras.get(name).cloned().unwrap_or_default();

        for (inner_name, inner_inst) in &sub.instances {
            let new_name = format!("{name}{}{inner_name}", opts.separator);
            if instances.contains_key(&new_name) || surviving.contains(new_name.as_str()) {
                return Err(Error::FlattenInstanceCollision {
                    instance: name.clone(),
                    new_name,
                });
            }
            let mut new_inst = inner_inst.clone();
            new_inst.name = new_name.clone();
            instances.insert(new_name.clone(), new_inst);

            let inner_extra = sub.extras.get(inner_name).cloned().unwrap_or_default();
            // An explicit map wins over `PlacedInstance.cell`, and either is
            // worth recording: it keeps the result flattenable without maps.
            let resolved = sub_instance_cell_maps
                .get(cell)
                .and_then(|map| map.get(inner_name))
                .cloned()
                .or_else(|| Some(inner_extra.cell.clone()).filter(|c| !c.is_empty()));
            extras.insert(
                new_name.clone(),
                PlacedExtra {
                    cell: resolved.clone().unwrap_or_default(),
                    placement: compose_placement(&parent_extra.placement, &inner_extra.placement),
                },
            );
            if let Some(inner_cell) = resolved {
                next_cell_of.insert(new_name.clone(), inner_cell);
            }
        }
    }

    // ---- 3. nets ----
    // Parent members referring to an inlined instance and inner members
    // referring to a sub-cell port are both dropped; instead, the nets that
    // held them are merged, which is what re-connects the two levels.
    let mut combined: Vec<Vec<NetMember>> = Vec::with_capacity(cur.nets.len());
    let mut binding: HashMap<(String, String), Vec<usize>> = HashMap::new();
    let mut parent_keys: Vec<(String, String)> = Vec::new();
    let mut inner_bound: HashSet<(String, String)> = HashSet::new();

    for net in &cur.nets {
        let mut kept: Vec<NetMember> = Vec::with_capacity(net.members.len());
        let mut touched: Vec<(String, String)> = Vec::new();
        for member in &net.members {
            let hit = match member {
                NetMember::Ref(r) if expanded.contains(r.instance.as_str()) => {
                    Some((r.instance.clone(), r.port.clone()))
                }
                NetMember::ArrayRef(r) if expanded.contains(r.instance.as_str()) => {
                    Some((r.instance.clone(), r.port.clone()))
                }
                _ => None,
            };
            match hit {
                Some(key) => touched.push(key),
                None => kept.push(member.clone()),
            }
        }
        let idx = combined.len();
        combined.push(kept);
        for key in touched {
            binding.entry(key.clone()).or_default().push(idx);
            parent_keys.push(key);
        }
    }

    for name in &to_expand {
        let sub = &subs[&cell_of[name]];
        for net in &sub.nets {
            let mut kept: Vec<NetMember> = Vec::with_capacity(net.members.len());
            let mut bound: Vec<String> = Vec::new();
            for member in &net.members {
                match member {
                    NetMember::Port(p) => bound.push(p.name.clone()),
                    NetMember::Ref(r) => kept.push(NetMember::Ref(PortRef {
                        instance: format!("{name}{}{}", opts.separator, r.instance),
                        port: r.port.clone(),
                    })),
                    NetMember::ArrayRef(r) => kept.push(NetMember::ArrayRef(PortArrayRef {
                        instance: format!("{name}{}{}", opts.separator, r.instance),
                        port: r.port.clone(),
                        ia: r.ia,
                        ib: r.ib,
                    })),
                }
            }
            let idx = combined.len();
            combined.push(kept);
            for port in bound {
                inner_bound.insert((name.clone(), port.clone()));
                binding.entry((name.clone(), port)).or_default().push(idx);
            }
        }
    }

    if !opts.allow_unconnected_ports {
        for key in &parent_keys {
            if inner_bound.contains(key) {
                continue;
            }
            let cell = &cell_of[&key.0];
            return Err(Error::FlattenUnconnectedPort {
                instance: key.0.clone(),
                port: key.1.clone(),
                cell: cell.clone(),
            });
        }
    }

    let mut uf = UnionFind::new(combined.len());
    for indices in binding.values() {
        for pair in indices.windows(2) {
            uf.union(pair[0], pair[1]);
        }
    }
    let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
    for idx in 0..combined.len() {
        let root = uf.find(idx);
        groups.entry(root).or_default().push(idx);
    }
    // Key by lowest member index so the net order does not depend on hashing.
    let ordered: BTreeMap<usize, Vec<usize>> = groups
        .into_values()
        .map(|indices| (indices[0], indices))
        .collect();

    let mut nets: Vec<Net> = Vec::with_capacity(ordered.len());
    for indices in ordered.into_values() {
        let mut seen: HashSet<&NetMember> = HashSet::new();
        let mut members: Vec<NetMember> = Vec::new();
        for idx in indices {
            for member in &combined[idx] {
                if seen.insert(member) {
                    members.push(member.clone());
                }
            }
        }
        if !members.is_empty() {
            nets.push(Net::from_members(members));
        }
    }

    Ok((
        State {
            data: NetlistData {
                instances,
                nets,
                ports: cur.ports,
                extras,
            },
            cell_of: next_cell_of,
            warned,
            warnings,
        },
        true,
    ))
}

/// A real cell hierarchy is a DAG, so the pass count is bounded by its depth.
/// This only bites on a hand-built `netlists` mapping where a cell (in)directly
/// contains itself, which would otherwise inline forever.
const MAX_PASSES: usize = 1000;

/// Flatten `base` against the `{cell name: netlist}` mapping in `subs`.
pub fn flatten_netlist(
    base: NetlistData,
    instance_cell_map: &HashMap<String, String>,
    subs: &HashMap<String, NetlistData>,
    sub_instance_cell_maps: &HashMap<String, HashMap<String, String>>,
    opts: &FlattenOptions,
) -> Result<FlattenOutput> {
    let mut cell_of: HashMap<String, String> = HashMap::new();
    for name in base.instances.keys() {
        let cell = instance_cell_map
            .get(name)
            .cloned()
            .or_else(|| base.extras.get(name).map(|e| e.cell.clone()))
            .filter(|cell| !cell.is_empty());
        if let Some(cell) = cell {
            cell_of.insert(name.clone(), cell);
        }
    }

    let mut state = State {
        data: base,
        cell_of,
        warned: HashSet::new(),
        warnings: Vec::new(),
    };
    for pass in 0.. {
        if pass == MAX_PASSES {
            return Err(Error::RecursiveFlattenLimit(MAX_PASSES));
        }
        let (next, expanded) = expand_pass(state, subs, sub_instance_cell_maps, opts)?;
        state = next;
        if !expanded || !opts.recursive {
            break;
        }
    }

    // Deterministic output, matching the ordering `Netlist.sort()` produces.
    let State {
        mut data, warnings, ..
    } = state;
    data.instances.sort_keys();
    data.extras.sort_keys();
    for net in &mut data.nets {
        net.sort_in_place();
    }
    data.nets.sort();
    data.ports.sort();
    Ok(FlattenOutput { data, warnings })
}
