# kfnetlist Package Overview

## What is kfnetlist?

kfnetlist is a standalone, high-performance netlist schema for circuit connectivity manipulation. It provides a decoupled, lightweight data model for representing and manipulating circuit netlists without requiring the full [kfactory](https://github.com/gdsfactory/kfactory)/klayout stack.

The core data types and algorithms live in the Python-independent **Rust** crate `kfnetlist-core`. The separate `kfnetlist-python` crate exposes the Python API via PyO3. Extraction logic and port checking remain in Python for interoperability with klayout.

## Key Features

- **Zero runtime dependencies** for the core package (Rust-backed types only)
- **Hierarchical netlists**: instances, nets, top-level ports, and array instances
- **Full serialization**: JSON and Python dict round-trips on every type
- **LVS-equivalent port folding**: collapse equivalent ports (e.g. multi-pad cells) into canonical names with automatic net merging
- **Hierarchical flattening**: replace instances by the contents of their own cell's netlist, rewiring nets across both levels
- **Instance removal**: delete intermediate instances and re-merge their nets
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

### Rust workspace

| Crate | Responsibility |
|-------|----------------|
| `crates/kfnetlist-core` | Native connectivity and placement values, serde wire formats, validation, normalization, hierarchical flattening, instance removal, open detection, and net differences |
| `crates/kfnetlist-python` | PyO3 classes and inheritance, mutable Python properties, collection snapshots, iterators, repr/comparison, Pydantic integration, and exception conversion |

Both crates have `port`, `net`, `instance`, `netlist`, and `placement` modules.
Core values contain no Python objects; binding classes own core values. The
binding crate's `lib.rs` registers the `kfnetlist._native` module. See
[the Rust API guide](rust-core.md) for the native public API and testing commands.

### Python Modules (`src/kfnetlist/`)

| Module | Purpose | Dependencies |
|--------|---------|-------------|
| `__init__.py` | Re-exports all public types from `_native` and `port_check` | None (beyond _native) |
| `_native.pyi` | Type stubs for the Rust extension | None |
| `_flatten.py` | `flatten_netlists()`: flatten a whole `{cell name: netlist}` mapping | None (beyond _native) |
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
A reference to a port on a named instance. `name` is the port name alone (the instance is a separate field). Supports `as_python_str()` for code generation.

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
| `remove_instances(names)` | Delete instances, merging the nets they touched (`flatten_instances` is a deprecated alias) |
| `flatten(netlists, cells=None, ...)` | Replace instances by the contents of their own cell's netlist |
| `sort()` | Normalize ordering of instances, nets, ports |
| `normalize(cell_name=None, equivalent_ports=None, ...)` | Return a new netlist with equivalent ports collapsed |
| `to_json()` / `from_json(s)` | JSON serialization |
| `to_dict()` / `from_dict(d)` | Python dict serialization |
| `instances` / `nets` / `ports` | Properties returning fresh snapshots |

### Placement-Aware Flavor (from `_native`)

A second flavor carries physical **placement** geometry alongside connectivity.
The types subclass the plain ones (via PyO3 `#[pyclass(extends = ...)]`), so
`isinstance(placed, Netlist)` is true and all inherited behaviour (nets, ports,
instance removal, sorting, LVS folding) works unchanged.

#### `Placement(x, y, orientation, mirror, bbox)`
A purely **geometric** value object — *where* an instance sits, not *what* it
is:

| Field | Meaning |
|-------|---------|
| `x`, `y` | Origin displacement, micrometres |
| `orientation` | Rotation about the origin, degrees |
| `mirror` | Mirror flag (klayout convention) |
| `bbox` | Bounding box dict `{"left", "bottom", "right", "top"}`, µm |

`bbox` is exposed and serialized as a plain dict, never as a class. The placed
cell's *name* is an intrinsic instance property and lives on `PlacedInstance`,
not here.

#### `PlacedInstance(kcl, component, settings=None, array=None, name="", cell="", placement=None)`
Subclass of `NetlistInstance` adding the placed `cell` name and a `placement`.
Inherits all connectivity fields (`kcl`, `component`, `settings`, `array`,
`name`). `cell` is the layout cell name — distinct from `component`, which is
the factory name (falling back to the cell name).

#### `PlacedNetlist()`
Subclass of `Netlist` whose `instances` property returns `PlacedInstance`
objects, with an extra `placements` map keyed by instance name.

| Method | Description |
|--------|-------------|
| `from_netlist(netlist, placements=None, cells=None)` | Upgrade a plain `Netlist`, attaching per-instance placement geometry and cell names (entries for absent instances are dropped; instances without one get empty defaults) |
| `create_inst(name, kcl, component, settings=None, na=1, nb=1, cell="", placement=None)` | Add an instance with optional cell name and placement (base parameter order preserved) |
| `flatten(netlists, cells=None, ...)` | As `Netlist.flatten`, but returns a `PlacedNetlist`: resolves each instance's cell from `PlacedInstance.cell` and composes each inlined placement with the placement of the instance it came from |
| `placements` | Property: `dict[str, Placement]` for instances that have one |

Placement is **excluded from equality**, so LVS comparisons are unaffected by
the extra geometry.

### Hierarchical Flattening

#### `Netlist.flatten(netlists, cells=None, *, exclude=None, instance_cell_map=None, sub_instance_cell_maps=None, recursive=True, allow_unconnected_ports=False, warn_skipped=False, separator=".")`
Replace instances by the contents of their own cell's netlist. `netlists` is a
`{cell name: Netlist | PlacedNetlist}` mapping (what `extract()` returns); the
inlined instances are renamed `"{instance}{separator}{inner instance}"` and the
nets of both levels are merged through the sub-cell's ports.

| Argument | Meaning |
|----------|---------|
| `cells` | Cell names to inline; `None` inlines everything resolvable |
| `exclude` | Cell names never to inline (wins over `cells`) |
| `instance_cell_map` | This netlist's `{instance name: cell name}` — a plain `NetlistInstance` does not record its cell (`component` is the factory name) |
| `sub_instance_cell_maps` | `{cell name: {instance name: cell name}}` for the levels below, needed when `recursive=True` |
| `recursive` | Keep inlining inside what was just inlined |
| `allow_unconnected_ports` | Inline even when a connected port has no net inside the sub-cell (dropping that connection) instead of raising |
| `warn_skipped` | Warn about every instance left alone |

Instances are skipped when their cell has no instances of its own (a
primitive), their cell name is unknown, or they are arrays (`na`/`nb` > 1).
Inner nets that touch no sub-cell port stay as floating nets; an inner net
touching two sub-cell ports merges both parent nets.

#### `flatten_netlists(netlists, cells=None, *, exclude=None, instance_cell_maps=None, ...) -> dict[str, Netlist]`
Apply `flatten()` to every entry of a `{cell name: netlist}` mapping. Each
netlist is flattened against the original mapping, so the result is independent
of iteration order, and inlined cells keep their own entry. There is a single
map argument here — `instance_cell_maps` (`{cell name: {instance name: cell
name}}`) — since every entry's own cell name is known from the mapping key.

### Port Checking

#### `PortCheck` (IntFlag)
Bitmask flags: `opposite`, `same`, `width`, `layer`, `cross_section`, `port_type`, `position`, `all_opposite`, `all_overlap`.

#### `check_connection(p1, p2, *, tolerance=0.1, angle_tolerance=0.01, snapped=False) -> int`
Compare two duck-typed ports, returning a `PortCheck` bitmask. Uses integer transforms when both ports have `trans`, otherwise complex transforms with tolerances.

### Extraction (requires klayout)

#### `extract(cell, *, wrap_kdb_instance, port_types, mark_port_types, ..., include_placement=False, flatten=False) -> dict[str, Netlist]`
Full hierarchical extraction: optical nets from geometry + electrical nets from klayout L2N. With `include_placement=True`, each returned value is a `PlacedNetlist` whose instances additionally carry a `Placement` read from the layout; the default returns plain `Netlist` objects, identical to before. With `flatten=True` (or a sequence of cell names) the selected instances are replaced by the contents of their own cell's netlist; extraction supplies the instance→cell mapping, so this works for either flavor.

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
      {"name": "in"},
      {"instance": "wg1", "port": "o1"}
    ]
  ],
  "ports": [{"name": "in"}, {"name": "out"}]
}
```

Instance names are dict keys (not duplicated inside the value). Net members are untagged objects distinguished by their fields. The `NetlistWire` serde struct in Rust handles this mapping.

A `PlacedNetlist` uses the same shape, with each instance value extended by a `placement` block:

```json
{
  "instances": {
    "wg1": {
      "kcl": "PDK",
      "component": "straight",
      "settings": {"width": 500},
      "cell": "straight",
      "placement": {
        "x": 10.0, "y": 5.0,
        "orientation": 90.0,
        "mirror": false,
        "bbox": {"left": 0.0, "bottom": 0.0, "right": 10.0, "top": 0.5}
      }
    }
  },
  "nets": [],
  "ports": []
}
```

## Optional Dependencies

| Dependency | When needed |
|-----------|-------------|
| klayout >= 0.30.8 | `port_check.check_connection()`, `kfnetlist.extract` |
| Pydantic v2 | Pydantic model validation (all types support it) |
| kfactory | The `wrap_kdb_instance` callable in `extract()` typically comes from kfactory |
