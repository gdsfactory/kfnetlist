"""
Bidirectional conversion between the YAML-level schema models and the
Rust-native Netlist/Net/NetlistInstance types.

Forward  (YAML → Netlist):  top_level_module_to_netlists / module_to_netlist
Reverse  (Netlist → YAML):  netlists_to_top_level_module / netlist_to_module

Also provides proto-level conversions:
  top_level_module_to_proto_circuit  (TopLevelModule → ProtoCircuit)
  proto_circuit_to_top_level_module  (ProtoCircuit  → TopLevelModule)

And a PIC YAML file loader:
  load_pic_yaml  (path → TopLevelModule)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from kfnetlist._native import (
    Netlist,
    NetlistPort,
    PortArrayRef,
    PortRef,
)

from .models import (
    ArraySpec,
    Bus,
    Connection,
    Instance,
    Module,
    ModelReference,
    Parameter,
    ParameterValue,
    PrefixedValue,
    ProtoCircuit,
    ProtoModule,
    ProtoModuleReference,
    Terminal,
    TerminalReference,
    TopLevelModule,
    _PROP_ARRAY,
    _PROP_INFO,
    _PROP_PLACEMENTS,
    _PROP_ROUTES,
)

# ---------------------------------------------------------------------------
# Port-reference parsing
# ---------------------------------------------------------------------------

# Matches "inst_name,port_name" or "inst_name, port_name"
_REF_RE = re.compile(r"^(.+?)\s*,\s*(.+)$")
# Matches "inst_name<ia.ib>,port_name"
_ARRAY_REF_RE = re.compile(r"^(.+?)<(\d+)\.(\d+)>\s*,\s*(.+)$")
# Matches "inst_name[n],port_name" (bracket-index syntax from schema.pic.yaml)
_BRACKET_REF_RE = re.compile(r"^(.+?)\[(\d+)\]\s*,\s*(.+)$")


def _parse_port_ref(ref: str) -> PortRef | PortArrayRef | NetlistPort:
    """Parse "inst,port", "inst<ia.ib>,port", "inst[n],port", or bare port name."""
    m = _ARRAY_REF_RE.match(ref)
    if m:
        inst, ia, ib, port = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        return PortArrayRef(inst, port, ia, ib)
    m = _BRACKET_REF_RE.match(ref)
    if m:
        # inst[n],port → PortArrayRef(inst, port, n+1, 1) — 1-indexed to match NetlistArray
        inst, n, port = m.group(1), int(m.group(2)) + 1, m.group(3)
        return PortArrayRef(inst, port, n, 1)
    m = _REF_RE.match(ref)
    if m:
        return PortRef(m.group(1), m.group(2))
    return NetlistPort(ref)


def _unparse_port_ref(member: PortRef | PortArrayRef | NetlistPort) -> str:
    """Serialise a net member back to its string form."""
    if isinstance(member, PortArrayRef):
        return f"{member.instance}<{member.ia}.{member.ib}>,{member.port}"
    if isinstance(member, PortRef):
        return f"{member.instance},{member.port}"
    return member.name  # NetlistPort


# ---------------------------------------------------------------------------
# Forward: TopLevelModule → dict[str, Netlist]
# ---------------------------------------------------------------------------


def top_level_module_to_netlists(doc: TopLevelModule) -> dict[str, Netlist]:
    """
    Elaborate every Module in *doc* into a Rust Netlist.
    Returns {module_name: Netlist}.
    """
    return {name: module_to_netlist(mod) for name, mod in doc.modules.items()}


def module_to_netlist(mod: Module) -> Netlist:
    """Convert a single YAML-level Module into a Rust Netlist."""
    nl = Netlist()

    # Ports
    for port_name in mod.ports:
        nl.create_port(port_name)

    # Instances
    for inst_name, inst in mod.instances.items():
        array = inst.array
        # Support array_size in settings as a shorthand for a 1D array
        if array is None and "array_size" in inst.settings:
            array = ArraySpec(na=int(inst.settings["array_size"]), nb=1)
        na = array.na if array else 1
        nb = array.nb if array else 1
        nl.create_inst(
            name=inst_name,
            kcl="",
            component=inst.component,
            settings=inst.settings if inst.settings else None,
            na=na,
            nb=nb,
        )

    # Explicit snap connections (single-pair nets)
    for src_ref, tgt_ref in mod.connections.items():
        src = _parse_port_ref(src_ref)
        tgt = _parse_port_ref(tgt_ref)
        nl.create_net(src, tgt)

    # Logical nets (multi-member)
    for net_members in mod.nets:
        members = [_parse_port_ref(r) for r in net_members]
        nl.create_net(*members)

    # Port exposures: "port_name": "inst,port" → net tying top-level port to instance port
    for port_name, ref_str in mod.ports.items():
        src = _parse_port_ref(ref_str)
        nl.create_net(NetlistPort(port_name), src)

    return nl


# ---------------------------------------------------------------------------
# Reverse: dict[str, Netlist] → TopLevelModule
# ---------------------------------------------------------------------------


def netlists_to_top_level_module(
    netlists: dict[str, Netlist],
    toplevel: str | None = None,
) -> TopLevelModule:
    """
    Convert a dict of {module_name: Netlist} back into a TopLevelModule.
    Net members are serialized to "inst,port" / "inst<ia.ib>,port" strings.
    """
    modules = {name: netlist_to_module(name, nl) for name, nl in netlists.items()}
    return TopLevelModule(modules=modules, toplevel=toplevel)


def netlist_to_module(name: str, nl: Netlist) -> Module:
    """Convert a single Rust Netlist back into a YAML-level Module."""
    from kfnetlist._native import NetlistPort

    instances: dict[str, Instance] = {}
    for inst_name, inst in nl.instances.items():
        array = inst.array
        instances[inst_name] = Instance(
            component=inst.component,
            settings=inst.settings if inst.settings else {},
            array=ArraySpec(na=array.na, nb=array.nb) if array else None,
        )

    # Recover ports: find nets that pair a NetlistPort with exactly one other member
    ports: dict[str, str] = {}
    nets: list[list[str]] = []
    for net in nl.nets:
        members = list(net)
        port_members = [m for m in members if isinstance(m, NetlistPort)]
        other_members = [m for m in members if not isinstance(m, NetlistPort)]
        if len(port_members) == 1 and len(other_members) == 1:
            ports[port_members[0].name] = _unparse_port_ref(other_members[0])
        else:
            nets.append([_unparse_port_ref(m) for m in members])

    return Module(
        name=name,
        instances=instances,
        ports=ports,
        nets=nets,
    )


# ---------------------------------------------------------------------------
# Proto-level conversions: TopLevelModule ↔ ProtoCircuit
# ---------------------------------------------------------------------------


def _settings_to_parameters(settings: dict[str, Any]) -> list[Parameter]:
    """Encode a free-form settings dict as a list of Parameter messages."""
    params: list[Parameter] = []
    for i, (key, value) in enumerate(settings.items()):
        if isinstance(value, (int, float)):
            pv = ParameterValue(prefixed_value=PrefixedValue(double_value=float(value)))
        else:
            pv = ParameterValue(
                model_ref=ModelReference(
                    model_interface_name="__json__",
                    arguments={
                        "value": ParameterValue(
                            prefixed_value=PrefixedValue(double_value=0.0)
                        )
                    },
                )
            )
            _ = pv  # placeholder; store as property instead (see below)
            pv = None
        params.append(
            Parameter(
                uid=i,
                name=key,
                default_value=pv,
                properties={"__json_value__": json.dumps(value)},
            )
        )
    return params


def _parameters_to_settings(params: list[Parameter]) -> dict[str, Any]:
    """Recover a settings dict from a list of Parameter messages."""
    settings: dict[str, Any] = {}
    for p in params:
        if "__json_value__" in p.properties:
            settings[p.name] = json.loads(p.properties["__json_value__"])
        elif p.default_value and p.default_value.prefixed_value:
            v = p.default_value.prefixed_value.double_value
            settings[p.name] = int(v) if v == int(v) else v
    return settings


def _instance_to_proto_ref(inst_name: str, inst: Instance) -> ProtoModuleReference:
    props: dict[str, str] = {}
    if inst.array:
        props[_PROP_ARRAY] = inst.array.model_dump_json()
    if inst.info:
        props[_PROP_INFO] = json.dumps(inst.info)
    # settings → parameter_overrides (encode each value as a ParameterValue)
    param_overrides: dict[str, ParameterValue] = {}
    for key, value in inst.settings.items():
        if isinstance(value, (int, float)):
            param_overrides[key] = ParameterValue(
                prefixed_value=PrefixedValue(double_value=float(value))
            )
        else:
            # Non-numeric: store in properties
            props[f"__setting__{key}"] = json.dumps(value)
    return ProtoModuleReference(
        name=inst_name,
        module_name=inst.component,
        parameter_overrides=param_overrides,
        properties=props,
    )


def _proto_ref_to_instance(ref: ProtoModuleReference) -> tuple[str, Instance]:
    props = ref.properties
    array: ArraySpec | None = None
    if _PROP_ARRAY in props:
        array = ArraySpec.model_validate_json(props[_PROP_ARRAY])
    info: dict[str, Any] = json.loads(props[_PROP_INFO]) if _PROP_INFO in props else {}
    # Recover settings
    settings: dict[str, Any] = {}
    for key, pv in ref.parameter_overrides.items():
        if pv.prefixed_value:
            v = pv.prefixed_value.double_value
            settings[key] = int(v) if v == int(v) else v
    for prop_key, prop_val in props.items():
        if prop_key.startswith("__setting__"):
            setting_key = prop_key[len("__setting__") :]
            settings[setting_key] = json.loads(prop_val)
    return ref.name, Instance(
        component=ref.module_name, settings=settings, array=array, info=info
    )


def _module_to_proto_module(mod_name: str, mod: Module) -> ProtoModule:
    props: dict[str, str] = {}
    if mod.placements:
        props[_PROP_PLACEMENTS] = json.dumps(mod.placements)
    if mod.routes:
        props[_PROP_ROUTES] = json.dumps(mod.routes)
    if mod.info:
        props[_PROP_INFO] = json.dumps(mod.info)

    parameters = _settings_to_parameters(mod.settings)
    module_refs = [_instance_to_proto_ref(n, i) for n, i in mod.instances.items()]

    # Ports → Terminals
    terminals = [
        Terminal(name=port_name, uid=i) for i, port_name in enumerate(mod.ports)
    ]

    # Snap connections
    connections: list[Connection] = []
    for i, (src_str, tgt_str) in enumerate(mod.connections.items()):
        src_m = _REF_RE.match(src_str)
        tgt_m = _REF_RE.match(tgt_str)
        src = TerminalReference(
            instance_name=src_m.group(1) if src_m else "",
            terminal_name=src_m.group(2) if src_m else src_str,
        )
        tgt = TerminalReference(
            instance_name=tgt_m.group(1) if tgt_m else "",
            terminal_name=tgt_m.group(2) if tgt_m else tgt_str,
        )
        connections.append(Connection(name=f"conn_{i}", source=src, target=tgt))

    # Logical nets → Buses
    buses: list[Bus] = []
    for i, net_members in enumerate(mod.nets):
        bus_conns: list[Connection] = []
        for j in range(len(net_members) - 1):
            src_str = net_members[j]
            tgt_str = net_members[j + 1]
            src_m = _REF_RE.match(src_str)
            tgt_m = _REF_RE.match(tgt_str)
            src = TerminalReference(
                instance_name=src_m.group(1) if src_m else "",
                terminal_name=src_m.group(2) if src_m else src_str,
            )
            tgt = TerminalReference(
                instance_name=tgt_m.group(1) if tgt_m else "",
                terminal_name=tgt_m.group(2) if tgt_m else tgt_str,
            )
            bus_conns.append(Connection(name=f"net{i}_c{j}", source=src, target=tgt))
        buses.append(Bus(name=f"net_{i}", connections=bus_conns))

    # Port exposures → additional connections
    for port_name, ref_str in mod.ports.items():
        ref_m = _REF_RE.match(ref_str)
        src = TerminalReference(instance_name="", terminal_name=port_name)
        tgt = TerminalReference(
            instance_name=ref_m.group(1) if ref_m else "",
            terminal_name=ref_m.group(2) if ref_m else ref_str,
        )
        connections.append(Connection(name=f"port_{port_name}", source=src, target=tgt))

    return ProtoModule(
        name=mod_name,
        parameters=parameters,
        module_references=module_refs,
        terminal=terminals,
        connections=connections,
        buses=buses,
        properties=props,
    )


def _proto_module_to_module(pm: ProtoModule) -> tuple[str, Module]:
    props = pm.properties
    placements: dict[str, Any] = (
        json.loads(props[_PROP_PLACEMENTS]) if _PROP_PLACEMENTS in props else {}
    )
    routes: dict[str, Any] = (
        json.loads(props[_PROP_ROUTES]) if _PROP_ROUTES in props else {}
    )
    info: dict[str, Any] = json.loads(props[_PROP_INFO]) if _PROP_INFO in props else {}
    settings = _parameters_to_settings(pm.parameters)

    instances: dict[str, Instance] = {}
    for ref in pm.module_references:
        inst_name, inst = _proto_ref_to_instance(ref)
        instances[inst_name] = inst

    # Recover ports from terminal list + port connections
    port_connections = {c.name: c for c in pm.connections if c.name.startswith("port_")}
    ports: dict[str, str] = {}
    for c in port_connections.values():
        if c.source and c.target:
            port_name = c.source.terminal_name
            inst = c.target.instance_name
            term = c.target.terminal_name
            ports[port_name] = f"{inst},{term}" if inst else term

    snap_connections: dict[str, str] = {}
    for c in pm.connections:
        if c.name.startswith("conn_") and c.source and c.target:
            src_str = (
                f"{c.source.instance_name},{c.source.terminal_name}"
                if c.source.instance_name
                else c.source.terminal_name
            )
            tgt_str = (
                f"{c.target.instance_name},{c.target.terminal_name}"
                if c.target.instance_name
                else c.target.terminal_name
            )
            snap_connections[src_str] = tgt_str

    nets: list[list[str]] = []
    for bus in pm.buses:
        if not bus.connections:
            continue
        members: list[str] = []
        for c in bus.connections:
            if c.source:
                s = (
                    f"{c.source.instance_name},{c.source.terminal_name}"
                    if c.source.instance_name
                    else c.source.terminal_name
                )
                if not members or members[-1] != s:
                    members.append(s)
            if c.target:
                t = (
                    f"{c.target.instance_name},{c.target.terminal_name}"
                    if c.target.instance_name
                    else c.target.terminal_name
                )
                if not members or members[-1] != t:
                    members.append(t)
        if members:
            nets.append(members)

    return pm.name, Module(
        name=pm.name,
        settings=settings,
        info=info,
        instances=instances,
        placements=placements,
        ports=ports,
        connections=snap_connections,
        nets=nets,
        routes=routes,
    )


def top_level_module_to_proto_circuit(doc: TopLevelModule) -> ProtoCircuit:
    """Convert a TopLevelModule document into a ProtoCircuit."""
    proto_modules = [
        _module_to_proto_module(name, mod) for name, mod in doc.modules.items()
    ]
    return ProtoCircuit(
        name=doc.toplevel or "",
        top_module=doc.toplevel or "",
        modules=proto_modules,
    )


def proto_circuit_to_top_level_module(circuit: ProtoCircuit) -> TopLevelModule:
    """Convert a ProtoCircuit back into a TopLevelModule."""
    modules: dict[str, Module] = {}
    for pm in circuit.modules:
        mod_name, mod = _proto_module_to_module(pm)
        modules[mod_name] = mod
    return TopLevelModule(
        modules=modules,
        toplevel=circuit.top_module or None,
    )


# ---------------------------------------------------------------------------
# PIC YAML file loader
# ---------------------------------------------------------------------------

_BARE_ELLIPSIS_RE = re.compile(r"^\s*\.\.\.\s*$", re.MULTILINE)


def load_pic_yaml(path: str | Path) -> TopLevelModule:
    """
    Load a PIC YAML file and return a TopLevelModule.

    Handles non-standard constructs used in schema.pic.yaml:
    - Bare `...` lines (used as "etc." placeholders) are stripped before
      parsing; they are valid YAML document-end markers but break
      multi-document contexts when used mid-document.
    - `${settings.x}` interpolation strings are kept as-is (str values).
    """
    import yaml

    text = Path(path).read_text(encoding="utf-8")
    text = _BARE_ELLIPSIS_RE.sub("", text)
    raw = yaml.safe_load(text)
    return TopLevelModule.model_validate(raw)
