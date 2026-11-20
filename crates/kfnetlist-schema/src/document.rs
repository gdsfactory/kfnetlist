use super::{error, Error, Result};
use indexmap::IndexMap;
use kfnetlist_core::{Directive, Net, NetMember, Netlist, NetlistPort, PortArrayRef, PortRef};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ArraySpec {
    pub na: i64,
    pub nb: i64,
}
impl Default for ArraySpec {
    fn default() -> Self {
        Self { na: 1, nb: 1 }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubCircuitDocument {
    pub component: String,
    #[serde(default)]
    pub settings: Map<String, Value>,
    #[serde(default)]
    pub array: Option<ArraySpec>,
    #[serde(default)]
    pub info: Map<String, Value>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct CircuitDocument {
    pub name: Option<String>,
    pub settings: Map<String, Value>,
    pub info: Map<String, Value>,
    pub instances: IndexMap<String, SubCircuitDocument>,
    pub placements: Map<String, Value>,
    pub ports: IndexMap<String, String>,
    pub connections: IndexMap<String, String>,
    pub nets: Vec<Vec<String>>,
    /// Name of `nets[i]`; empty (or past the end) means unnamed.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub net_names: Vec<String>,
    pub routes: Map<String, Value>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub directives: Vec<Directive>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct NetlistDocument {
    pub modules: IndexMap<String, CircuitDocument>,
    pub toplevel: Option<String>,
}
impl<'de> Deserialize<'de> for NetlistDocument {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        let mut raw = Map::<String, Value>::deserialize(deserializer)?;
        let toplevel = raw
            .remove("toplevel")
            .map(serde_json::from_value)
            .transpose()
            .map_err(serde::de::Error::custom)?
            .flatten();
        let modules = raw.remove("modules");
        if modules.as_ref().is_some_and(|v| !v.is_object()) {
            return Err(serde::de::Error::custom("modules must be a mapping"));
        }
        let explicit = modules
            .as_ref()
            .is_some_and(|v| v.as_object().is_some_and(|m| !m.is_empty()));
        if explicit {
            if !raw.is_empty() {
                return Err(serde::de::Error::custom(
                    "cannot mix modules with bare module fields",
                ));
            }
            Ok(Self {
                modules: serde_json::from_value(modules.unwrap())
                    .map_err(serde::de::Error::custom)?,
                toplevel,
            })
        } else if !raw.is_empty() {
            let module =
                serde_json::from_value(Value::Object(raw)).map_err(serde::de::Error::custom)?;
            Ok(Self {
                modules: IndexMap::from([("__root__".into(), module)]),
                toplevel: toplevel.or(Some("__root__".into())),
            })
        } else {
            Ok(Self {
                modules: modules
                    .map(serde_json::from_value)
                    .transpose()
                    .map_err(serde::de::Error::custom)?
                    .unwrap_or_default(),
                toplevel,
            })
        }
    }
}

/// Parse bare pins, instance pins, 1-based grid indices and 0-based bracket indices.
pub fn parse_port_ref(text: &str) -> Result<NetMember> {
    let text = text.trim();
    if text.is_empty() {
        return Err(Error("empty port reference".into()));
    }
    let Some((instance, port)) = text.split_once(',') else {
        return Ok(NetMember::Port(NetlistPort { name: text.into() }));
    };
    let instance = instance.trim();
    let port = port.trim();
    if instance.is_empty() || port.is_empty() || port.contains(',') {
        return Err(Error(format!("invalid port reference: {text}")));
    }
    let index = |s: &str| -> Result<i64> { s.parse::<i64>().map_err(error) };
    let array = if let Some((name, indices)) = instance.split_once('<') {
        let (a, b) = indices
            .strip_suffix('>')
            .and_then(|s| s.split_once('.'))
            .ok_or_else(|| Error(format!("invalid array reference: {text}")))?;
        Some((name, index(a)?, index(b)?))
    } else if let Some((name, n)) = instance.split_once('[') {
        let n = n
            .strip_suffix(']')
            .ok_or_else(|| Error(format!("invalid array reference: {text}")))?;
        let n = index(n)?;
        if n < 0 {
            return Err(Error("bracket indices must be nonnegative".into()));
        }
        Some((
            name,
            n.checked_add(1)
                .ok_or_else(|| Error("array index overflow".into()))?,
            1,
        ))
    } else {
        None
    };
    if let Some((name, ia, ib)) = array {
        if name.is_empty() || ia < 1 || ib < 1 {
            return Err(Error("array indices must be positive".into()));
        }
        Ok(NetMember::ArrayRef(PortArrayRef {
            instance: name.into(),
            port: port.into(),
            ia,
            ib,
        }))
    } else {
        Ok(NetMember::Ref(PortRef {
            instance: instance.into(),
            port: port.into(),
        }))
    }
}
fn unparse(member: &NetMember) -> String {
    match member {
        NetMember::Port(p) => p.name.clone(),
        NetMember::Ref(p) => format!("{},{}", p.instance, p.port),
        NetMember::ArrayRef(p) => format!("{}<{}.{}>,{}", p.instance, p.ia, p.ib, p.port),
    }
}
impl CircuitDocument {
    // An instance named like `X[3]` (an expanded Verilog instance array) is a plain
    // reference, not gdsfactory array syntax.
    fn member(&self, text: &str) -> Result<NetMember> {
        match text.split_once(',') {
            Some((inst, port))
                if self.instances.contains_key(inst.trim()) && !port.contains(',') =>
            {
                Ok(NetMember::Ref(PortRef {
                    instance: inst.trim().into(),
                    port: port.trim().into(),
                }))
            }
            _ => parse_port_ref(text),
        }
    }
    /// `members` in the order a `Netlist` net stores them (sorted).
    pub(crate) fn netlist_order(&self, members: &[String]) -> Option<Vec<String>> {
        let members = members.iter().map(|m| self.member(m).ok());
        let net = Net::from_members(members.collect::<Option<_>>()?);
        Some(net.members.iter().map(unparse).collect())
    }
    pub fn to_netlist(&self) -> Result<Netlist> {
        let mut nl = Netlist {
            directives: self.directives.clone(),
            info: self.info.clone(),
            ..Netlist::default()
        };
        for name in self.ports.keys() {
            nl.create_port(name.clone());
        }
        for (name, inst) in &self.instances {
            let array = match &inst.array {
                Some(a) => Some(a.clone()),
                None => inst
                    .settings
                    .get("array_size")
                    .map(|v| {
                        v.as_i64()
                            .filter(|n| *n > 0)
                            .map(|na| ArraySpec { na, nb: 1 })
                            .ok_or_else(|| Error("array_size must be a positive integer".into()))
                    })
                    .transpose()?,
            };
            let (na, nb) = array.as_ref().map_or((0, 0), |a| (a.na, a.nb));
            if array.is_some() && (na < 1 || nb < 1) {
                return Err(Error("array dimensions must be positive".into()));
            }
            nl.create_inst_with_info(
                name.clone(),
                String::new(),
                inst.component.clone(),
                Value::Object(inst.settings.clone()),
                na,
                nb,
                inst.info.clone(),
            )
            .map_err(error)?;
        }
        let member = |text: &str| self.member(text);
        for (src, tgt) in &self.connections {
            nl.create_net([member(src)?, member(tgt)?]).map_err(error)?;
        }
        for (i, net) in self.nets.iter().enumerate() {
            let members = net.iter().map(|s| member(s)).collect::<Result<Vec<_>>>()?;
            match self.net_name(i) {
                Some(name) => nl.create_named_net(members, name),
                None => nl.create_net(members),
            }
            .map_err(error)?;
        }
        for (name, reference) in &self.ports {
            if name == reference {
                continue;
            }
            nl.create_net([
                NetMember::Port(NetlistPort { name: name.clone() }),
                member(reference)?,
            ])
            .map_err(error)?;
        }
        Ok(nl)
    }
    /// Recover connectivity and instance metadata. Layout/routing data is absent from Netlist.
    pub fn from_netlist(name: String, nl: &Netlist) -> Self {
        let instances = nl
            .instances
            .iter()
            .map(|(name, i)| {
                (
                    name.clone(),
                    SubCircuitDocument {
                        component: i.component.clone(),
                        settings: i.settings.as_object().cloned().unwrap_or_default(),
                        array: i.array.as_ref().map(|a| ArraySpec { na: a.na, nb: a.nb }),
                        info: i.info.clone(),
                    },
                )
            })
            .collect();
        let mut module = Self {
            name: Some(name),
            instances,
            info: nl.info.clone(),
            directives: nl.directives.clone(),
            ..Self::default()
        };
        for net in &nl.nets {
            let (pins, others): (Vec<_>, Vec<_>) = net
                .members
                .iter()
                .partition(|m| matches!(m, NetMember::Port(_)));
            // An unnamed port net: the plain `ports` form, which has no place for a name.
            if pins.len() == 1 && others.len() == 1 && net.name.is_none() {
                module.ports.insert(unparse(pins[0]), unparse(others[0]));
            } else {
                module.push_net(net.members.iter().map(unparse).collect(), net.name.clone());
            }
        }
        // Preserve declared pins, including pins in multi-terminal nets and unconnected pins.
        for p in &nl.ports {
            module
                .ports
                .entry(p.name.clone())
                .or_insert_with(|| p.name.clone());
        }
        module
    }
    pub fn net_name(&self, i: usize) -> Option<&str> {
        self.net_names
            .get(i)
            .map(String::as_str)
            .filter(|n| !n.is_empty())
    }
    pub(crate) fn push_net(&mut self, members: Vec<String>, name: Option<String>) {
        if let Some(name) = name {
            self.net_names.resize(self.nets.len(), String::new());
            self.net_names.push(name);
        }
        self.nets.push(members);
    }
}
impl NetlistDocument {
    pub fn from_yaml(text: &str) -> Result<Self> {
        serde_yaml_ng::from_str(text).map_err(error)
    }
    pub fn to_yaml(&self) -> Result<String> {
        serde_yaml_ng::to_string(self).map_err(error)
    }
    pub fn load_pic_yaml(path: impl AsRef<std::path::Path>) -> Result<Self> {
        Self::from_yaml(&std::fs::read_to_string(path).map_err(error)?)
    }
    pub fn to_netlists(&self) -> Result<IndexMap<String, Netlist>> {
        if let Some(top) = &self.toplevel {
            if !self.modules.contains_key(top) {
                return Err(Error(format!("unknown toplevel module: {top}")));
            }
        }
        self.modules
            .iter()
            .map(|(name, m)| Ok((name.clone(), m.to_netlist()?)))
            .collect()
    }
    pub fn from_netlists(netlists: &IndexMap<String, Netlist>, toplevel: Option<String>) -> Self {
        Self {
            modules: netlists
                .iter()
                .map(|(name, nl)| {
                    (
                        name.clone(),
                        CircuitDocument::from_netlist(name.clone(), nl),
                    )
                })
                .collect(),
            toplevel,
        }
    }
}
