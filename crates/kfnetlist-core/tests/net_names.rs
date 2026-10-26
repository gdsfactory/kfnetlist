//! Native optional net names: wire format, identity, and merge policy.

use kfnetlist_core::{
    flatten_netlist, from_json, to_json, FlattenOptions, Net, NetMember, Netlist, NetlistData,
    NetlistPort, PortRef,
};
use serde_json::json;
use std::collections::{HashMap, HashSet};
use std::hash::{DefaultHasher, Hash, Hasher};

fn reference(instance: &str, port: &str) -> NetMember {
    NetMember::Ref(PortRef {
        instance: instance.into(),
        port: port.into(),
    })
}

fn port(name: &str) -> NetMember {
    NetMember::Port(NetlistPort { name: name.into() })
}

fn add_instance(nl: &mut Netlist, name: &str, component: &str) {
    nl.create_inst(name.into(), "pdk".into(), component.into(), json!({}), 0, 0)
        .unwrap();
}

fn hash_of(net: &Net) -> u64 {
    let mut hasher = DefaultHasher::new();
    net.hash(&mut hasher);
    hasher.finish()
}

/// Add a net, named when `name` is given.
fn add_net(nl: &mut Netlist, members: Vec<NetMember>, name: Option<&str>) {
    match name {
        Some(name) => nl.create_named_net(members, name).unwrap(),
        None => nl.create_net(members).unwrap(),
    }
}

