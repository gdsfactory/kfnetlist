# Rust core and Python bindings

The repository is a Cargo workspace. `kfnetlist-core` depends on serde,
serde_json, and indexmap. `kfnetlist-python` depends on the core, PyO3, and
pythonize, and produces the existing `kfnetlist._native` extension. The default
workspace member is the core: plain `cargo build` and `cargo test` do not build
Python bindings.

## Native API

The core exports `Netlist`, `Net`, `NetMember`, `NetlistPort`, `PortRef`,
`PortArrayRef`, `NetlistInstance`, `NetlistArray`, `BBox`, `Placement`,
`PlacedExtra`, `PlacedInstance`, and `PlacedNetlist` at the crate root.

- Construct leaf values with Rust struct literals. Construct a sorted net with
  `Net::from_members(Vec<NetMember>)` and an empty netlist with `Netlist::default()`.
- `NetMember::{Port, Ref, ArrayRef}` represents all reference variants without
  inheritance. `PortArrayRef` contains the instance, port, and both array indices.
- `Netlist::create_inst` accepts JSON settings and array dimensions and returns
  an owned snapshot. `create_net` accepts an iterator of owned `NetMember` values.
  These methods validate their inputs before committing changes.
- `detect_opens` returns `Opens { unconnected_ports, singleton_nets }`.
  `find_net_difference` returns `NetDifference { missing, extra }`.
  Both results own their contents and preserve the Python API's ordering rules.
- `normalize` returns a new sorted netlist, normalizes integer-valued settings,
  and optionally folds equivalent ports using the `EquivalentPorts` and
  `PortMapping` map types. `sort` and `flatten_instances` mutate in place.
- `PlacedInstance` composes `instance: NetlistInstance` and `extra: PlacedExtra`.
  `PlacedNetlist` composes `netlist: Netlist` and an `extras` map. Its `create_inst`,
  `get_instance`, and `flatten_instances` methods keep connectivity and placement
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
modules. The JSON schema is unchanged: net members are untagged objects,
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
`flatten_instances` removes named instances and merges their touching nets; it
does not recursively expand child netlists.

## Development

```sh
cargo test -p kfnetlist-core
cargo run -p kfnetlist-core --example connectivity
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
uv run --extra dev --with pydantic --reinstall-package kfnetlist pytest
uv build
```

The integration tests exercise the core as an ordinary Rust consumer. The
Python suite checks the binding contract. CI runs both. Maturin reads
`crates/kfnetlist-python/Cargo.toml` through `pyproject.toml`; wheels and source
distributions include the workspace core dependency. Package versions are
inherited from the root `[workspace.package]` version, which the existing tbump
configuration updates together with the Python package version.
