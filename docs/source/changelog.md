# Changelog

## Unreleased

- **Bidirectional netlist format conversion** — morphnet's source is vendored as
  `kfnetlist.morphnet`. Its runtime dependencies (`lark`, `protobuf`, `pydantic`,
  `pydantic-yaml`) become kfnetlist dependencies.
  It provides Lark parsers and writers for SPICE, HSPICE, Xyce, Spectre,
  Spectre-SPICE and Verilog-AMS, plus the programmatic circuit builder
  (`morphnet.circuit()`, `subcircuit()`, `connect()`, ...).
  `morphnet.from_netlists()` / `to_netlists()` bridge to
  `Netlist`. The native netlist and schema classes still import none of these.
- **One naming everywhere: `Netlist` → `Circuit` → `SubCircuit`.** The container,
  circuit definition and instance have the same names in `circuit.proto`, Rust,
  the PyO3 schema classes, the PIC document model and `kfnetlist.morphnet`:

  | Layer | Before | Now |
  |---|---|---|
  | proto messages | `Circuit`, `Module`, `ModuleReference`, `ExternalModule` | `Netlist`, `Circuit`, `SubCircuit`, `ExternalCircuit` |
  | proto fields | `top_module`, `modules`, `ext_modules`, `module_references`, `module_name` | `top_circuit`, `circuits`, `ext_circuits`, `subcircuits`, `circuit_name` |
  | `kfnetlist_schema` | `ProtoCircuit` (container), `ProtoModule`, `ProtoModuleReference`, `ExternalModule` | `ProtoNetlist`, `ProtoCircuit` (definition), `ProtoSubCircuit`, `ExternalCircuit` |
  | PIC documents | `TopLevelModule`, `Module`, `Instance` | `NetlistDocument`, `CircuitDocument`, `SubCircuitDocument` (YAML keys unchanged) |
  | conversions | `to_proto_circuit()`, `from_proto_circuit()` | `to_proto_netlist()`, `from_proto_netlist()` |
  | morphnet | `Circuit`, `Module`, `ModuleReference`, `module()`, `module_reference()`, `ext_module()` | `Netlist`, `Circuit`, `SubCircuit`, `circuit()`, `subcircuit()`, `ext_circuit()` |

  - The wire format is unchanged (same field numbers), so protobuf bytes from
    earlier versions decode as before.
  - Old keyword arguments, dict, JSON and YAML keys still load, with one
    `DeprecationWarning`. Old getters and old class/function names remain as
    deprecated aliases. `ProtoCircuit` is the exception: it now names the
    circuit definition, and container data passed to it is rejected.
  - morphnet JSON and YAML use the schema names, so
    `ProtoNetlist.from_json(netlist.to_json())` loads them.
- **One circuit schema** — `circuit.proto` and the new `simulation.proto` now
  follow morphnet's schema (renamed as above), shared by Rust and Python. It adds simulation,
  directives, external libraries and `Terminal.discipline`. It removes `uid`,
  `Terminal.cross_section` and the string `domain` fields, renames
  `terminal` to `terminals`, and replaces the instance
  `parameter_values`/`parameter_overrides` with `parameters`.
  - Backward compatible: the old keyword arguments, dict and JSON keys are
    still accepted with a `DeprecationWarning`. Removed values are kept in
    `properties["__<field>__"]` (or in `parameters`), and deprecated getters read
    them back.
  - Documents encoded by earlier versions (`NetlistDocument.to_proto()`) decode
    unchanged.
  - Not readable: hand-built `ProtoSubCircuit` bytes that use the old
    `parameter_values` (field 10) or `parameter_overrides` (field 20).
  - `NetlistDocument.to_proto()` now encodes nets in morphnet's named-net form,
    which earlier versions cannot read.
- **SI prefixes** — `PrefixedValue.prefix` is applied when converting to
  `Netlist` settings (`1k` becomes `1000.0`).
- **Zero Python runtime dependencies** — protobuf and YAML parsing now run
  entirely in the native extension. The duplicate Python schema converters and
  generated protobuf module were removed. Pydantic interoperability remains
  available when applications install Pydantic separately.
- **Pure connectivity core** — PIC documents, YAML, and protobuf moved from
  `kfnetlist-core` into the new `kfnetlist-schema` crate.
- **Instance removal** no longer creates empty nets when an absent or isolated
  instance is removed.
