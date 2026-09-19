# Rust core and Python bindings

The repository is a Cargo workspace. `kfnetlist-core` depends only on serde,
serde_json, and indexmap. `kfnetlist-schema` depends on the core and owns PIC
documents, YAML, and protobuf. `kfnetlist-python` binds both crates with PyO3
and produces the existing `kfnetlist._native` extension. The default workspace
member is the core: plain `cargo build` and `cargo test` do not build schema or
Python bindings.

## Native API

The core exports `Netlist`, `Net`, `NetMember`, `NetlistPort`, `PortRef`,
`PortArrayRef`, `NetlistInstance`, `LeafNetlistInstance`, `RefNetlistInstance`,
`NetlistArray`, `BBox`, `Placement`,
`PlacedExtra`, `PlacedInstance`, and `PlacedNetlist` at the crate root.

- Construct leaf values with Rust struct literals. Construct a sorted net with
  `Net::from_members(Vec<NetMember>)` and an empty netlist with `Netlist::default()`.
- `NetMember::{Port, Ref, ArrayRef}` represents all reference variants without
  inheritance. `PortArrayRef` contains the instance, port, and both array indices.
- `Netlist::create_inst` accepts JSON settings and array dimensions and returns
  an owned snapshot. `create_net` accepts an iterator of owned `NetMember` values.
  These methods validate their inputs before committing changes.
- `NetlistInstance::{Leaf, Ref}` distinguishes component leaves from explicit
  child-netlist references. Common fields remain accessible through `Deref`.
  `hierarchy_from_json` and `validate_hierarchy` validate document references.
  See [the draft reference contract](explicit-netlist-references.md) for wire
  format and compatibility details.
- The instance `info` field stores JSON-compatible per-instance metadata.
  `create_inst_with_info` accepts metadata while `create_inst` retains the
  original signature and defaults it to an empty map.
- `detect_opens` returns `Opens { unconnected_ports, singleton_nets }`.
  `find_net_difference` returns `NetDifference { missing, extra }`.
  Both results own their contents and preserve the Python API's ordering rules.
- `normalize` returns a new sorted netlist, normalizes integer-valued settings,
  and optionally folds equivalent ports using the `EquivalentPorts` and
  `PortMapping` map types. `sort` and `remove_instances` mutate in place.
- Hierarchical inlining is available without Python through `flatten_netlist`,
  `NetlistData`, and `FlattenOptions`. The result contains flattened data plus
  any requested non-fatal skipped-instance diagnostics.
- `PlacedInstance` composes `instance: NetlistInstance` and `extra: PlacedExtra`.
  `PlacedNetlist` composes `netlist: Netlist` and an `extras` map. Its `create_inst`,
  `get_instance`, and `remove_instances` methods keep connectivity and placement
  together. `PlacedNetlist::new` drops extras for unknown instance names.
- `Error` distinguishes invalid dimensions, missing instances and ports, array
  bounds, missing canonical ports, and JSON failures. Callers can match its
  variants; it implements `Display` and `std::error::Error`.

The native model exposes its fields for ordinary Rust manipulation. Direct
field mutation and deserialization do not run connectivity validation. Use the
creation methods when validation is required. Keep instance names consistent
with their map keys when editing maps manually.

## Serialization and comparison

Core values implement serde traits. `kfnetlist_core::to_json` and `from_json`
provide JSON conversion with native errors; wire types live in their respective
modules. Existing leaf JSON remains supported; reference instances add a required string
`ref`. Net members remain untagged objects,
instance names are omitted from values and restored from parent map keys, null
settings serialize as `{}`, and absent array metadata is omitted. Standalone
instance deserialization leaves its name empty; the wire conversion methods
accept a name when one is needed.

`Net::from_members` sorts members. Direct serde loading preserves member order,
as existing netlist loading does; call `sort_in_place`, `Netlist::sort`, or
`Netlist::normalize` before comparing unsorted input. `Netlist` equality includes
instance insertion order. Native placed-value equality includes physical
attributes; compare their `netlist` or `instance` fields for connectivity-only
comparison. Python placed classes retain their inherited connectivity-only
comparison behavior.

A placed netlist without explicit extras serializes default physical attributes
for each instance. Deserializing that output materializes those defaults in the
extras map, while preserving the effective per-instance values.

## Python compatibility boundary

PyO3 classes own core values. `PortArrayRef` still subclasses `PortRef`,
`PlacedInstance` still subclasses `NetlistInstance`, and `PlacedNetlist` still
subclasses `Netlist`. Their Python parent and child layers hold the corresponding
parts of the core representation. Placement mutations temporarily compose those
parts into a core value and restore them after the operation, including errors.

Python-only code handles argument extraction, dictionaries and lists, property
snapshots, iteration, repr, rich comparison, and Pydantic schemas. Lookup errors
remain `KeyError`; domain validation and JSON failures remain `ValueError`.
Python collection getters and the objects they contain are independent snapshots.
Inherited `PlacedNetlist.normalize()` continues to return a plain `Netlist`.

Existing array behavior is retained: a zero instance dimension disables array
metadata; otherwise dimensions must be positive. `(1, 1)` array references
collapse to plain references; other reference indices have upper-bound checks.
`remove_instances` removes named instances and merges their touching nets.
`flatten_instances` remains a deprecated Rust and Python alias; hierarchical
`flatten` replaces instances with the contents of their child netlists.

## Development

```sh
cargo test -p kfnetlist-core
cargo test -p kfnetlist-schema
cargo run -p kfnetlist-core --example connectivity
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
uv run --extra dev --with pydantic --reinstall-package kfnetlist pytest
uv build
```

The integration tests exercise the core as an ordinary Rust consumer. The
Python suite checks the binding contract. CI runs both. Maturin reads
`crates/kfnetlist-python/Cargo.toml` through `pyproject.toml`; wheels and source
distributions include both workspace dependencies. Package versions are
inherited from the root `[workspace.package]` version, which the existing tbump
configuration updates together with the Python package version.
