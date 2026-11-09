use kfnetlist_core::{NetMember, Netlist};
use kfnetlist_schema::{proto, CircuitDocument, NetlistDocument};
use prost::Message;
use serde_json::json;

fn document() -> NetlistDocument {
    serde_json::from_value(json!({
        "modules": {"child": {"name": "display name", "settings": {"width": 0.5},
            "instances": {"a": {"component": "coupler", "settings": {
                "large": 9007199254740993u64, "enabled": true, "null": null,
                "values": [1, "two"], "expr": "${settings.width}", "width": 0.5
            }, "info": {"source": "layout"}, "array": {"na": 3, "nb": 2}}},
            "ports": {"in": "a[0],in", "out": "a<3.2>,out"},
            "connections": {"a<1.2>,out": "a<2.2>,in"},
            "nets": [[], ["a,in"], ["a,in", "a[2],in", "a<3.2>,out"]],
            "placements": {"a": {"x": "pad,e4"}}, "routes": {"optical": {"radius": 10}},
            "info": {"description": "test"}
        }, "parent": {"instances": {"sub": {"component": "child"}}}},
        "toplevel": "parent"
    }))
    .unwrap()
}

#[test]
fn yaml_json_and_wire_preserve_the_complete_document() {
    let doc = document();
    assert_eq!(
        NetlistDocument::from_yaml(&doc.to_yaml().unwrap()).unwrap(),
        doc
    );
    assert_eq!(
        serde_json::from_str::<NetlistDocument>(&serde_json::to_string(&doc).unwrap()).unwrap(),
        doc
    );
    let bytes = doc.to_proto().unwrap();
    let circuit = proto::Netlist::decode(bytes.as_slice()).unwrap();
    assert_eq!(circuit.top_circuit, "parent");
    assert_eq!(
        circuit.circuits[0].connections[0]
            .source
            .as_ref()
            .unwrap()
            .terminal_name,
        "out"
    );
    assert_eq!(NetlistDocument::from_proto(&bytes).unwrap(), doc);
}

#[test]
fn wire_matches_a_fixed_protobuf_fixture() {
    // Netlist.name = field 1, Netlist.top_circuit = field 3; wire type 2.
    let bytes = b"\x0a\x04demo\x1a\x03top";
    let circuit = proto::Netlist::decode(bytes.as_slice()).unwrap();
    assert_eq!(circuit.name, "demo");
    assert_eq!(circuit.top_circuit, "top");
    assert_eq!(circuit.encode_to_vec(), bytes);
    // TerminalReference uses the original field numbers, including Terminal_name.
    let pin = proto::TerminalReference {
        instance_name: "a".into(),
        terminal_name: "p".into(),
    };
    assert_eq!(pin.encode_to_vec(), b"\x0a\x01a\x12\x01p");
}

#[test]
fn terminal_alias_and_oneof_validation_work_in_rust() {
    let pin: proto::TerminalReference =
        serde_json::from_value(json!({"Terminal_name": "in"})).unwrap();
    assert_eq!(pin.terminal_name, "in");
    let parameter: proto::ParameterValue = serde_json::from_value(json!({"model_ref": {
        "model_interface_name": "model", "arguments": {"x": {"prefixed_value": {"double_value": 2.0}}}
    }})).unwrap();
    assert_eq!(
        proto::ParameterValue::decode(parameter.encode_to_vec().as_slice()).unwrap(),
        parameter
    );
    assert_eq!(
        serde_json::from_value::<proto::ParameterValue>(serde_json::to_value(&parameter).unwrap())
            .unwrap(),
        parameter
    );
    assert!(serde_json::from_value::<proto::ParameterValue>(
        json!({"prefixed_value": {}, "model_ref": {}})
    )
    .is_err());
}

#[test]
fn elaboration_preserves_arrays_connectivity_and_instance_metadata() {
    let doc = document();
    let netlists = doc.to_netlists().unwrap();
    let nl = &netlists["child"];
    assert_eq!(nl.instances["a"].info["source"], "layout");
    assert_eq!(nl.instances["a"].array.as_ref().unwrap().nb, 2);
    assert!(nl
        .nets
        .iter()
        .flat_map(|n| &n.members)
        .any(|m| matches!(m, NetMember::ArrayRef(p) if p.ia == 3 && p.ib == 2)));
    let reverse = NetlistDocument::from_netlists(&netlists, Some("parent".into()));
    assert_eq!(
        reverse.modules["child"].instances["a"].info["source"],
        "layout"
    );
    assert_eq!(reverse.to_netlists().unwrap(), netlists);
}

#[test]
fn bare_yaml_and_array_size_shorthand() {
    let doc = NetlistDocument::from_yaml("instances:\n  a:\n    component: coupler\n    settings: {array_size: 3}\nports: {out: 'a[2],out'}\n").unwrap();
    assert_eq!(doc.toplevel.as_deref(), Some("__root__"));
    let netlists = doc.to_netlists().unwrap();
    assert_eq!(
        netlists["__root__"].instances["a"]
            .array
            .as_ref()
            .unwrap()
            .na,
        3
    );
}

