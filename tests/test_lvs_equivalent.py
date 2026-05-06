from __future__ import annotations

from kfnetlist import Net, Netlist, NetlistPort, PortRef


def _make_netlist_with_pads() -> Netlist:
    """Two pads with 4 electrically equivalent ports, connected pairwise."""
    nl = Netlist()
    nl.create_inst("p1", kcl="pdk", component="pad_m1", settings={})
    nl.create_inst("p2", kcl="pdk", component="pad_m1", settings={})
    nl.create_net(
        PortRef(instance="p1", port="e3"),
        PortRef(instance="p2", port="e1"),
    )
    return nl


def test_lvs_equivalent_collapses_to_canonical_port_name() -> None:
    nl = _make_netlist_with_pads()
    out = nl.lvs_equivalent(
        cell_name="top",
        equivalent_ports={"pad_m1": [["e1", "e2", "e3", "e4"]]},
    )
    flat_ports = {
        (p.instance, p.port)
        for net in out.nets
        for p in net.root
        if isinstance(p, PortRef)
    }
    # All pad ports collapse to the canonical first one ("e1")
    assert flat_ports == {("p1", "e1"), ("p2", "e1")}


def test_lvs_equivalent_merges_changed_nets_sharing_canonical_port() -> None:
    nl = Netlist()
    nl.create_inst("pad", kcl="pdk", component="pad_m1", settings={})
    nl.create_inst("a", kcl="pdk", component="other", settings={})
    nl.create_inst("b", kcl="pdk", component="other", settings={})

    nl.create_net(
        PortRef(instance="pad", port="e1"),
        PortRef(instance="a", port="o1"),
    )
    nl.create_net(
        PortRef(instance="pad", port="e2"),
        PortRef(instance="b", port="o1"),
    )

    out = nl.lvs_equivalent(
        cell_name="top",
        equivalent_ports={"pad_m1": [["e1", "e2", "e3", "e4"]]},
    )

    # The two nets that touched the pad on different equivalent ports must merge
    pad_nets = [
        net
        for net in out.nets
        if any(
            isinstance(p, PortRef) and p.instance == "pad" for p in net.root
        )
    ]
    assert len(pad_nets) == 1
    refs = {(p.instance, p.port) for p in pad_nets[0].root if isinstance(p, PortRef)}
    assert ("a", "o1") in refs
    assert ("b", "o1") in refs
    assert ("pad", "e1") in refs


def test_lvs_equivalent_returns_new_netlist() -> None:
    nl = _make_netlist_with_pads()
    before = nl.model_dump_json()
    nl.lvs_equivalent(
        cell_name="top",
        equivalent_ports={"pad_m1": [["e1", "e2", "e3", "e4"]]},
    )
    # Original must not mutate
    assert nl.model_dump_json() == before


def test_lvs_equivalent_with_top_level_port_remap() -> None:
    nl = Netlist()
    nl.create_inst("pad", kcl="pdk", component="pad_m1", settings={})
    nl.create_port("e2")
    nl.create_port("e1")
    nl.create_net(
        NetlistPort(name="e2"),
        PortRef(instance="pad", port="e2"),
    )
    nl.create_net(
        NetlistPort(name="e1"),
        PortRef(instance="pad", port="e1"),
    )

    out = nl.lvs_equivalent(
        cell_name="top",
        equivalent_ports={
            "pad_m1": [["e1", "e2", "e3", "e4"]],
            "top": [["e1", "e2"]],
        },
    )
    # the two nets collapse; top-level port remap routes both NetlistPort
    # references to "e1"
    netlist_port_names = {
        p.name
        for net in out.nets
        for p in net.root
        if isinstance(p, NetlistPort)
    }
    assert netlist_port_names == {"e1"}


def test_lvs_equivalent_no_change_when_component_not_in_map() -> None:
    nl = Netlist()
    nl.create_inst("a", kcl="pdk", component="other", settings={})
    nl.create_inst("b", kcl="pdk", component="other", settings={})
    nl.create_net(
        PortRef(instance="a", port="o1"),
        PortRef(instance="b", port="o1"),
    )
    out = nl.lvs_equivalent(
        cell_name="top",
        equivalent_ports={"pad_m1": [["e1", "e2"]]},
    )
    # No remapping happens
    assert {
        (p.instance, p.port)
        for net in out.nets
        for p in net.root
        if isinstance(p, PortRef)
    } == {("a", "o1"), ("b", "o1")}


def test_lvs_equivalent_eq_via_round_trip() -> None:
    """Two semantically identical netlists, one before remap and one canonical,
    must compare equal after `lvs_equivalent`."""
    nl = _make_netlist_with_pads()
    out = nl.lvs_equivalent(
        cell_name="top",
        equivalent_ports={"pad_m1": [["e1", "e2", "e3", "e4"]]},
    )

    expected = Netlist()
    expected.create_inst("p1", kcl="pdk", component="pad_m1", settings={})
    expected.create_inst("p2", kcl="pdk", component="pad_m1", settings={})
    expected.create_net(
        PortRef(instance="p1", port="e1"),
        PortRef(instance="p2", port="e1"),
    )
    expected.sort()

    assert out == expected
