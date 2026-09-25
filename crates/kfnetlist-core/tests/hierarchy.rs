use indexmap::IndexMap;
use kfnetlist_core::{
    from_json, hierarchy_from_json, to_json, validate_hierarchy, Error, FlattenOptions,
    HierarchicalNetlist, LeafNetlistInstance, Netlist, NetlistInstance, RefNetlistInstance,
};
use serde_json::json;

#[test]
fn explicit_variants_round_trip_and_remain_distinct() {
    let wire = json!({"kcl": "pdk", "component": "arm", "settings": {"length": 10}});
    let leaf: NetlistInstance = serde_json::from_value(wire.clone()).unwrap();
    assert!(matches!(leaf, NetlistInstance::Leaf(_)));
    assert_eq!(serde_json::to_value(&leaf).unwrap(), wire);
    let mut referenced = wire.clone();
    referenced["netlist_id"] = json!("arm_10");
    let reference: NetlistInstance = serde_json::from_value(referenced.clone()).unwrap();
    assert!(matches!(reference, NetlistInstance::Ref(_)));
    assert_eq!(reference.netlist_id(), Some("arm_10"));
    assert_ne!(reference, leaf);
    assert_eq!(serde_json::to_value(&reference).unwrap(), referenced);
    let explicit: RefNetlistInstance = serde_json::from_value(referenced.clone()).unwrap();
    assert_eq!(serde_json::to_value(explicit).unwrap(), referenced);
    assert!(serde_json::from_value::<RefNetlistInstance>(wire).is_err());
    assert!(serde_json::from_value::<LeafNetlistInstance>(referenced).is_err());
    for value in [json!(null), json!(2), json!([]), json!({}), json!(false)] {
        assert!(serde_json::from_value::<NetlistInstance>(
            json!({"kcl":"pdk", "component":"arm", "netlist_id": value})
        )
        .is_err());
    }
}

#[test]
fn document_validates_shared_children_missing_targets_and_cycles() {
    let child = json!({"kcl":"pdk", "component":"arm", "settings":{}, "netlist_id":"child"});
    let data = json!({"top": {"instances": {"a":child, "b":child}}, "child": {}});
    let mut doc = hierarchy_from_json(&data.to_string()).unwrap();
    assert_eq!(doc["top"].instances["a"].name, "a");
    assert_eq!(hierarchy_from_json(&to_json(&doc).unwrap()).unwrap(), doc);
    doc.shift_remove("child");
    assert!(matches!(
        validate_hierarchy(&doc),
        Err(Error::MissingNetlistReference { .. })
    ));
    doc.insert(
        "child".into(),
        from_json::<Netlist>(
            r#"{"instances":{"back":{"kcl":"p","component":"top","netlist_id":"top"}}}"#,
        )
        .unwrap(),
    );
    assert!(matches!(
        validate_hierarchy(&doc),
        Err(Error::CyclicNetlistReference(_))
    ));
}

#[test]
fn deep_hierarchy_validation_does_not_recurse_on_the_call_stack() {
    let mut doc = HierarchicalNetlist::new();
    for i in 0..5000 {
        let value = if i == 4999 {
            json!({})
        } else {
            json!({"instances":{"next":{"kcl":"p", "component":"factory", "netlist_id":(i+1).to_string()}}})
        };
        doc.insert(i.to_string(), serde_json::from_value(value).unwrap());
    }
    validate_hierarchy(&doc).unwrap();
}

#[test]
fn hierarchy_struct_validates_construction_edit_and_flatten() {
    let child: Netlist = from_json(
        r#"{"instances":{"wg":{"kcl":"pdk","component":"straight","settings":{}}},"nets":[[{"name":"in"},{"instance":"wg","port":"in"}],[{"instance":"wg","port":"out"},{"name":"out"}]],"ports":[{"name":"in"},{"name":"out"}]}"#,
    )
    .unwrap();
    let top: Netlist = from_json(
        r#"{"instances":{"arm":{"kcl":"pdk","component":"make_arm","settings":{},"netlist_id":"child"}},"nets":[[{"name":"in"},{"instance":"arm","port":"in"}],[{"instance":"arm","port":"out"},{"name":"out"}]],"ports":[{"name":"in"},{"name":"out"}]}"#,
    )
    .unwrap();
    let mut entries = IndexMap::new();
    entries.insert("top".into(), top);
    assert!(matches!(
        HierarchicalNetlist::from_netlists(entries.clone()),
        Err(Error::MissingNetlistReference { .. })
    ));
    entries.insert("child".into(), child);
    let mut hierarchy = HierarchicalNetlist::from_netlists(entries).unwrap();
    let options = FlattenOptions::new(None, None, true, false, false, ".".into());
    let flat = hierarchy.flatten("top", &options).unwrap();
    assert!(flat.instances.contains_key("arm.wg"));
    assert!(matches!(
        hierarchy.flatten("missing", &options),
        Err(Error::MissingNetlist(_))
    ));
    assert_eq!(
        hierarchy_from_json(&hierarchy.to_json().unwrap()).unwrap(),
        hierarchy
    );
    hierarchy.shift_remove("child");
    assert!(hierarchy.validate().is_err());
    assert!(hierarchy.to_json().is_err());
    assert!(hierarchy.flatten("top", &options).is_err());
    assert!(to_json(&hierarchy).is_err());
}
