# kfnetlist Package Overview

## What is kfnetlist?

kfnetlist is a standalone, high-performance netlist schema for circuit connectivity manipulation. It provides a decoupled, lightweight data model for representing and manipulating circuit netlists without requiring the full [kfactory](https://github.com/gdsfactory/kfactory)/klayout stack.

The core data types are implemented in **Rust** (via PyO3) for performance, while the extraction logic and port checking remain in Python for flexibility and interoperability with klayout.

## Key Features

- **Zero runtime dependencies** for the core package (Rust-backed types only)
- **Hierarchical netlists**: instances, nets, top-level ports, and array instances
- **Full serialization**: JSON and Python dict round-trips on every type
- **LVS-equivalent port folding**: collapse equivalent ports (e.g. multi-pad cells) into canonical names with automatic net merging
- **Instance flattening**: remove intermediate instances and re-merge their nets
- **Port connection checking**: bitmask-based pairwise port comparison (direction, width, layer, position)
- **Layout extraction** (optional, requires klayout): extract optical and electrical netlists from layout cells
- **Pydantic v2 compatibility**: all types implement `__get_pydantic_core_schema__` for seamless validation

## Architecture

```
                          ┌───────────────────────────┐
                          │       User Code            │
                          └────────────┬──────────────┘
                                       │
                          ┌────────────▼──────────────┐
                          │   kfnetlist.__init__       │
                          │   (public API surface)     │
                          └──┬──────────┬──────────┬──┘
                             │          │          │
              ┌──────────────▼──┐  ┌────▼────┐  ┌──▼──────────────────┐
              │  _native (Rust) │  │port_check│  │ extract (optional)  │
              │  via PyO3       │  │ (Python) │  │ requires klayout    │
              │                 │  │          │  │                     │
              │ NetlistPort     │  │PortCheck │  │ _algo.py  (orchestr)│
              │ PortRef         │  │check_    │  │ _geometry.py (optic)│
              │ PortArrayRef    │  │connection│  │ _l2n.py    (electr) │
              │ Net             │  │          │  │ _settings.py (serde)│
              │ NetlistInstance  │  └──────────┘  └─────────────────────┘
              │ NetlistArray    │
              │ Netlist         │
              └─────────────────┘
```

### Rust Modules (`src/*.rs`)

| Module | Purpose |
|--------|---------|
| `lib.rs` | PyO3 module bootstrap, shared helpers (hashing, comparison, serde wrappers) |
| `port.rs` | `NetlistPort`, `PortRef`, `PortArrayRef` types with ordering, hashing, serialization |
| `net.rs` | `Net` container (sorted member collection) and `NetMember` enum |
| `instance.rs` | `NetlistInstance` and `NetlistArray` types |
| `netlist.rs` | `Netlist` orchestrator: instance/port/net management, flattening, LVS equivalence, sorting |

### Python Modules (`src/kfnetlist/`)

| Module | Purpose | Dependencies |
|--------|---------|-------------|
| `__init__.py` | Re-exports all public types from `_native` and `port_check` | None (beyond _native) |
| `_native.pyi` | Type stubs for the Rust extension | None |
| `port_check.py` | `PortCheck` bitmask enum and `check_connection()` function | klayout (lazy import) |
| `extract/__init__.py` | Re-exports extraction functions | klayout |
| `extract/_algo.py` | Main extraction orchestrator (`extract()`) | `_geometry`, `_l2n`, `_settings`, kfnetlist core |
| `extract/_geometry.py` | Optical net extraction from port adjacency (`get_optical_nets()`) | `port_check`, klayout |
| `extract/_l2n.py` | Electrical layout-to-netlist via klayout L2N (`l2n_elec()`) | klayout |
| `extract/_settings.py` | Serialize klayout shapes to JSON-safe strings (`serialize_setting()`) | klayout |

## Public API Reference

### Core Types (from `_native`)

#### `NetlistPort(name: str)`
A top-level (cell-level) port. Hashable, orderable, serializable.

#### `PortRef(instance: str, port: str)`
A reference to a port on a named instance. Has a derived `name` property (`"instance,port"`). Supports `as_python_str()` for code generation.

#### `PortArrayRef(instance: str, port: str, ia: int, ib: int)`
Extends `PortRef` with array index coordinates. When `ia=1, ib=1`, automatically collapsed to a plain `PortRef` inside `create_net()`.

#### `NetlistArray(na: int, nb: int)`
Dimensions for an array instance.

#### `NetlistInstance(kcl, component, settings=None, array=None, name="")`
An instance of a sub-cell. Tracks which KCL and component it came from, plus serialized settings.

#### `Net(members=None)`
An unordered collection of connected `NetMember` items (`NetlistPort | PortRef | PortArrayRef`). Supports `len`, iteration, indexing, membership testing, `append`, `extend`, and `sort`.

#### `Netlist()`
The top-level container. Key methods:

| Method | Description |
|--------|-------------|
| `create_inst(name, kcl, component, ...)` | Add an instance (validates array dimensions) |
| `create_port(name)` | Add a top-level port |
| `create_net(*members)` | Wire 2+ members together (validates existence) |
| `add_net(net)` | Add a pre-constructed `Net` |
| `flatten_instances(names)` | Remove instances, merge their nets |
| `sort()` | Normalize ordering of instances, nets, ports |
| `lvs_equivalent(cell_name, equivalent_ports, ...)` | Return a new netlist with equivalent ports collapsed |
| `to_json()` / `from_json(s)` | JSON serialization |
| `to_dict()` / `from_dict(d)` | Python dict serialization |
| `instances` / `nets` / `ports` | Properties returning fresh snapshots |

### Port Checking

#### `PortCheck` (IntFlag)
Bitmask flags: `opposite`, `same`, `width`, `layer`, `cross_section`, `port_type`, `position`, `all_opposite`, `all_overlap`.

#### `check_connection(p1, p2, *, tolerance=0.1, angle_tolerance=0.01, snapped=False) -> int`
Compare two duck-typed ports, returning a `PortCheck` bitmask. Uses integer transforms when both ports have `trans`, otherwise complex transforms with tolerances.

### Extraction (requires klayout)

#### `extract(cell, *, wrap_kdb_instance, port_types, mark_port_types, ...) -> dict[str, Netlist]`
Full hierarchical extraction: optical nets from geometry + electrical nets from klayout L2N.

#### `get_optical_nets(cell, port_types, *, allow_width_mismatch) -> list[Net]`
Extract optical nets from geometric port adjacency within a single cell.

#### `l2n_elec(cell, mark_port_types, connectivity, port_mapping) -> kdb.LayoutToNetlist`
Build a klayout LayoutToNetlist from electrical port markers.

#### `serialize_setting(setting) -> Any`
Recursively serialize klayout shapes to `"!#ClassName <str>"` format.

## Data Model

The netlist data model is a flat hierarchy:

```
Netlist
├── ports: list[NetlistPort]           # top-level I/O
├── instances: dict[str, NetlistInstance]  # named sub-cell instances
│   └── each has: kcl, component, settings, optional array
└── nets: list[Net]                    # connectivity
    └── each contains: list[NetMember]
        where NetMember = NetlistPort | PortRef | PortArrayRef
```

A `Net` connects members together. Each member is either:
- A **top-level port** (`NetlistPort`) of the current cell
- A **port on an instance** (`PortRef` or `PortArrayRef`)

Nets are unordered collections. The `sort()` method normalizes everything for deterministic comparison and serialization.

## JSON Wire Format

```json
{
  "instances": {
    "wg1": {
      "kcl": "PDK",
      "component": "straight",
      "settings": {"width": 500}
    }
  },
  "nets": [
    [
      {"Port": "in"},
      {"Ref": {"instance": "wg1", "port": "o1"}}
    ]
  ],
  "ports": ["in", "out"]
}
```

Instance names are dict keys (not duplicated inside the value). Net members are tagged unions (`Port`, `Ref`, `ArrayRef`). The `NetlistWire` serde struct in Rust handles this mapping.

## Optional Dependencies

| Dependency | When needed |
|-----------|-------------|
| klayout >= 0.30.8 | `port_check.check_connection()`, `kfnetlist.extract` |
| Pydantic v2 | Pydantic model validation (all types support it) |
| kfactory | The `wrap_kdb_instance` callable in `extract()` typically comes from kfactory |