#[test]
fn unnamed_nets_keep_the_historical_wire_shape() {
    // Before names, a net *was* its member list. An unnamed net must still
    // serialize to exactly that.
    let net = Net::from_members(vec![reference("R1", "p")]);
    assert_eq!(to_json(&net).unwrap(), r#"[{"instance":"R1","port":"p"}]"#);
    assert_eq!(
        serde_json::to_value(&net).unwrap(),
        json!([{"instance": "R1", "port": "p"}])
    );
}

#[test]
fn named_net_is_an_object_and_round_trips() {
    let net = Net::with_name(vec![reference("R1", "p")], "GND");
    assert_eq!(
        to_json(&net).unwrap(),
        r#"{"name":"GND","members":[{"instance":"R1","port":"p"}]}"#
    );
    let loaded: Net = from_json(&to_json(&net).unwrap()).unwrap();
    assert_eq!(loaded.name.as_deref(), Some("GND"));
    assert_eq!(loaded, net);
}

#[test]
fn reading_accepts_both_shapes() {
    let from_array: Net = from_json(r#"[{"name":"in"}]"#).unwrap();
    assert_eq!(from_array.name, None);
    assert_eq!(from_array.members, vec![port("in")]);

    let from_object: Net = from_json(r#"{"name":"GND","members":[{"name":"in"}]}"#).unwrap();
    assert_eq!(from_object.name.as_deref(), Some("GND"));
    assert_eq!(from_object.members, vec![port("in")]);

    // An object without a name, and an explicit null, are both unnamed.
    let unnamed_object: Net = from_json(r#"{"members":[{"name":"in"}]}"#).unwrap();
    assert_eq!(unnamed_object.name, None);
    let null_name: Net = from_json(r#"{"name":null,"members":[{"name":"in"}]}"#).unwrap();
    assert_eq!(null_name, unnamed_object);

    // A memberless net round-trips in both shapes.
    let empty_named: Net = from_json(r#"{"name":"floating","members":[]}"#).unwrap();
    assert_eq!(empty_named.name.as_deref(), Some("floating"));
    assert_eq!(
        to_json(&empty_named).unwrap(),
        r#"{"name":"floating","members":[]}"#
    );
    let empty: Net = from_json("[]").unwrap();
    assert_eq!(empty, Net::from_members(vec![]));
    assert_eq!(to_json(&empty).unwrap(), "[]");
}

#[test]
fn the_object_form_is_strict_so_a_typo_cannot_empty_a_net() {
    // A misspelled or missing `members` would otherwise read as an empty net
    // and silently drop the connectivity.
    assert!(from_json::<Net>(r#"{"name":"MID","member":[{"instance":"R1","port":"n"}]}"#).is_err());
    assert!(from_json::<Net>(r#"{"name":"MID"}"#).is_err());
    assert!(from_json::<Net>("{}").is_err());
    assert!(from_json::<Net>(r#"{"names":"MID","members":[]}"#).is_err());
}

#[test]
fn netlist_round_trip_keeps_names_and_leaves_unnamed_nets_unchanged() {
    let mut nl = Netlist::default();
    add_instance(&mut nl, "R1", "res");
    add_instance(&mut nl, "R2", "res");
    let input = nl.create_port("in".into());
    nl.create_named_net([NetMember::Port(input), reference("R1", "p")], "in")
        .unwrap();
    nl.create_net([reference("R1", "n"), reference("R2", "p")])
        .unwrap();

    let document = serde_json::to_value(&nl).unwrap();
    assert_eq!(
        document["nets"],
        json!([
            {"name": "in", "members": [{"name": "in"}, {"instance": "R1", "port": "p"}]},
            [{"instance": "R1", "port": "n"}, {"instance": "R2", "port": "p"}],
        ])
    );

    let loaded: Netlist = from_json(&to_json(&nl).unwrap()).unwrap();
    assert_eq!(loaded.nets[0].name.as_deref(), Some("in"));
    assert_eq!(loaded.nets[1].name, None);
    assert_eq!(loaded, nl);
}

#[test]
fn names_are_not_identity() {
    let a = Net::with_name(vec![reference("R1", "p")], "A");
    let b = Net::with_name(vec![reference("R1", "p")], "B");
    let unnamed = Net::from_members(vec![reference("R1", "p")]);

    assert_eq!(a, b);
    assert_eq!(a, unnamed);
    assert_eq!(hash_of(&a), hash_of(&b));
    assert_eq!(a.cmp(&unnamed), std::cmp::Ordering::Equal);
    // Ordering still follows the members.
    assert!(unnamed < Net::from_members(vec![reference("R1", "q")]));

    // Netlist comparison is therefore unchanged by names.
    let mut named = Netlist::default();
    add_instance(&mut named, "R1", "res");
    named.create_named_net([reference("R1", "p")], "A").unwrap();
    let mut other = Netlist::default();
    add_instance(&mut other, "R1", "res");
    other.create_named_net([reference("R1", "p")], "B").unwrap();
    let mut plain = Netlist::default();
    add_instance(&mut plain, "R1", "res");
    plain.create_net([reference("R1", "p")]).unwrap();
    assert_eq!(named, other);
    assert_eq!(named, plain);

    // A HashSet of nets ignores names too.
    let set: HashSet<Net> = [a.clone(), b.clone(), unnamed.clone()].into();
    assert_eq!(set.len(), 1);
}

#[test]
fn removing_an_instance_keeps_the_lowest_indexed_name() {
    let touching = |nl: &mut Netlist| {
        add_instance(nl, "a", "leaf");
        add_instance(nl, "mid", "leaf");
        add_instance(nl, "b", "leaf");
    };

    // Both contributing nets named differently: the lower index wins.
    let mut nl = Netlist::default();
    touching(&mut nl);
    add_net(
        &mut nl,
        vec![reference("a", "p"), reference("mid", "in")],
        Some("first"),
    );
    add_net(
        &mut nl,
        vec![reference("mid", "out"), reference("b", "p")],
        Some("second"),
    );
    nl.remove_instances(vec!["mid".into()]).unwrap();
    assert_eq!(nl.nets.len(), 1);
    assert_eq!(nl.nets[0].name.as_deref(), Some("first"));
    assert_eq!(nl.nets[0].members.len(), 2);

    // Only the higher-indexed net is named: the merged net takes that name.
    let mut nl = Netlist::default();
    touching(&mut nl);
    add_net(
        &mut nl,
        vec![reference("a", "p"), reference("mid", "in")],
        None,
    );
    add_net(
        &mut nl,
        vec![reference("mid", "out"), reference("b", "p")],
        Some("second"),
    );
    nl.remove_instances(vec!["mid".into()]).unwrap();
    assert_eq!(nl.nets[0].name.as_deref(), Some("second"));

    // Neither named: the merged net stays unnamed.
    let mut nl = Netlist::default();
    touching(&mut nl);
    add_net(
        &mut nl,
        vec![reference("a", "p"), reference("mid", "in")],
        None,
    );
    add_net(
        &mut nl,
        vec![reference("mid", "out"), reference("b", "p")],
        None,
    );
    nl.remove_instances(vec!["mid".into()]).unwrap();
    assert_eq!(nl.nets[0].name, None);
}

#[test]
fn normalize_keeps_the_lowest_indexed_name() {
    let build = |names: [Option<&str>; 3]| {
        let mut nl = Netlist::default();
        for name in ["b", "a"] {
            add_instance(&mut nl, name, "pad");
        }
        let top = nl.create_port("in".into());
        add_net(
            &mut nl,
            vec![reference("a", "e2"), NetMember::Port(top)],
            names[0],
        );
        add_net(
            &mut nl,
            vec![reference("a", "e1"), reference("b", "e2")],
            names[1],
        );
        add_net(&mut nl, vec![reference("b", "e1")], names[2]);
        nl
    };

    let equivalent = [("pad".into(), vec![vec!["e1".into(), "e2".into()]])].into();

    // All three nets merge; the lowest-indexed named net wins.
    let normalized = build([Some("top_net"), Some("middle"), None])
        .normalize(Some("top".into()), Some(equivalent), None)
        .unwrap();
    assert_eq!(normalized.nets.len(), 1);
    assert_eq!(normalized.nets[0].name.as_deref(), Some("top_net"));

    // The only named net is not the lowest index; it still wins.
    let equivalent = [("pad".into(), vec![vec!["e1".into(), "e2".into()]])].into();
    let normalized = build([None, Some("middle"), None])
        .normalize(Some("top".into()), Some(equivalent), None)
        .unwrap();
    assert_eq!(normalized.nets.len(), 1);
    assert_eq!(normalized.nets[0].name.as_deref(), Some("middle"));

    // No names anywhere: the merged net is unnamed.
    let equivalent = [("pad".into(), vec![vec!["e1".into(), "e2".into()]])].into();
    let normalized = build([None, None, None])
        .normalize(Some("top".into()), Some(equivalent), None)
        .unwrap();
    assert_eq!(normalized.nets[0].name, None);
}

#[test]
fn flatten_keeps_the_lowest_indexed_name() {
    // Parent nets come first, so a parent name wins over a child name ...
    assert_eq!(
        flatten_names(Some("top_net"), Some("child_net")).as_deref(),
        Some("top_net")
    );
    // ... a child name survives when the parent net has none ...
    assert_eq!(
        flatten_names(None, Some("child_net")).as_deref(),
        Some("child_net")
    );
    // ... and a parent name survives when the child's is absent.
    assert_eq!(
        flatten_names(Some("top_net"), None).as_deref(),
        Some("top_net")
    );
    // Neither named: the merged net stays unnamed.
    assert_eq!(flatten_names(None, None), None);
}

/// Flatten a child netlist into a parent netlist through a shared port and
/// report the name of the merged net.
fn flatten_names(parent_name: Option<&str>, child_name: Option<&str>) -> Option<String> {
    let mut child = Netlist::default();
    add_instance(&mut child, "inner", "leaf");
    let input = child.create_port("input".into());
    add_net(
        &mut child,
        vec![NetMember::Port(input), reference("inner", "input")],
        child_name,
    );

    let mut top = Netlist::default();
    add_instance(&mut top, "sub", "child");
    let input = top.create_port("input".into());
    add_net(
        &mut top,
        vec![NetMember::Port(input), reference("sub", "input")],
        parent_name,
    );

    let output = flatten_netlist(
        top.into(),
        Some(&HashMap::from([("sub".into(), "child".into())])),
        &HashMap::from([("child".into(), NetlistData::from(child))]),
        &HashMap::new(),
        &FlattenOptions::new(None, None, true, false, false, ".".into()),
    )
    .unwrap();

    assert_eq!(output.data.nets.len(), 1);
    assert!(output.data.instances.contains_key("sub.inner"));
    output.data.nets[0].name.clone()
}
