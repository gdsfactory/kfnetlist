use kfnetlist_core::{to_json, NetMember, Netlist, PortRef};
use serde_json::json;

fn main() -> kfnetlist_core::Result<()> {
    let mut netlist = Netlist::default();
    netlist.create_inst(
        "wg1".into(),
        "PDK".into(),
        "straight".into(),
        json!({"width": 0.5}),
        1,
        1,
    )?;
    let input = netlist.create_port("in".into());
    netlist.create_net([
        NetMember::Port(input),
        NetMember::Ref(PortRef {
            instance: "wg1".into(),
            port: "o1".into(),
        }),
    ])?;
    assert!(netlist.detect_opens().unconnected_ports.is_empty());
    println!("{}", to_json(&netlist)?);
    Ok(())
}
