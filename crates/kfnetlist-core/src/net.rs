use crate::port::{NetlistPort, PortArrayRef, PortRef};
use serde::de::{self, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::cmp::Ordering;
use std::fmt;
use std::hash::{Hash, Hasher};

/// Native enum for the three kinds of net members.
///
/// Variant declaration order is significant:
///   1. Derived `PartialOrd`/`Ord` orders by variant index, giving the
///      kind-tag ordering Port < Ref < ArrayRef.
///   2. `serde(untagged)` tries variants in declaration order. NetlistPort
///      (only `name`) and PortRef (`instance, port`) are uniquely identified
///      by their fields. PortArrayRef has the same `instance, port` plus
///      `ia, ib`; `deny_unknown_fields` on PortRef makes serde reject the
///      array shape and fall through to ArrayRef.
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(untagged)]
pub enum NetMember {
    Port(NetlistPort),
    Ref(PortRef),
    ArrayRef(PortArrayRef),
}

/// A net: an unordered collection of port members that share electrical
/// connectivity, optionally carrying a name.
///
/// `from_members` sorts by (kind, fields) for stable equality and hashing.
/// Direct field mutation and serde loading preserve the supplied order;
/// call `sort_in_place` or `Netlist::normalize` before comparing unsorted inputs.
///
/// # Names are not identity
///
/// The name travels with the net and is preserved by net merging, but
/// `PartialEq`, `Hash` and `Ord` deliberately ignore it: two nets with the same
/// members compare equal whether or not they are named, and whether or not the
/// names match. Connectivity comparison therefore keeps the semantics it had
/// before names existed. A name-sensitive comparison is a separate, opt-in API;
/// it is not what equality means here.
///
/// # Wire format
///
/// An unnamed net keeps the historical shape — a bare JSON array of members —
/// so existing netlists and consumers are unaffected. A named net is an object
/// `{"name": ..., "members": [...]}`. Reading accepts both shapes; a net read
/// from the object form without a `name` (or with `"name": null`) is unnamed and
/// re-serializes as a bare array. The object form requires `members` and rejects
/// unknown fields, like the rest of the wire format, so a misspelled key cannot
/// silently read as an empty net. Writing the object form is a forward
/// incompatibility: a reader older than names cannot read a file containing a
/// named net (its net deserializer expects an array).
#[derive(Clone, Debug)]
pub struct Net {
    pub name: Option<String>,
    pub members: Vec<NetMember>,
}

impl Net {
    pub fn sort_in_place(&mut self) {
        self.members.sort();
    }

    /// Sorted, unnamed net.
    pub fn from_members(members: Vec<NetMember>) -> Self {
        let mut net = Net {
            name: None,
            members,
        };
        net.sort_in_place();
        net
    }

    /// Sorted net carrying `name`.
    pub fn with_name(members: Vec<NetMember>, name: impl Into<String>) -> Self {
        let mut net = Net {
            name: Some(name.into()),
            members,
        };
        net.sort_in_place();
        net
    }
}

impl PartialEq for Net {
    fn eq(&self, other: &Self) -> bool {
        self.members == other.members
    }
}

impl Eq for Net {}

impl Hash for Net {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.members.hash(state);
    }
}

impl Ord for Net {
    fn cmp(&self, other: &Self) -> Ordering {
        self.members.cmp(&other.members)
    }
}

impl PartialOrd for Net {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

/// Wire form of a named net: `{"name": ..., "members": [...]}`.
#[derive(Serialize)]
struct NamedNet<'a> {
    name: &'a str,
    members: &'a [NetMember],
}

impl Serialize for Net {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match &self.name {
            None => self.members.serialize(serializer),
            Some(name) => NamedNet {
                name,
                members: &self.members,
            }
            .serialize(serializer),
        }
    }
}

/// Members of the object form of a net, for serde's error messages.
const NET_FIELDS: &[&str] = &["name", "members"];

impl<'de> Deserialize<'de> for Net {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct NetVisitor;

        impl<'de> Visitor<'de> for NetVisitor {
            type Value = Net;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(
                    "a list of net members, or an object with an optional \"name\" and \"members\"",
                )
            }

            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Net, A::Error> {
                let mut members: Vec<NetMember> = Vec::with_capacity(seq.size_hint().unwrap_or(0));
                while let Some(member) = seq.next_element()? {
                    members.push(member);
                }
                Ok(Net {
                    name: None,
                    members,
                })
            }

            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Net, A::Error> {
                let mut name: Option<String> = None;
                let mut members: Option<Vec<NetMember>> = None;
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "name" => name = map.next_value::<Option<String>>()?,
                        "members" => members = Some(map.next_value()?),
                        other => return Err(de::Error::unknown_field(other, NET_FIELDS)),
                    }
                }
                Ok(Net {
                    name,
                    // Strict on purpose: an object that lost or misspelled its
                    // members would otherwise read as an empty net.
                    members: members.ok_or_else(|| de::Error::missing_field("members"))?,
                })
            }
        }

        deserializer.deserialize_any(NetVisitor)
    }
}
