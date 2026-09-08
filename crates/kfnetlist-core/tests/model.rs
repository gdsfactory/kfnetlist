use kfnetlist_core::{
    from_json, to_json, ArrayDirection, Error, Net, NetMember, Netlist, NetlistInstance,
    NetlistPort, PlacedExtra, PlacedInstance, PlacedNetlist, Placement, PortArrayRef, PortRef,
};
use serde_json::json;

fn reference(instance: &str, port: &str) -> NetMember {
    NetMember::Ref(PortRef {
        instance: instance.into(),
        port: port.into(),
    })
}

fn array_reference(instance: &str, ia: i64, ib: i64) -> NetMember {
    NetMember::ArrayRef(PortArrayRef {
        instance: instance.into(),
        port: "p".into(),
        ia,
        ib,
    })
}

fn add_instance(nl: &mut Netlist, name: &str, component: &str) {
    nl.create_inst(name.into(), "pdk".into(), component.into(), json!({}), 2, 3)
        .unwrap();
}

#[test]
fn serde_wire_round_trip_restores_names_and_preserves_member_variants() {
    let wire = json!({
        "instances": {"unit": {"kcl": "pdk", "component": "cell", "settings": {}, "array": {"na": 2, "nb": 3}}},
        "ports": [{"name": "in"}],
        "nets": [[{"instance": "unit", "port": "p", "ia": 0, "ib": 2}, {"name": "in"}, {"instance": "unit", "port": "q"}]]
    });
    let nl: Netlist = serde_json::from_value(wire.clone()).unwrap();
    assert_eq!(nl.instances["unit"].name, "unit");
    assert!(matches!(nl.nets[0].members[0], NetMember::ArrayRef(_)));
    assert_eq!(serde_json::to_value(&nl).unwrap(), wire);
    assert_eq!(from_json::<Netlist>(&to_json(&nl).unwrap()).unwrap(), nl);
    let sorted = nl.normalize(None, None, None).unwrap();
    assert!(matches!(sorted.nets[0].members[0], NetMember::Port(_)));
    assert!(matches!(sorted.nets[0].members[1], NetMember::Ref(_)));
    assert!(matches!(sorted.nets[0].members[2], NetMember::ArrayRef(_)));
    let instance: NetlistInstance = from_json(r#"{"kcl":"pdk","component":"cell"}"#).unwrap();
    assert_eq!(
        serde_json::to_value(&instance).unwrap(),
        json!({"kcl":"pdk","component":"cell","settings":{}})
    );
}

#[test]
fn serde_rejects_unknown_fields_and_reports_native_errors() {
    for data in [
        r#"{"unexpected":1}"#,
        r#"{"ports":[{"name":"p","unexpected":1}]}"#,
        r#"{"nets":[[{"instance":"i","port":"p","ia":1}]]}"#,
        r#"{"instances":{"i":{"kcl":"p","component":"c","unexpected":1}}}"#,
    ] {
        assert!(matches!(
            from_json::<Netlist>(data),
            Err(Error::Deserialize(_))
        ));
    }
    assert!(
        matches!(Netlist::default().get_instance("absent"), Err(Error::MissingInstance(name)) if name == "absent")
    );
}

#[test]
fn failed_mutations_leave_existing_connectivity_intact() {
    let mut nl = Netlist::default();
    add_instance(&mut nl, "unit", "cell");
    let before = nl.clone();
    assert!(matches!(
        nl.create_inst(
            "unit".into(),
            "pdk".into(),
            "replacement".into(),
            json!({}),
            -1,
            2
        ),
        Err(Error::InvalidArrayDimensions { na: -1, nb: 2 })
    ));
    assert_eq!(nl, before);
    assert!(matches!(
        nl.create_net([reference("unit", "p"), reference("absent", "p")]),
        Err(Error::UnknownInstance(_))
    ));
    assert!(matches!(
        nl.create_net([NetMember::Port(NetlistPort {
            name: "absent".into()
        })]),
        Err(Error::UndefinedPort(_))
    ));
    assert!(matches!(
        nl.create_net([array_reference("unit", 3, 1)]),
        Err(Error::ArrayIndexOutOfBounds {
            direction: ArrayDirection::A,
            size: 2,
            index: 3,
            ..
        })
    ));
    assert!(matches!(
        nl.create_net([array_reference("unit", 1, 4)]),
        Err(Error::ArrayIndexOutOfBounds {
            direction: ArrayDirection::B,
            ..
        })
    ));
    assert_eq!(nl, before);
}

#[test]
fn array_reference_validation_preserves_legacy_index_rules() {
    let mut nl = Netlist::default();
    add_instance(&mut nl, "array", "cell");
    nl.create_net([array_reference("array", 1, 1)]).unwrap();
    assert_eq!(nl.nets[0].members, vec![reference("array", "p")]);
    nl.create_net([array_reference("array", 0, -1)]).unwrap();
    assert!(matches!(nl.nets[1].members[0], NetMember::ArrayRef(_)));
    nl.create_inst(
        "single".into(),
        "pdk".into(),
        "cell".into(),
        json!({}),
        0,
        1,
    )
    .unwrap();
    assert!(nl.instances["single"].array.is_none());
    nl.create_net([array_reference("single", 1, 1)]).unwrap();
    assert!(matches!(
        nl.create_net([array_reference("single", 0, 0)]),
        Err(Error::NotArrayInstance(_))
    ));
    let net = Net::from_members(vec![array_reference("array", 1, 1)]);
    nl.add_net(&net).unwrap();
    assert_eq!(
        nl.nets.last().unwrap().members,
        vec![reference("array", "p")]
    );
}

#[test]
fn open_detection_and_difference_return_owned_results_in_source_order() {
    let mut nl = Netlist::default();
    let z = nl.create_port("z".into());
    nl.create_port("b".into());
    nl.create_port("a".into());
    nl.create_net([NetMember::Port(z)]).unwrap();
    nl.nets.push(Net::from_members(vec![]));
    let opens = nl.detect_opens();
    assert_eq!(opens.unconnected_ports, ["a", "b"]);
    assert_eq!(opens.singleton_nets, vec![nl.nets[0].clone()]);
    let mut reference = Netlist::default();
    let port = reference.create_port("reference".into());
    reference.create_net([NetMember::Port(port)]).unwrap();
    reference.nets.push(reference.nets[0].clone());
    let difference = nl.find_net_difference(&reference);
    assert_eq!(difference.missing, reference.nets);
    assert_eq!(difference.extra, nl.nets);
    nl.nets.clear();
    assert_eq!(opens.singleton_nets.len(), 1);
    assert_eq!(difference.extra.len(), 2);
}

#[test]
fn normalization_merges_transitive_equivalent_nets_without_changing_source() {
    let mut nl = Netlist::default();
    for name in ["b", "a"] {
        add_instance(&mut nl, name, "pad");
    }
    nl.instances["a"].settings = json!({"nested": [1.0, {"fraction": 1.5, "whole": -2.0}]});
    let top = nl.create_port("in".into());
    nl.create_net([reference("a", "e2"), NetMember::Port(top)])
        .unwrap();
    nl.create_net([reference("a", "e1"), reference("b", "e2")])
        .unwrap();
    nl.create_net([reference("b", "e1")]).unwrap();
    let before = to_json(&nl).unwrap();
    let equivalent = [("pad".into(), vec![vec!["e1".into(), "e2".into()]])].into();
    let normalized = nl
        .normalize(Some("top".into()), Some(equivalent), None)
        .unwrap();
    assert_eq!(to_json(&nl).unwrap(), before);
    assert_eq!(normalized.instance_names(), ["a", "b"]);
    assert_eq!(
        normalized.nets,
        vec![Net::from_members(vec![
            NetMember::Port(NetlistPort { name: "in".into() }),
            reference("a", "e1"),
            reference("b", "e1")
        ])]
    );
    let settings = &normalized.instances["a"].settings;
    assert!(settings["nested"][0].is_i64());
    assert!(settings["nested"][1]["whole"].is_i64());
    assert!(settings["nested"][1]["fraction"].is_f64());
    assert_eq!(normalized.normalize(None, None, None).unwrap(), normalized);
}

#[test]
fn normalization_keeps_array_elements_separate_and_validates_top_port_mapping() {
    let mut nl = Netlist::default();
    add_instance(&mut nl, "array", "pad");
    let top = nl.create_port("in".into());
    nl.create_net([array_reference("array", 0, 1), NetMember::Port(top)])
        .unwrap();
    nl.create_net([array_reference("array", 0, 2)]).unwrap();
    let equivalent = [("pad".into(), vec![vec!["canonical".into(), "p".into()]])].into();
    let normalized = nl
        .normalize(Some("top".into()), Some(equivalent), None)
        .unwrap();
    assert_eq!(normalized.nets.len(), 2);
    let equivalent = [("pad".into(), vec![vec!["p".into()]])].into();
    let mapping = [
        ("pad".into(), [("p".into(), "p".into())].into()),
        ("top".into(), [("in".into(), "missing".into())].into()),
    ]
    .into();
    assert!(
        matches!(nl.normalize(Some("top".into()), Some(equivalent), Some(mapping)), Err(Error::MissingCanonicalPort(name)) if name == "missing")
    );
}

#[test]
fn placed_netlist_round_trip_and_flatten_preserve_surviving_geometry() {
    let mut nl = PlacedNetlist::default();
    for (name, x) in [("a", 1.0), ("flat", 2.0), ("b", 3.0)] {
        nl.create_inst(
            name.into(),
            "pdk".into(),
            "cell".into(),
            json!({}),
            1,
            1,
            PlacedExtra {
                cell: format!("placed_{name}"),
                placement: Placement {
                    x,
                    ..Placement::default()
                },
            },
        )
        .unwrap();
    }
    nl.netlist
        .create_net([reference("a", "p"), reference("flat", "in")])
        .unwrap();
    nl.netlist
        .create_net([reference("flat", "out"), reference("b", "p")])
        .unwrap();
    let serialized = to_json(&nl).unwrap();
    let loaded: PlacedNetlist = from_json(&serialized).unwrap();
    assert_eq!(loaded, nl);
    assert_eq!(loaded.get_instance("a").unwrap().instance.name, "a");
    let instance: PlacedInstance =
        from_json(&to_json(&loaded.get_instance("a").unwrap()).unwrap()).unwrap();
    assert!(instance.instance.name.is_empty());
    assert_eq!(instance.extra.cell, "placed_a");
    assert!(matches!(
        nl.create_inst(
            "a".into(),
            "p".into(),
            "replacement".into(),
            json!({}),
            -1,
            1,
            PlacedExtra::default()
        ),
        Err(Error::InvalidArrayDimensions { .. })
    ));
    assert_eq!(nl, loaded);
    nl.flatten_instances(vec!["flat".into()]).unwrap();
    assert_eq!(
        nl.netlist.nets,
        vec![Net::from_members(vec![
            reference("a", "p"),
            reference("b", "p")
        ])]
    );
    assert!(!nl.extras.contains_key("flat"));
    assert_eq!(nl.get_instance("a").unwrap().extra.placement.x, 1.0);
    assert_eq!(nl.get_instance("b").unwrap().extra.placement.x, 3.0);
}

#[test]
fn placed_upgrade_drops_unknown_extras_and_defaults_missing_geometry() {
    let mut nl = Netlist::default();
    add_instance(&mut nl, "known", "cell");
    let placed = PlacedNetlist::new(nl, [("unknown".into(), PlacedExtra::default())].into());
    assert!(placed.extras.is_empty());
    assert_eq!(
        placed.get_instance("known").unwrap().extra,
        PlacedExtra::default()
    );
    let reloaded: PlacedNetlist = from_json(&to_json(&placed).unwrap()).unwrap();
    assert_eq!(
        reloaded.get_instance("known").unwrap(),
        placed.get_instance("known").unwrap()
    );
}