#[test]
fn sample_yaml_elaborates_without_python() {
    let doc = NetlistDocument::from_yaml(include_str!("../../../kfnetlist-schema/schema.pic.yaml"))
        .unwrap();
    assert_eq!(doc.to_netlists().unwrap().len(), 2);
    assert_eq!(
        NetlistDocument::from_proto(&doc.to_proto().unwrap()).unwrap(),
        doc
    );
}

#[test]
fn bad_inputs_report_errors() {
    assert!(NetlistDocument::from_yaml("modules: [").is_err());
    assert!(NetlistDocument::from_proto(b"\xff").is_err());
    let bad: NetlistDocument =
        serde_json::from_value(json!({"modules": {"m": {}}, "toplevel": "absent"})).unwrap();
    assert!(bad.to_netlists().is_err());
    for reference in [
        "a[-1],p",
        "a<0.1>,p",
        "a[999999999999999999999],p",
        "a[3],p",
        "absent,p",
        "a,p,extra",
    ] {
        let doc: NetlistDocument = serde_json::from_value(json!({"instances": {"a": {"component": "x", "array": {"na": 2}}}, "ports": {"out": reference}})).unwrap();
        assert!(doc.to_netlists().is_err(), "accepted {reference}");
    }
    for size in [json!(0), json!(-1), json!(2.5), json!(true), json!("two")] {
        let doc: NetlistDocument = serde_json::from_value(
            json!({"instances": {"a": {"component": "x", "settings": {"array_size": size}}}}),
        )
        .unwrap();
        assert!(doc.to_netlists().is_err());
    }
    let circuit = proto::Netlist {
        circuits: vec![proto::Circuit {
            properties: [("__info__".into(), "invalid json".into())].into(),
            ..Default::default()
        }],
        ..Default::default()
    };
    assert!(NetlistDocument::from_proto_netlist(&circuit).is_err());
}

#[test]
fn unconnected_and_multi_net_pins_are_not_lost() {
    let mut nl = Netlist::default();
    let p = nl.create_port("p".into());
    nl.create_port("q".into());
    let r = nl.create_port("r".into());
    nl.create_net([NetMember::Port(p), NetMember::Port(r)])
        .unwrap();
    let module = CircuitDocument::from_netlist("m".into(), &nl);
    assert_eq!(module.ports.len(), 3);
    assert_eq!(module.to_netlist().unwrap(), nl);
}

fn pin(instance: &str, terminal: &str) -> Option<proto::TerminalReference> {
    Some(proto::TerminalReference {
        instance_name: instance.into(),
        terminal_name: terminal.into(),
    })
}

#[test]
fn morphnet_and_legacy_encodings_decode() {
    let star = |net: &str, inst: &str, port: &str| proto::Connection {
        name: net.into(),
        source: pin("", net),
        target: pin(inst, port),
        ..Default::default()
    };
    // Shape produced by morphnet's SPICE parser for `R1 in_ mid 1k` / `C1 mid 0 1p`.
    let resistor = proto::SubCircuit {
        name: "R1".into(),
        circuit_name: "resistor".into(),
        parameters: vec![proto::Parameter {
            name: "value".into(),
            default_value: serde_json::from_value(
                json!({"prefixed_value": {"double_value": 1.0, "prefix": 15}}),
            )
            .unwrap(),
            ..Default::default()
        }],
        ..Default::default()
    };
    let module = proto::Circuit {
        name: "rc".into(),
        terminals: vec![proto::Terminal {
            name: "in_".into(),
            ..Default::default()
        }],
        subcircuits: vec![resistor],
        connections: vec![
            star("in_", "R1", "p"),
            star("mid", "R1", "n"),
            star("mid", "C1", "p"),
        ],
        ..Default::default()
    };
    let circuit = proto::Netlist {
        top_circuit: "rc".into(),
        circuits: vec![module],
        ..Default::default()
    };
    let rc = &NetlistDocument::from_proto_netlist(&circuit)
        .unwrap()
        .modules["rc"];
    assert_eq!(rc.nets, vec![vec!["in_", "R1,p"], vec!["R1,n", "C1,p"]]);
    assert_eq!(rc.instances["R1"].settings["value"], json!(1000.0));

    // Bytes written before the named-net encoding: port_* connections and __members__ buses.
    let legacy = proto::Circuit {
        name: "old".into(),
        terminals: vec![proto::Terminal {
            name: "o1".into(),
            ..Default::default()
        }],
        connections: vec![proto::Connection {
            name: "port_o1".into(),
            source: pin("", "o1"),
            target: pin("wg", "o1"),
            ..Default::default()
        }],
        buses: vec![proto::Bus {
            name: "net_0".into(),
            properties: [("__members__".into(), r#"["wg,o2","wg2,o1"]"#.into())].into(),
            ..Default::default()
        }],
        properties: [("__placements__".into(), "{}".into())].into(),
        ..Default::default()
    };
    let circuit = proto::Netlist {
        circuits: vec![legacy],
        ..Default::default()
    };
    let old = &NetlistDocument::from_proto_netlist(&circuit)
        .unwrap()
        .modules["old"];
    assert_eq!(old.ports["o1"], "wg,o1");
    assert_eq!(old.nets, vec![vec!["wg,o2", "wg2,o1"]]);
}
