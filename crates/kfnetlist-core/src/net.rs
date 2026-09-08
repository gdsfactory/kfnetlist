use crate::port::{NetlistPort, PortArrayRef, PortRef};
use serde::{Deserialize, Serialize};

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
/// connectivity. `from_members` sorts by (kind, fields) for stable equality and
/// hashing. Direct field mutation and serde loading preserve the supplied order;
/// call `sort_in_place` or `Netlist::normalize` before comparing unsorted inputs.
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Net {
    pub members: Vec<NetMember>,
}

impl Net {
    pub fn sort_in_place(&mut self) {
        self.members.sort();
    }

    pub fn from_members(members: Vec<NetMember>) -> Self {
        let mut net = Net { members };
        net.sort_in_place();
        net
    }
}
