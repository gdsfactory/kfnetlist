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
    assert!(serde_json::from_value::<proto::ParameterValue>(
        json!({"prefixed_value": {}, "expression": {"node": {"raw": "x"}}})
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

#[test]
fn bus_terminals_and_bracketed_instance_names_decode() {
    // Shape produced by morphnet's SystemVerilog parser for
    // `module top (input [1:0] in); leaf I[1:0] (.a(in)); endmodule`.
    let star = |net: &str, inst: &str| proto::Connection {
        name: net.into(),
        source: pin("", net),
        target: pin(inst, "a"),
        ..Default::default()
    };
    let leaf = |name: &str| proto::SubCircuit {
        name: name.into(),
        circuit_name: "leaf".into(),
        ..Default::default()
    };
    let module = proto::Circuit {
        name: "top".into(),
        terminals: vec![proto::Terminal {
            name: "in".into(),
            width: 2,
            properties: [("range".into(), "1:0".into())].into(),
            ..Default::default()
        }],
        subcircuits: vec![leaf("I[1]"), leaf("I[0]")],
        connections: vec![star("in[1]", "I[1]"), star("in[0]", "I[0]")],
        ..Default::default()
    };
    let circuit = proto::Netlist {
        top_circuit: "top".into(),
        circuits: vec![module],
        ..Default::default()
    };
    let doc = NetlistDocument::from_proto_netlist(&circuit).unwrap();
    let top = &doc.modules["top"];
    assert_eq!(
        top.nets,
        vec![vec!["in[1]", "I[1],a"], vec!["in[0]", "I[0],a"]]
    );
    let nl = top.to_netlist().unwrap();
    let ports: Vec<_> = nl.ports.iter().map(|p| p.name.as_str()).collect();
    assert_eq!(ports, ["in[1]", "in[0]"]);
    assert_eq!(nl.nets.len(), 2);
}

/// proto -> document -> kfnetlist Netlists -> document -> proto, as morphnet's bridge does.
fn through_netlists(netlist: &proto::Netlist) -> proto::Netlist {
    let netlists = NetlistDocument::from_proto_netlist(netlist)
        .unwrap()
        .to_netlists()
        .unwrap();
    NetlistDocument::from_netlists(&netlists, None)
        .to_proto_netlist()
        .unwrap()
}

#[test]
fn morphnet_only_fields_survive_kfnetlist() {
    let kilo = serde_json::from_value::<Option<proto::ParameterValue>>(
        json!({"prefixed_value": {"double_value": 1.0, "prefix": 15}}),
    )
    .unwrap();
    let directive = |kind: proto::DirectiveKind, value: &str| proto::Directive {
        kind: kind as i32,
        name: String::new(),
        value: value.into(),
    };
    let sub = proto::SubCircuit {
        name: "R1".into(),
        circuit_name: "rmodel".into(),
        parameters: vec![
            proto::Parameter {
                name: "r".into(),
                default_value: kilo.clone(),
                ..Default::default()
            },
            proto::Parameter {
                name: "w".into(),
                default_value: serde_json::from_value(json!({"expression": {"node": {
                    "binary": {"op": proto::Operator::Mul as i32,
                        "lhs": {"node": {"literal": {"double_value": 2.0}}},
                        "rhs": {"node": {"reference": "l"}}}
                }}}))
                .unwrap(),
                ..Default::default()
            },
        ],
        properties: [
            ("model_name".into(), "rpoly".into()),
            ("__info__".into(), r#"{"gsch":1}"#.into()),
        ]
        .into(),
        ..Default::default()
    };
    let star = |net: &str, inst: &str, port: &str| proto::Connection {
        name: net.into(),
        source: pin("", net),
        target: pin(inst, port),
        domain: proto::SignalDomain::Electrical as i32,
        ..Default::default()
    };
    let circuit = proto::Circuit {
        name: "top".into(),
        terminals: vec![proto::Terminal {
            name: "a".into(),
            direction: proto::TerminalDirection::Input as i32,
            domain: proto::SignalDomain::Electrical as i32,
            discipline: "electrical".into(),
            ..Default::default()
        }],
        parameters: vec![proto::Parameter {
            name: "l".into(),
            default_value: kilo,
            ..Default::default()
        }],
        subcircuits: vec![sub.clone()],
        connections: vec![star("a", "R1", "p"), star("mid", "R1", "n")],
        properties: [("analog_block".into(), "analog begin end".into())].into(),
        directives: vec![directive(proto::DirectiveKind::Include, "top.inc")],
        ..Default::default()
    };
    let netlist = proto::Netlist {
        name: "doc".into(),
        top_circuit: "top".into(),
        circuits: vec![circuit.clone()],
        ext_circuits: vec![proto::ExternalCircuit {
            name: "rmodel".into(),
            properties: [("spice_prefix".into(), "R".into())].into(),
            ..Default::default()
        }],
        properties: [("dialect".into(), "spectre".into())].into(),
        directives: vec![directive(proto::DirectiveKind::Lib, "corners.lib")],
        ..Default::default()
    };

    let doc = NetlistDocument::from_proto_netlist(&netlist).unwrap();
    let top = &doc.modules["top"];
    assert_eq!(top.instances["R1"].settings["w"], json!("2 * l"));
    assert_eq!(top.instances["R1"].info["gsch"], json!(1));
    assert_eq!(
        top.instances["R1"].info["__morphnet__"]["properties"],
        json!({"model_name": "rpoly"})
    );
    assert_eq!(top.net_names, ["a", "mid"]);
    let nl = top.to_netlist().unwrap();
    assert_eq!(
        nl.directives
            .iter()
            .map(|d| d.kind.as_str())
            .collect::<Vec<_>>(),
        ["lib", "include"]
    );
    let names: Vec<_> = nl.nets.iter().map(|n| n.name.as_deref()).collect();
    assert_eq!(names, [Some("a"), Some("mid")]);

    let back = through_netlists(&netlist);
    assert_eq!(back.name, "doc");
    assert_eq!(back.top_circuit, "top");
    assert_eq!(back.ext_circuits, netlist.ext_circuits);
    assert_eq!(back.properties, netlist.properties);
    assert_eq!(
        back.directives,
        [netlist.directives.clone(), circuit.directives.clone()].concat()
    );
    let c = &back.circuits[0];
    assert!(c.directives.is_empty());
    assert_eq!(c.terminals, circuit.terminals);
    assert_eq!(c.parameters, circuit.parameters);
    assert_eq!(c.properties["analog_block"], "analog begin end");
    assert_eq!(c.subcircuits[0].parameters, sub.parameters);
    assert_eq!(c.subcircuits[0].properties["model_name"], "rpoly");
    assert_eq!(c.subcircuits[0].properties["__info__"], r#"{"gsch":1}"#);
    let nets: Vec<_> = c
        .connections
        .iter()
        .map(|c| (c.name.as_str(), c.domain))
        .collect();
    assert_eq!(nets, [("a", 1), ("mid", 1)]);
    // A second trip is stable.
    assert_eq!(through_netlists(&back), back);

    // An edited expression setting comes back as raw text.
    let mut netlists = NetlistDocument::from_proto_netlist(&netlist)
        .unwrap()
        .to_netlists()
        .unwrap();
    let r1 = netlists.get_mut("top").unwrap().instances.get_mut("R1").unwrap();
    r1.settings["w"] = json!("3*l");
    let edited = NetlistDocument::from_netlists(&netlists, None)
        .to_proto_netlist()
        .unwrap();
    let w = &edited.circuits[0].subcircuits[0].parameters[1];
    assert_eq!(w.name, "w");
    assert_eq!(
        serde_json::to_value(&w.default_value).unwrap(),
        json!({"expression": {"node": {"raw": "3*l"}}})
    );
}

#[test]
fn kfnetlist_round_trip_adds_no_morphnet_metadata() {
    let mut nl = Netlist::default();
    nl.create_inst(
        "X1".into(),
        String::new(),
        "cell".into(),
        json!({"w": "2*l", "on": true, "n": 2}),
        0,
        0,
    )
    .unwrap();
    nl.create_named_net(
        [NetMember::Ref(kfnetlist_core::PortRef {
            instance: "X1".into(),
            port: "p".into(),
        })],
        "mid",
    )
    .unwrap();
    let doc = NetlistDocument::from_netlists(&[("top".to_string(), nl.clone())].into(), None);
    let back = NetlistDocument::from_proto(&doc.to_proto().unwrap())
        .unwrap()
        .to_netlists()
        .unwrap();
    let back = &back["top"];
    assert!(back.info.is_empty());
    assert!(back.instances["X1"].info.is_empty());
    assert_eq!(back.instances["X1"].settings, nl.instances["X1"].settings);
    assert_eq!(back.nets[0].name.as_deref(), Some("mid"));
}

#[test]
fn every_module_carries_the_document_header() {
    let ext = |name: &str, model: &str| proto::ExternalCircuit {
        name: name.into(),
        properties: [("model_type".into(), model.into())].into(),
        ..Default::default()
    };
    let doc = |circuit: &str, exts: Vec<proto::ExternalCircuit>| {
        let netlist = proto::Netlist {
            name: "doc".into(),
            top_circuit: circuit.into(),
            circuits: vec![
                proto::Circuit {
                    name: format!("{circuit}_child"),
                    ..Default::default()
                },
                proto::Circuit {
                    name: circuit.into(),
                    ..Default::default()
                },
            ],
            ext_circuits: exts,
            properties: [("ground_net".into(), "GND".into())].into(),
            ..Default::default()
        };
        let netlists = NetlistDocument::from_proto_netlist(&netlist)
            .unwrap()
            .to_netlists()
            .unwrap();
        (netlist, netlists)
    };
    let (source, netlists) = doc("top", vec![ext("nch", "nmos"), ext("pch", "pmos")]);
    let header =
        |p: &proto::Netlist| (p.name.clone(), p.ext_circuits.clone(), p.properties.clone());

    // a non-lead toplevel
    let back = NetlistDocument::from_netlists(&netlists, Some("top_child".into()))
        .to_proto_netlist()
        .unwrap();
    assert_eq!(header(&back), header(&source));
    assert_eq!(back.top_circuit, "top_child");

    // a single cell without the toplevel: the stale top reference is dropped
    let child = [("top_child".to_string(), netlists["top_child"].clone())].into();
    let back = NetlistDocument::from_netlists(&child, None)
        .to_proto_netlist()
        .unwrap();
    assert_eq!(header(&back), header(&source));
    assert_eq!(back.top_circuit, "");

    // cells of two documents: the lead's header, then the others' ext circuits by name
    let (_, other) = doc("other", vec![ext("nch", "other"), ext("res", "r")]);
    let mut both = netlists.clone();
    both.extend(other);
    let back = NetlistDocument::from_netlists(&both, Some("other".into()))
        .to_proto_netlist()
        .unwrap();
    let names: Vec<_> = back
        .ext_circuits
        .iter()
        .map(|e| (e.name.as_str(), e.properties["model_type"].as_str()))
        .collect();
    assert_eq!(names, [("nch", "other"), ("res", "r"), ("pch", "pmos")]);
}

#[test]
fn only_an_unnamed_port_net_uses_the_port_form() {
    let mut nl = Netlist::default();
    nl.create_port("o1".into());
    nl.create_inst(
        "mmi".into(),
        String::new(),
        "mmi1x2".into(),
        json!({}),
        0,
        0,
    )
    .unwrap();
    let members = || {
        [
            NetMember::Port(kfnetlist_core::NetlistPort { name: "o1".into() }),
            NetMember::Ref(kfnetlist_core::PortRef {
                instance: "mmi".into(),
                port: "o1".into(),
            }),
        ]
    };
    let mut named = nl.clone();
    named.create_named_net(members(), "o1").unwrap();
    nl.create_net(members()).unwrap();
    let plain = CircuitDocument::from_netlist("top".into(), &nl);
    assert_eq!(plain.ports["o1"], "mmi,o1");
    let named = CircuitDocument::from_netlist("top".into(), &named);
    assert_eq!(named.ports["o1"], "o1");
    assert_eq!(named.net_name(0), Some("o1"));
}

#[test]
fn a_non_object_morphnet_stash_is_an_error() {
    let doc: NetlistDocument = serde_json::from_value(json!({
        "modules": {"top": {"info": {"__morphnet__": "garbage"}}}
    }))
    .unwrap();
    let err = doc.to_proto().unwrap_err();
    assert_eq!(err.to_string(), "info['__morphnet__'] must be an object");
}

#[test]
fn buses_and_foreign_dunder_properties_survive_kfnetlist() {
    let props = |pairs: &[(&str, &str)]| -> std::collections::BTreeMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    };
    let reference = |instance: &str, terminal: &str| {
        Some(proto::TerminalReference {
            instance_name: instance.into(),
            terminal_name: terminal.into(),
        })
    };
    let bus = proto::Bus {
        name: "data".into(),
        width: 2,
        domain: proto::SignalDomain::Electrical as i32,
        connections: vec![proto::Connection {
            name: "d0".into(),
            source: reference("R1", "p"),
            target: reference("R1", "q"),
            ..Default::default()
        }],
        properties: props(&[("protocol", "spi"), ("__bus_x", "1")]),
    };
    let sub = proto::SubCircuit {
        name: "R1".into(),
        circuit_name: "r".into(),
        properties: props(&[("__sub_x", "\"a\"")]),
        ..Default::default()
    };
    let conn = proto::Connection {
        name: "mid".into(),
        source: Some(proto::TerminalReference {
            terminal_name: "mid".into(),
            ..Default::default()
        }),
        target: reference("R1", "n"),
        properties: props(&[("__conn_x", "2")]),
        ..Default::default()
    };
    let circuit = proto::Circuit {
        name: "top".into(),
        subcircuits: vec![sub],
        connections: vec![conn],
        buses: vec![bus],
        properties: props(&[("__circuit_x", "3")]),
        ..Default::default()
    };
    let netlist = proto::Netlist {
        name: "doc".into(),
        top_circuit: "top".into(),
        circuits: vec![circuit],
        ..Default::default()
    };
    let back = through_netlists(&netlist);
    let (a, b) = (&netlist.circuits[0], &back.circuits[0]);
    assert_eq!(b.buses, a.buses);
    assert_eq!(b.subcircuits[0].properties["__sub_x"], "\"a\"");
    assert_eq!(b.properties["__circuit_x"], "3");
    assert_eq!(b.connections[0].properties["__conn_x"], "2");
    assert_eq!(b.connections.len(), a.connections.len());
    // The bus members stay a plain net of the kfnetlist side.
    let nl = NetlistDocument::from_proto_netlist(&netlist)
        .unwrap()
        .to_netlists()
        .unwrap();
    assert_eq!(nl["top"].nets.len(), 2);
    // A second trip is stable.
    assert_eq!(through_netlists(&back), back);
}

fn endpoint(instance: &str, terminal: &str) -> Option<proto::TerminalReference> {
    Some(proto::TerminalReference {
        instance_name: instance.into(),
        terminal_name: terminal.into(),
    })
}

/// A circuit of instances `names` (each of master `x`) around `connections` and `buses`.
fn circuit_of(
    names: &[&str],
    connections: Vec<proto::Connection>,
    buses: Vec<proto::Bus>,
) -> proto::Netlist {
    proto::Netlist {
        name: "doc".into(),
        top_circuit: "top".into(),
        circuits: vec![proto::Circuit {
            name: "top".into(),
            subcircuits: names
                .iter()
                .map(|n| proto::SubCircuit {
                    name: (*n).into(),
                    circuit_name: "x".into(),
                    ..Default::default()
                })
                .collect(),
            connections,
            buses,
            ..Default::default()
        }],
        ..Default::default()
    }
}
fn link(
    name: &str,
    source: (&str, &str),
    target: (&str, &str),
    extra: &[(&str, &str)],
) -> proto::Connection {
    proto::Connection {
        name: name.into(),
        source: endpoint(source.0, source.1),
        target: endpoint(target.0, target.1),
        properties: extra
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect(),
        ..Default::default()
    }
}

#[test]
fn a_bus_with_out_of_order_pins_is_restored() {
    // A `Netlist` sorts net members: `Z,p` then `A,n` comes back as `A,n`, `Z,p`.
    let bus = proto::Bus {
        name: "data".into(),
        connections: vec![link("d0", ("Z", "p"), ("A", "n"), &[])],
        ..Default::default()
    };
    let back = through_netlists(&circuit_of(&["Z", "A"], vec![], vec![bus.clone()]));
    assert_eq!(back.circuits[0].buses, [bus]);
    assert!(back.circuits[0].connections.is_empty());
}

#[test]
fn foreign_properties_stay_on_their_own_connection() {
    // An unnamed connection, and one net whose two connections differ.
    let back = through_netlists(&circuit_of(
        &["A", "B", "C"],
        vec![
            link("", ("A", "o3"), ("B", "o3"), &[("__x", "u")]),
            link("m", ("A", "o2"), ("B", "o2"), &[("__x", "1")]),
            link("m", ("A", "o2"), ("C", "o2"), &[]),
        ],
        vec![],
    ));
    // (terminal, other instance) -> the `__x` it carries.
    let x = |terminal: &str, other: &str| {
        back.circuits[0]
            .connections
            .iter()
            .find(|c| {
                let ends: Vec<_> = [&c.source, &c.target]
                    .into_iter()
                    .flatten()
                    .map(|t| (t.instance_name.as_str(), t.terminal_name.as_str()))
                    .collect();
                ends.contains(&(other, terminal))
            })
            .unwrap_or_else(|| panic!("no connection to {other},{terminal}"))
            .properties
            .get("__x")
            .cloned()
    };
    assert_eq!(x("o3", "B").as_deref(), Some("u"));
    assert_eq!(x("o2", "B").as_deref(), Some("1"));
    assert_eq!(x("o2", "C"), None);
}

#[test]
fn a_bus_sharing_a_circuit_connection_keeps_both() {
    // The shape of tests/morphnet/conftest.py: the bus carries a circuit connection.
    let shared = link("n1", ("A", "o1"), ("B", "o1"), &[]);
    let bus = proto::Bus {
        name: "data_bus".into(),
        width: 4,
        connections: vec![shared.clone()],
        ..Default::default()
    };
    let back = through_netlists(&circuit_of(&["A", "B"], vec![shared], vec![bus.clone()]));
    assert_eq!(back.circuits[0].buses, [bus]);
    assert_eq!(back.circuits[0].connections.len(), 1);
    assert_eq!(back.circuits[0].connections[0].name, "n1");
}
