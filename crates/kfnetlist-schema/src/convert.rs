use super::{error, proto as p, CircuitDocument, NetlistDocument, Result, SubCircuitDocument};
use indexmap::IndexMap;
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
// ponytail: non-numeric values (model_ref) are dropped from settings; map them when a consumer needs them.
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
fn reference(t: &p::TerminalReference) -> String {
    if t.instance_name.is_empty() {
        t.terminal_name.clone()
    } else {
        format!("{},{}", t.instance_name, t.terminal_name)
    }
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
    fn to_proto_subcircuit(&self, name: &str) -> Result<p::SubCircuit> {
        let mut properties = Properties::new();
        put(&mut properties, "__array__", &self.array)?;
        put(&mut properties, "__info__", &self.info)?;
        let mut parameters = Vec::new();
        for (key, value) in &self.settings {
            if let Some(v) = parameter(value) {
                parameters.push(p::Parameter {
                    name: key.clone(),
                    default_value: Some(v),
                    ..Default::default()
                });
            }
            // Keep exact JSON types/integers alongside the numeric protobuf representation.
            put(&mut properties, &format!("__setting__{key}"), value)?;
        }
        Ok(p::SubCircuit {
            name: name.into(),
            circuit_name: self.component.clone(),
            parameters,
            properties,
            ..Default::default()
        })
    }
    fn from_proto_subcircuit(r: &p::SubCircuit) -> Result<Self> {
        let mut settings: Map<String, Value> = r
            .parameters
            .iter()
            .filter(|p| !p.name.is_empty())
            .filter_map(|p| Some((p.name.clone(), number(p.default_value.as_ref()?)?)))
            .collect();
        for (k, v) in &r.properties {
            if let Some(k) = k.strip_prefix("__setting__") {
                settings.insert(k.into(), serde_json::from_str(v).map_err(error)?);
            }
        }
        Ok(Self {
            component: r.circuit_name.clone(),
            settings,
            array: get(&r.properties, "__array__")?,
            info: get(&r.properties, "__info__")?,
        })
    }
}
impl CircuitDocument {
    fn to_proto_circuit(&self, name: &str) -> Result<p::Circuit> {
        let mut properties = Properties::new();
        put(&mut properties, "__name__", &self.name)?;
        put(&mut properties, "__placements__", &self.placements)?;
        put(&mut properties, "__routes__", &self.routes)?;
        put(&mut properties, "__info__", &self.info)?;
        put(&mut properties, "__nets__", &"named")?;
        let mut parameters = Vec::new();
        for (name, value) in &self.settings {
            let mut properties = Properties::new();
            put(&mut properties, "__json_value__", value)?;
            parameters.push(p::Parameter {
                name: name.clone(),
                default_value: parameter(value),
                properties,
                ..Default::default()
            });
        }
        let subcircuits = self
            .instances
            .iter()
            .map(|(name, i)| i.to_proto_subcircuit(name))
            .collect::<Result<_>>()?;
        let terminals = self
            .ports
            .keys()
            .map(|name| p::Terminal {
                name: name.clone(),
                ..Default::default()
            })
            .collect();
        // morphnet's encoding, which its writers read: a net is a star of connections named
        // after the net, from the port's net node (empty instance) or else the first pin.
        // `__from__`/`__members__` (ignored by morphnet) restore the exact document.
        // Same order as the pre-morphnet encoding: connections, ports, nets.
        let groups = self
            .connections
            .iter()
            .map(|(src, tgt)| ("conn", vec![src.clone(), tgt.clone()]))
            .chain(
                self.ports
                    .iter()
                    .filter(|(name, target)| name != target)
                    .map(|(name, target)| ("port", vec![name.clone(), target.clone()])),
            )
            .chain(self.nets.iter().map(|members| ("net", members.clone())));
        let mut connections = Vec::new();
        for (i, (from, members)) in groups.enumerate() {
            // ponytail: document nets carry no names, so Netlist net names become the port
            // name or net_<i>; add names to document::CircuitDocument to keep them.
            let port = members.iter().find(|m| !m.contains(','));
            let net = port.cloned().unwrap_or_else(|| format!("net_{i}"));
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
            }
            put(&mut star[0].properties, "__members__", &members)?;
            connections.extend(star);
        }
        Ok(p::Circuit {
            name: name.into(),
            terminals,
            parameters,
            subcircuits,
            connections,
            properties,
            ..Default::default()
        })
    }
    fn read_named_nets(&mut self, pm: &p::Circuit) -> Result<()> {
        let terminals: HashSet<&str> = pm.terminals.iter().map(|t| t.name.as_str()).collect();
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
                        ("net", _) => self.nets.push(members),
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
        self.nets
            .extend(foreign.into_values().filter(|m| !m.is_empty()));
        Ok(())
    }
    fn from_proto_circuit(pm: &p::Circuit) -> Result<Self> {
        let mut settings = Map::new();
        for p in &pm.parameters {
            if let Some(v) = p.properties.get("__json_value__") {
                settings.insert(p.name.clone(), serde_json::from_str(v).map_err(error)?);
            } else if let Some(v) = p.default_value.as_ref().and_then(number) {
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
        for t in &pm.terminals {
            module.ports.insert(t.name.clone(), t.name.clone());
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
        Ok(module)
    }
}
impl NetlistDocument {
    pub fn to_proto_netlist(&self) -> Result<p::Netlist> {
        Ok(p::Netlist {
            name: self.toplevel.clone().unwrap_or_default(),
            top_circuit: self.toplevel.clone().unwrap_or_default(),
            circuits: self
                .modules
                .iter()
                .map(|(name, m)| m.to_proto_circuit(name))
                .collect::<Result<_>>()?,
            ..Default::default()
        })
    }
    pub fn from_proto_netlist(c: &p::Netlist) -> Result<Self> {
        Ok(Self {
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
        })
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
