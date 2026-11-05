# Circuit schema

`kfnetlist_schema` owns the hierarchical PIC document model, YAML parsing,
netlist elaboration, and protobuf conversion. It is usable from Rust without
Python. `crates/kfnetlist-schema/proto/{circuit,simulation}.proto` is the single
protobuf source for Rust and for `kfnetlist.morphnet`. The schema follows
morphnet's, so prefer additive changes there. `just compile-schema-py` regenerates
the morphnet Python stubs (`src/kfnetlist/morphnet/morphnet_schema/*_pb2.py`);
`prost-build` generates the Rust messages into Cargo's `OUT_DIR`. The build uses
a vendored `protoc`, so developers and wheel builders do not need to install it.
Generated code is neither checked in nor written into the source tree.

```rust
use kfnetlist_schema::{proto, TopLevelModule};
use prost::Message;

let document = TopLevelModule::from_yaml(
    "instances: {wg: {component: straight}}\nports: {in: 'wg,o1'}"
)?;
let netlists = document.to_netlists()?;
let bytes = document.to_proto()?;
let circuit = proto::Circuit::decode(bytes.as_slice())?;
let recovered = TopLevelModule::from_proto_circuit(&circuit)?;
assert_eq!(recovered, document);
# Ok::<(), Box<dyn std::error::Error>>(())
```

Python exposes owned Rust values through PyO3. The Python package contains
re-exports and compatibility functions that delegate to the native methods.
It does not need `protobuf`, `pydantic`, `pydantic-yaml`, or a Python YAML parser.

```python
from kfnetlist.kfnetlist_schema import TopLevelModule, ProtoCircuit, load_pic_yaml

document = load_pic_yaml("kfnetlist-schema/schema.pic.yaml")
netlists = document.to_netlists()
wire = document.to_proto()  # bytes encoded by Rust/prost
circuit = ProtoCircuit.from_proto(wire)
assert TopLevelModule.from_proto_circuit(circuit) == document
assert ProtoCircuit.from_proto(circuit.to_proto()) == circuit
```

The schema types accept keyword arguments, nested dictionaries, and other native
schema objects. Their fields are read-only; containers and nested objects returned
by getters are owned snapshots. Construct a replacement or use `from_dict()` to
change a document. `to_dict()` / `from_dict()` and `to_json()` / `from_json()` are
available on every schema type. The `model_validate`, `model_validate_json`,
`model_dump`, and `model_dump_json` names remain convenience aliases; these types
are no longer Pydantic `BaseModel` subclasses. Optional Pydantic integration uses
the same core-schema hook as the existing netlist classes.

Compared with the initial schema PR, `to_proto()` and `from_proto()` exchange
**bytes**, and the native schema classes no longer depend on Python protobuf
(only the vendored `kfnetlist.morphnet` imports it).

**Legacy fields.** The schema adopted morphnet's `circuit.proto`, which removed
or renamed some fields. Input dictionaries, JSON and keyword arguments with the
old names are still accepted. One rewrite in `crates/kfnetlist-python/src/schema.rs`
(`upgrade_legacy`) handles them and emits a single `DeprecationWarning`:

| Old field | Where the value goes |
|---|---|
| `uid`, `cross_section`, string `domain` | `properties["__uid__"]`, `properties["__cross_section__"]`, `properties["__domain__"]` |
| `Module.terminal` | `terminals` |
| `ModuleReference.parameter_values` | `parameters` entries with an empty name |
| `ModuleReference.parameter_overrides` | `parameters` entries named by key |

Deprecated getters with the old names read the values back.
`tests/data/legacy_schema_v0_3.json` pins outputs captured from the
pre-morphnet build.

**Net encoding.** `convert.rs` writes nets in morphnet's form: each net is a star of
`Connection`s named after the net, so morphnet's writers can read them.
`__from__`/`__members__` connection properties restore the exact document. On
read, modules without `__nets__` that carry `__placements__` use the
pre-morphnet decoder (`port_*`/`conn_*` connections, `__members__` buses).

The `Terminal_name` spelling of `TerminalReference.terminal_name` is still
accepted in input dictionaries. `ParameterValue` validates its `oneof`
in Rust, including when it occurs inside a nested dictionary.

`TopLevelModule.from_yaml()` accepts standard YAML. Bare single-module documents
are promoted to `modules["__root__"]`. `${settings.x}` expressions remain strings;
this layer does not evaluate them. Instance references support `inst,port`,
zero-based `inst[n],port`, and one-based `inst<ia.ib>,port`. Explicit array sizes
and `settings.array_size` are checked during elaboration. Unknown top-level
module names, malformed references, and invalid wire data raise `ValueError` in
Python and return errors in Rust.

Protobuf conversion preserves document settings, instance metadata, placements,
routes, display names, and logical nets using reserved properties where the
protobuf schema has no direct field. Exact JSON settings accompany numeric
protobuf values so large integers and booleans survive a round trip. Netlist
conversion retains connectivity, instances, arrays, settings, and instance
metadata. A connectivity `Netlist` has no fields for module settings, placements,
or routes; retain the document or protobuf representation when those are needed.
Unconnected top-level ports use a self-reference in a recovered module's `ports`
mapping and do not introduce a new net when elaborated again.

Run `cargo test -p kfnetlist-schema` for Python-independent schema and wire tests,
and `uv run --extra dev --with pydantic pytest` for the Python suite. A Python test
blocks imports of Python schema and codec packages in a fresh interpreter to
check that the Rust path is sufficient.
