use super::{error, proto as p, CircuitDocument, NetlistDocument, Result, SubCircuitDocument};
use indexmap::IndexMap;
use kfnetlist_core::{merge_directives, Directive};
use prost::Message;
use serde::{de::DeserializeOwned, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, HashSet};

type Properties = BTreeMap<String, String>;
fn put<T: Serialize>(props: &mut Properties, key: &str, value: &T) -> Result<()> {
    props.insert(key.into(), serde_json::to_string(value).map_err(error)?);
    Ok(())
}
fn get<T: DeserializeOwned + Default>(props: &Properties, key: &str) -> Result<T> {
    props
        .get(key)
        .map(|s| serde_json::from_str(s).map_err(error))
        .transpose()
        .map(|v| v.unwrap_or_default())
}
/// Properties morphnet owns (no `__` prefix, plus the bridge's `__order__` key-order
/// record); the other `__` ones are this crate's encoding.
fn public(props: &Properties) -> Properties {
    props
        .iter()
        .filter(|(k, _)| !k.starts_with("__") || *k == "__order__")
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect()
}

/// Morphnet data with no kfnetlist counterpart, kept in kfnetlist `info["__morphnet__"]`.
/// Each field is stored only when it differs from what the kfnetlist data regenerates.
#[derive(Default, Serialize, serde::Deserialize)]
#[serde(default)]
struct Stash {
    #[serde(skip_serializing_if = "Properties::is_empty")]
    properties: Properties,
    #[serde(skip_serializing_if = "String::is_empty")]
    class_name: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    parameters: Vec<p::Parameter>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    terminals: Vec<p::Terminal>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    model_interfaces: Vec<p::ModelInterface>,
    /// Net name -> connection template (domain, weight, properties).
    #[serde(skip_serializing_if = "BTreeMap::is_empty")]
    nets: BTreeMap<String, p::Connection>,
    /// Net name -> pin order, where a `Netlist` (which sorts net members) loses it.
    #[serde(skip_serializing_if = "BTreeMap::is_empty")]
    order: BTreeMap<String, Vec<String>>,
    /// Net names in connection order, where a `Netlist` round trip reorders them (it
    /// writes a port's own net in the `ports` form, ahead of the other nets).
    #[serde(skip_serializing_if = "Vec::is_empty")]
    sequence: Vec<String>,
    /// Document-level fields (circuits and directives emptied), on every module so any
    /// subset of the cells keeps them.
    #[serde(skip_serializing_if = "Option::is_none")]
    netlist: Option<p::Netlist>,
    /// Subcircuit masters the document used without declaring (every module), so
    /// morphnet's bridge does not add built-in declarations the source never had.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    undeclared: Vec<String>,
}
const STASH: &str = "__morphnet__";
impl Stash {
    /// Split `info` into the `__info__` payload and the stash.
    fn take(info: &Map<String, Value>) -> Result<(Map<String, Value>, Self)> {
        let mut info = info.clone();
        let stash = match info.remove(STASH) {
            Some(value @ Value::Object(_)) => serde_json::from_value(value).map_err(error)?,
            _ => Self::default(), // not a stash: nothing of the bridge's to restore
        };
        Ok((info, stash))
    }
    fn store(&self, info: &mut Map<String, Value>) -> Result<()> {
        let value = serde_json::to_value(self).map_err(error)?;
        if value.as_object().is_some_and(|m| !m.is_empty()) {
            info.insert(STASH.into(), value);
        } else {
            info.remove(STASH);
        }
        Ok(())
    }
}