- **Selective instance flattening** — an explicit `instance_cell_map` now
  selects which starting instances may flatten, in addition to supplying their
  cell names. Omitted instances remain intact throughout recursion, including
  placed instances of the same cell. `None` considers all instances; `{}`
  selects none. Descendants of selected instances inherit eligibility, subject
  to `cells` / `exclude`. `sub_instance_cell_maps` remains a cell-name lookup.
  This changes the previous lookup-only behavior of `instance_cell_map`.
- **Instance metadata** — `NetlistInstance.info` and `PlacedInstance.info`
  carry JSON-compatible dictionaries, accepted through keyword-only `info=`
  constructor and `create_inst()` arguments. Extraction copies named kfactory
  instances' metadata. Metadata survives serialization, normalization, placement
  conversion, and child promotion during flattening. Empty metadata is omitted
  from output, and existing payloads without `info` remain readable.
- **`Netlist.flatten()`** — hierarchical flattening: replace instances by the
  contents of their own cell's netlist, rewiring the parent's nets through the
  sub-cell's ports. Selectable per cell (`cells` / `exclude`), recursive by
  default, and placement-aware on `PlacedNetlist` (each inlined placement is
  composed with the placement of the instance it came from).
  `kfnetlist.flatten_netlists()` applies it to a whole `{cell name: netlist}`
  mapping, and `extract(..., flatten=...)` does it as part of extraction.
- **`Netlist.flatten_instances()` renamed to `remove_instances()`** — the old
  name still works but raises a `DeprecationWarning`. It never inlined
  anything: it deletes instances and merges the nets they touched, which the
  new `flatten()` would otherwise be confused with.
- **Optional net names** — `Net` carries a `name`, set at construction
  (`Netlist.create_net(..., name=...)`, `Net(..., name=...)`, both
  keyword-only) and copied by `Netlist.add_net()`. The name survives
  serialization, `remove_instances()`, `normalize()` and `flatten()`; a merged
  net keeps the name of the lowest-indexed net that had one. Names are
  metadata, not identity: equality, hashing and ordering ignore them, so
  connectivity comparison is unchanged. A named net is written as
  `{"name": ..., "members": [...]}`; an unnamed net keeps the historical bare
  JSON array, and reading accepts both. The object form requires `members` and
  rejects unknown fields. **Forward incompatibility:** a reader released before
  this change expects a net to be an array and rejects any document containing
  a named net. Names travel with the netlist JSON only — the PIC-document
  (YAML/protobuf) net representation has no name slot yet, so
  `Module.from_netlist()` still drops them.

## 0.2.0

- **`find_net_difference()`** (renamed from `find_open_nets`) — compares
  two netlists by symmetric difference on their sorted nets, returning
  `{"missing": [Net, ...], "extra": [Net, ...]}` instead of the previous
  flat list. The new structure distinguishes nets absent from the layout
  (missing) vs. unexpected nets (extra).
- **`normalize()` replaces `lvs_equivalent()`** — the method name was
  changed to better reflect its purpose: fold equivalent ports into
  canonical names and merge nets sharing a canonical reference. The API
  and behaviour are unchanged.
- **Python 3.14 support** — classifier and CI testing added.

## 0.1.5

- **L2N parsing** — `parse_l2n()` and `l2n_to_json()` convert a klayout
  `LayoutToNetlist` to a JSON-serializable dict (or string) with optional
  hierarchy flattening and layer/instance filtering
- **Geometric short detection** — `detect_shorts()` finds polygon overlaps
  between electrically distinct nets on the same layer
- **Open detection** — `Netlist.detect_opens()` finds unconnected ports and
  singleton nets; `Netlist.find_net_difference(reference)` compares against a
  reference netlist to find missing and extra nets

## 0.1.0

Initial release.

- Rust-backed core types: `Netlist`, `Net`, `NetlistPort`, `PortRef`, `PortArrayRef`,
  `NetlistInstance`, `NetlistArray`
- Full JSON/dict serialization on all types
- Pydantic v2 integration (`__get_pydantic_core_schema__`)
- `Netlist.normalize()` for folding electrically-equivalent ports
- `Netlist.flatten_instances()` for merging sub-cell instances
- `PortCheck` bitmask and `check_connection()` for geometric port comparison
- `kfnetlist.extract` subpackage for hierarchical netlist extraction from layout cells