/// The kfnetlist setting a parameter carries: its number, else its `expr` text.
fn setting(param: &p::Parameter) -> Option<Value> {
    param.default_value.as_ref().and_then(number).or_else(|| {
        param
            .properties
            .get("expr")
            .map(|e| Value::from(e.as_str()))
    })
}
fn same(a: &Value, b: &Value) -> bool {
    a == b || a.as_f64().is_some_and(|x| Some(x) == b.as_f64())
}
/// Restore stashed parameters still matching `settings`; regenerate the rest. A stashed
/// parameter missing from `settings` was removed, unless `keep_unset` (a kfnetlist
/// `Netlist` has no circuit-level settings, so there absence means "not carried").
fn merge_parameters(
    stashed: &[p::Parameter],
    mut fresh: Vec<p::Parameter>,
    settings: &Map<String, Value>,
    keep_unset: bool,
) -> Vec<p::Parameter> {
    let mut out = Vec::new();
    for s in stashed {
        if s.name.is_empty() {
            out.push(s.clone()); // positional: never a setting
            continue;
        }
        match (settings.get(&s.name), setting(s)) {
            (Some(now), Some(was)) if same(now, &was) => {
                fresh.retain(|f| f.name != s.name);
                out.push(s.clone());
            }
            (Some(_), Some(_)) => {
                if let Some(i) = fresh.iter().position(|f| f.name == s.name) {
                    out.push(fresh.remove(i));
                }
            }
            (None, Some(_)) if !keep_unset => {} // setting removed
            _ => out.push(s.clone()),            // never a setting (model_ref, no value)
        }
    }
    out.extend(fresh);
    out
}
fn directive_to_proto(d: &Directive) -> p::Directive {
    let kind = format!("DIRECTIVE_KIND_{}", d.kind.to_uppercase());
    p::Directive {
        kind: p::DirectiveKind::from_str_name(&kind).unwrap_or_default() as i32,
        name: d.name.clone(),
        value: d.value.clone(),
    }
}
fn directive_from_proto(d: &p::Directive) -> Directive {
    let kind = p::DirectiveKind::try_from(d.kind).unwrap_or_default();
    Directive {
        kind: kind
            .as_str_name()
            .trim_start_matches("DIRECTIVE_KIND_")
            .to_lowercase(),
        name: d.name.clone(),
        value: d.value.clone(),
    }
}
fn parameter(value: &Value) -> Option<p::ParameterValue> {
    value.as_f64().map(|v| p::ParameterValue {
        value: Some(p::parameter_value::Value::PrefixedValue(p::PrefixedValue {
            double_value: v,
            prefix: 0,
        })),
    })
}
// SIPrefix enum value -> power of ten (QUECTO = 1 ... QUETTA = 24).
const SI_EXPONENT: [i32; 25] = [
    0, -30, -27, -24, -21, -18, -15, -12, -9, -6, -3, -2, -1, 1, 2, 3, 6, 9, 12, 15, 18, 21, 24,
    27, 30,
];
fn number(value: &p::ParameterValue) -> Option<Value> {
    match &value.value {
        Some(p::parameter_value::Value::PrefixedValue(v)) => {
            let exponent = usize::try_from(v.prefix)
                .ok()
                .and_then(|i| SI_EXPONENT.get(i))
                .copied()
                .unwrap_or(0);
            Some(Value::from(v.double_value * 10f64.powi(exponent)))
        }
        _ => None,
    }
}
fn terminal(text: &str) -> p::TerminalReference {
    let (instance, port) = text.split_once(',').unwrap_or(("", text));
    p::TerminalReference {
        instance_name: instance.trim().into(),
        terminal_name: port.trim().into(),
    }
}
/// Pin names of a terminal: a bus (`width` > 1, or a `range` property `"msb:lsb"`)
/// is its bits `name[msb]` … `name[lsb]`; anything else is the bare name.
fn terminal_pins(t: &p::Terminal) -> Vec<String> {
    let range = t.properties.get("range").and_then(|r| {
        let (a, b) = r.split_once(':')?;
        Some((a.trim().parse::<i64>().ok()?, b.trim().parse::<i64>().ok()?))
    });
    let (msb, lsb) = match range {
        Some(r) => r,
        None if t.width > 1 => (i64::from(t.width) - 1, 0),
        None => return vec![t.name.clone()],
    };
    let step = if msb >= lsb { -1 } else { 1 };
    (0..=(msb - lsb).abs())
        .map(|k| format!("{}[{}]", t.name, msb + step * k))
        .collect()
}
fn reference(t: &p::TerminalReference) -> String {
    if t.instance_name.is_empty() {
        t.terminal_name.clone()
    } else {
        format!("{},{}", t.instance_name, t.terminal_name)
    }
}
/// String and bool settings become an `expr` parameter (bools as `true`/`false`).
fn expr(value: &Value) -> Option<String> {
    match value {
        Value::String(s) => Some(s.clone()),
        Value::Bool(b) => Some(b.to_string()),
        _ => None,
    }
}
/// Net names of `connections` in order of first use.
fn net_sequence(connections: &[p::Connection]) -> Vec<String> {
    let mut names: Vec<String> = Vec::new();
    for c in connections {
        if !c.name.is_empty() && !names.contains(&c.name) {
            names.push(c.name.clone());
        }
    }
    names
}
fn connection(name: String, source: &str, target: &str) -> p::Connection {
    p::Connection {
        name,
        source: Some(terminal(source)),
        target: Some(terminal(target)),
        ..Default::default()
    }
}
impl SubCircuitDocument {
    fn proto_parameters(&self) -> Vec<p::Parameter> {
        self.settings
            .iter()
            .filter_map(|(key, value)| {
                let mut param = p::Parameter {
                    name: key.clone(),
                    default_value: parameter(value),
                    ..Default::default()
                };
                if param.default_value.is_none() {
                    param.properties.insert("expr".into(), expr(value)?);
                }
                Some(param)
            })
            .collect()
    }
    fn to_proto_subcircuit(&self, name: &str) -> Result<p::SubCircuit> {
        let (info, stash) = Stash::take(&self.info)?;
        let mut properties = stash.properties;
        put(&mut properties, "__array__", &self.array)?;
        put(&mut properties, "__info__", &info)?;
        for (key, value) in &self.settings {
            // Keep exact JSON types/integers alongside the protobuf representation.
            put(&mut properties, &format!("__setting__{key}"), value)?;
        }
        Ok(p::SubCircuit {
            name: name.into(),
            circuit_name: self.component.clone(),
            class_name: stash.class_name,
            parameters: merge_parameters(
                &stash.parameters,
                self.proto_parameters(),
                &self.settings,
                false,
            ),
            properties,
        })
    }
    fn from_proto_subcircuit(r: &p::SubCircuit) -> Result<Self> {
        let mut settings: Map<String, Value> = r
            .parameters
            .iter()
            .filter(|p| !p.name.is_empty())
            .filter_map(|p| Some((p.name.clone(), setting(p)?)))
            .collect();
        for (k, v) in &r.properties {
            if let Some(k) = k.strip_prefix("__setting__") {
                settings.insert(k.into(), serde_json::from_str(v).map_err(error)?);
            }
        }
        let mut doc = Self {
            component: r.circuit_name.clone(),
            settings,
            array: get(&r.properties, "__array__")?,
            info: get(&r.properties, "__info__")?,
        };
        let parameters = if r.parameters == doc.proto_parameters() {
            Vec::new()
        } else {
            r.parameters.clone()
        };
        Stash {
            properties: public(&r.properties),
            class_name: r.class_name.clone(),
            parameters,
            ..Default::default()
        }
        .store(&mut doc.info)?;
        Ok(doc)
    }
}
/// Restore stashed terminals whose pins are all still ports; plain terminals for the rest.
fn merge_terminals(stashed: &[p::Terminal], ports: &IndexMap<String, String>) -> Vec<p::Terminal> {
    let mut used = HashSet::new();
    let mut out = Vec::new();
    for t in stashed {
        let pins = terminal_pins(t);
        if pins.iter().all(|pin| ports.contains_key(pin)) {
            used.extend(pins);
            out.push(t.clone());
        }
    }
    out.extend(
        ports
            .keys()
            .filter(|name| !used.contains(*name))
            .map(|name| p::Terminal {
                name: name.clone(),
                ..Default::default()
            }),
    );
    out
}
impl CircuitDocument {
    fn proto_parameters(&self) -> Result<Vec<p::Parameter>> {
        let mut parameters = Vec::new();
        for (name, value) in &self.settings {
            let mut properties = Properties::new();
            put(&mut properties, "__json_value__", value)?;
            let default_value = parameter(value);
            if default_value.is_none() {
                if let Some(e) = expr(value) {
                    properties.insert("expr".into(), e);
                }
            }
            parameters.push(p::Parameter {
                name: name.clone(),
                default_value,
                properties,
                ..Default::default()
            });
        }
        Ok(parameters)
    }
    fn to_proto_circuit(&self, name: &str) -> Result<p::Circuit> {
        let (info, stash) = Stash::take(&self.info)?;
        let mut properties = stash.properties;
        put(&mut properties, "__name__", &self.name)?;
        put(&mut properties, "__placements__", &self.placements)?;
        put(&mut properties, "__routes__", &self.routes)?;
        put(&mut properties, "__info__", &info)?;
        put(&mut properties, "__nets__", &"named")?;
        if !stash.undeclared.is_empty() {
            put(&mut properties, "__undeclared__", &stash.undeclared)?;
        }
        let parameters = merge_parameters(
            &stash.parameters,
            self.proto_parameters()?,
            &self.settings,
            true,
        );
        let subcircuits = self
            .instances
            .iter()
            .map(|(name, i)| i.to_proto_subcircuit(name))
            .collect::<Result<_>>()?;
        let terminals = merge_terminals(&stash.terminals, &self.ports);
        // morphnet's encoding, which its writers read: a net is a star of connections named
        // after the net, from the port's net node (empty instance) or else the first pin.
        // `__from__`/`__members__`/`__named__` (ignored by morphnet) restore the exact
        // document. Same order as the pre-morphnet encoding: connections, ports, nets.
        let groups = self
            .connections
            .iter()
            .map(|(src, tgt)| ("conn", vec![src.clone(), tgt.clone()], None))
            .chain(
                self.ports
                    .iter()
                    .filter(|(name, target)| name != target)
                    .map(|(name, target)| ("port", vec![name.clone(), target.clone()], None)),
            )
            .chain(
                self.nets
                    .iter()
                    .enumerate()
                    .map(|(i, members)| ("net", members.clone(), self.net_name(i))),
            );
        let mut stars = Vec::new();
        for (i, (from, mut members, named)) in groups.enumerate() {
            if let Some(order) = named.and_then(|n| stash.order.get(n)) {
                if self.netlist_order(order) == Some(members.clone()) {
                    members = order.clone();
                }
            }
            // Unnamed nets are named after their port, else net_<i>.
            let port = members.iter().find(|m| !m.contains(','));
            let net = named
                .map(str::to_owned)
                .or_else(|| port.cloned())
                .unwrap_or_else(|| format!("net_{i}"));
            let source = port
                .or(members.first())
                .cloned()
                .unwrap_or_else(|| net.clone());
            let mut star: Vec<_> = members
                .iter()
                .filter(|m| **m != source)
                .map(|m| connection(net.clone(), &source, m))
                .collect();
            if star.is_empty() {
                star.push(p::Connection {
                    name: net.clone(),
                    source: Some(terminal(&source)),
                    ..Default::default()
                });
            }
            for c in &mut star {
                put(&mut c.properties, "__from__", &from)?;
                if let Some(t) = stash.nets.get(&net) {
                    c.domain = t.domain;
                    c.weight = t.weight;
                    c.properties.extend(t.properties.clone());
                }
            }
            put(&mut star[0].properties, "__members__", &members)?;
            if named.is_some() {
                put(&mut star[0].properties, "__named__", &true)?;
            }
            stars.push((net, star));
        }
        if !stash.sequence.is_empty() {
            let rank = |net: &String| stash.sequence.iter().position(|n| n == net);
            stars.sort_by_key(|(net, _)| rank(net).unwrap_or(usize::MAX));
        }
        let connections = stars.into_iter().flat_map(|(_, star)| star).collect();
        Ok(p::Circuit {
            name: name.into(),
            class_name: stash.class_name,
            terminals,
            parameters,
            model_interfaces: stash.model_interfaces,
            subcircuits,
            connections,
            properties,
            ..Default::default()
        })
    }
    fn read_named_nets(&mut self, pm: &p::Circuit) -> Result<()> {
        let pins: Vec<String> = pm.terminals.iter().flat_map(terminal_pins).collect();
        let terminals: HashSet<&str> = pins.iter().map(String::as_str).collect();
        let mut foreign: IndexMap<&str, Vec<String>> = IndexMap::new();
        for c in &pm.connections {
            if c.properties.contains_key("__from__") {
                if c.properties.contains_key("__members__") {
                    let members: Vec<String> = get(&c.properties, "__members__")?;
                    let from: String = get(&c.properties, "__from__")?;
                    match (from.as_str(), members.as_slice()) {
                        ("port", [name, target]) => {
                            self.ports.insert(name.clone(), target.clone());
                        }
                        ("conn", [src, tgt]) => {
                            self.connections.insert(src.clone(), tgt.clone());
                        }
                        ("net", _) => {
                            let named = c.properties.contains_key("__named__");
                            self.push_net(members, named.then(|| c.name.clone()));
                        }
                        _ => return Err(super::Error(format!("invalid net {:?}", c.name))),
                    }
                }
                continue;
            }
            // Foreign (e.g. parsed SPICE): a bare reference is a pin only if it is a terminal;
            // otherwise it is the net node itself.
            let members = foreign.entry(c.name.as_str()).or_default();
            for t in [&c.source, &c.target].into_iter().flatten() {
                if !t.instance_name.is_empty() || terminals.contains(t.terminal_name.as_str()) {
                    let r = reference(t);
                    if !members.contains(&r) {
                        members.push(r);
                    }
                }
            }
        }
        for (name, members) in foreign {
            if !members.is_empty() {
                self.push_net(members, (!name.is_empty()).then(|| name.to_owned()));
            }
        }
        Ok(())
    }
    fn from_proto_circuit(pm: &p::Circuit) -> Result<Self> {
        let mut settings = Map::new();
        for p in &pm.parameters {
            if let Some(v) = p.properties.get("__json_value__") {
                settings.insert(p.name.clone(), serde_json::from_str(v).map_err(error)?);
            } else if let Some(v) = setting(p).filter(|_| !p.name.is_empty()) {
                settings.insert(p.name.clone(), v);
            }
        }
        let mut module = Self {
            name: if pm.properties.contains_key("__name__") {
                get(&pm.properties, "__name__")?
            } else {
                Some(pm.name.clone())
            },
            settings,
            info: get(&pm.properties, "__info__")?,
            placements: get(&pm.properties, "__placements__")?,
            routes: get(&pm.properties, "__routes__")?,
            instances: pm
                .subcircuits
                .iter()
                .map(|r| {
                    Ok((
                        r.name.clone(),
                        SubCircuitDocument::from_proto_subcircuit(r)?,
                    ))
                })
                .collect::<Result<_>>()?,
            ..Default::default()
        };
        for pin in pm.terminals.iter().flat_map(terminal_pins) {
            module.ports.insert(pin.clone(), pin);
        }
        // Modules written before the named-net encoding always carry `__placements__`.
        if pm.properties.contains_key("__nets__") || !pm.properties.contains_key("__placements__") {
            module.read_named_nets(pm)?;
        } else {
            for c in &pm.connections {
                if let (Some(src), Some(tgt)) = (&c.source, &c.target) {
                    if c.name.starts_with("port_") {
                        module
                            .ports
                            .insert(src.terminal_name.clone(), reference(tgt));
                    } else {
                        module.connections.insert(reference(src), reference(tgt));
                    }
                }
            }
        }
        for bus in &pm.buses {
            let members = if bus.properties.contains_key("__members__") {
                get(&bus.properties, "__members__")?
            } else {
                let mut members = Vec::new();
                for c in &bus.connections {
                    for t in [&c.source, &c.target].into_iter().flatten() {
                        let r = reference(t);
                        if members.last() != Some(&r) {
                            members.push(r);
                        }
                    }
                }
                members
            };
            module.nets.push(members);
        }
        module.directives = pm.directives.iter().map(directive_from_proto).collect();
        let mut nets = BTreeMap::new();
        for c in &pm.connections {
            let properties = public(&c.properties);
            if !c.name.is_empty() && (c.domain != 0 || c.weight != 0 || !properties.is_empty()) {
                nets.entry(c.name.clone()).or_insert_with(|| p::Connection {
                    name: c.name.clone(),
                    domain: c.domain,
                    weight: c.weight,
                    properties,
                    ..Default::default()
                });
            }
        }
        let parameters = if pm.parameters == module.proto_parameters()? {
            Vec::new()
        } else {
            pm.parameters.clone()
        };
        let mut order = BTreeMap::new();
        for (i, members) in module.nets.iter().enumerate() {
            if let Some(name) = module.net_name(i) {
                if module.netlist_order(members).as_ref() != Some(members) {
                    order.insert(name.to_owned(), members.clone());
                }
            }
        }
        let plain = merge_terminals(&[], &module.ports);
        // The nets a kfnetlist round trip writes, if it keeps their names but not order.
        let sequence = net_sequence(&pm.connections);
        let reordered = module
            .to_netlist()
            .ok()
            .map(|nl| CircuitDocument::from_netlist(pm.name.clone(), &nl))
            .and_then(|m| m.to_proto_circuit(&pm.name).ok())
            .is_some_and(|c| {
                let regenerated = net_sequence(&c.connections);
                regenerated != sequence
                    && regenerated.iter().collect::<HashSet<_>>()
                        == sequence.iter().collect::<HashSet<_>>()
            });
        Stash {
            properties: public(&pm.properties),
            class_name: pm.class_name.clone(),
            parameters,
            terminals: if pm.terminals == plain {
                Vec::new()
            } else {
                pm.terminals.clone()
            },
            model_interfaces: pm.model_interfaces.clone(),
            nets,
            order,
            sequence: if reordered { sequence } else { Vec::new() },
            ..Default::default()
        }
        .store(&mut module.info)?;
        Ok(module)
    }
}
impl NetlistDocument {
    /// The module carrying document-level data: the toplevel, else the one holding a
    /// document stash, else the last (morphnet's toplevel convention).
    fn lead(&self) -> Option<&CircuitDocument> {
        let has_stash = |m: &&CircuitDocument| {
            m.info
                .get(STASH)
                .is_some_and(|s| s.get("netlist").is_some())
        };
        self.toplevel
            .as_ref()
            .and_then(|t| self.modules.get(t))
            .or_else(|| self.modules.values().rev().find(has_stash))
            .or_else(|| self.modules.values().last())
    }
    pub fn to_proto_netlist(&self) -> Result<p::Netlist> {
        let lead = self.lead();
        // Every module carries the document header: the lead's wins, the others add
        // the external circuits it lacks (by name).
        let mut header: Option<p::Netlist> = None;
        for m in lead.into_iter().chain(self.modules.values()) {
            let Some(stashed) = Stash::take(&m.info)?.1.netlist else {
                continue;
            };
            match &mut header {
                None => header = Some(stashed),
                Some(h) => {
                    for ext in stashed.ext_circuits {
                        if h.ext_circuits.iter().all(|e| e.name != ext.name) {
                            h.ext_circuits.push(ext);
                        }
                    }
                }
            }
        }
        let toplevel = self.toplevel.clone().unwrap_or_default();
        let mut netlist = header.unwrap_or_else(|| p::Netlist {
            name: toplevel.clone(),
            ..Default::default()
        });
        if self.toplevel.is_some() || !self.modules.contains_key(&netlist.top_circuit) {
            netlist.top_circuit = toplevel; // a subset may not hold the stashed toplevel
        }
        netlist.circuits = self
            .modules
            .iter()
            .map(|(name, m)| m.to_proto_circuit(name))
            .collect::<Result<_>>()?;
        // morphnet writers print only document directives: lift every module's, lead first.
        let mut directives = Vec::new();
        for m in lead.into_iter().chain(self.modules.values()) {
            merge_directives(&mut directives, &m.directives);
        }
        netlist.directives = directives.iter().map(directive_to_proto).collect();
        Ok(netlist)
    }
    pub fn from_proto_netlist(c: &p::Netlist) -> Result<Self> {
        let mut doc = Self {
            modules: c
                .circuits
                .iter()
                .map(|m| Ok((m.name.clone(), CircuitDocument::from_proto_circuit(m)?)))
                .collect::<Result<_>>()?,
            toplevel: if c.top_circuit.is_empty() {
                None
            } else {
                Some(c.top_circuit.clone())
            },
        };
        let lead = doc
            .toplevel
            .clone()
            .filter(|t| doc.modules.contains_key(t))
            .or_else(|| doc.modules.keys().last().cloned());
        if let Some(lead) = lead.and_then(|k| doc.modules.get_mut(&k)) {
            let own = std::mem::take(&mut lead.directives);
            lead.directives = c.directives.iter().map(directive_from_proto).collect();
            merge_directives(&mut lead.directives, &own);
        }
        if !doc.modules.is_empty() {
            let header = p::Netlist {
                circuits: Vec::new(),
                directives: Vec::new(),
                ..c.clone()
            };
            let plain = p::Netlist {
                name: c.top_circuit.clone(),
                top_circuit: c.top_circuit.clone(),
                ..Default::default()
            };
            let declared: HashSet<&str> = c
                .circuits
                .iter()
                .map(|m| m.name.as_str())
                .chain(c.ext_circuits.iter().map(|e| e.name.as_str()))
                .collect();
            let mut undeclared: Vec<String> = c
                .circuits
                .iter()
                .flat_map(|m| &m.subcircuits)
                .map(|r| r.circuit_name.clone())
                .filter(|n| !declared.contains(n.as_str()))
                .collect();
            // Only a foreign source (this crate's encoding always has `__placements__`)
            // decides which masters stay undeclared; documents get the bridge's fill.
            if c.circuits
                .iter()
                .all(|m| m.properties.contains_key("__placements__"))
            {
                undeclared.clear();
            }
            for m in &c.circuits {
                undeclared.extend(get::<Vec<String>>(&m.properties, "__undeclared__")?);
            }
            undeclared.sort();
            undeclared.dedup();
            let header = (header != plain).then_some(header);
            for module in doc.modules.values_mut() {
                let (_, mut stash) = Stash::take(&module.info)?;
                stash.netlist = header.clone();
                stash.undeclared = undeclared.clone();
                stash.store(&mut module.info)?;
            }
        }
        Ok(doc)
    }
    #[deprecated(note = "renamed to to_proto_netlist")]
    pub fn to_proto_circuit(&self) -> Result<p::Netlist> {
        self.to_proto_netlist()
    }
    #[deprecated(note = "renamed to from_proto_netlist")]
    pub fn from_proto_circuit(c: &p::Netlist) -> Result<Self> {
        Self::from_proto_netlist(c)
    }
    pub fn to_proto(&self) -> Result<Vec<u8>> {
        Ok(self.to_proto_netlist()?.encode_to_vec())
    }
    pub fn from_proto(data: &[u8]) -> Result<Self> {
        Self::from_proto_netlist(&p::Netlist::decode(data).map_err(error)?)
    }
}
