# kfnetlist

![Bidirectional netlist conversion between Spectre, Verilog-AMS and SPICE](docs/assets/netlist-conversion.gif)

**Build circuit netlists in Python and convert them both ways between SPICE, HSPICE,
Xyce, Spectre, Spectre-SPICE, Verilog-AMS and SystemVerilog, for electrical and
photonic circuits.**

**kfnetlist** is a standalone, Rust-backed netlist schema for
[kfactory](https://github.com/gdsfactory/kfactory) and netlist tooling.

It provides a fast, type-safe data model for circuit connectivity — instances,
nets, ports, and arrays — with full JSON/dict serialization and optional
Pydantic v2 integration. Python-independent Rust crates own the connectivity and
schema implementations; a separate PyO3 crate exposes them as native classes.

---

## Installation

```bash
pip install kfnetlist
```

Or with [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv add kfnetlist
```

Building from source requires a Rust toolchain and [maturin](https://www.maturin.rs/):

```bash
git clone https://github.com/gdsfactory/kfnetlist.git
cd kfnetlist
pip install maturin
maturin develop --release
```

## Quick Example

```python
from kfnetlist import Netlist, NetlistPort, PortRef

nl = Netlist()

# Add instances
nl.create_inst("wg1", kcl="MY_PDK", component="straight",
               settings={"width": 500, "length": 10_000})
nl.create_inst("wg2", kcl="MY_PDK", component="straight",
               settings={"width": 500, "length": 10_000})

# Add a top-level port and connect it
p_in = nl.create_port("in")
nl.create_net(p_in, PortRef(instance="wg1", port="o1"))

# Internal net
nl.create_net(
    PortRef(instance="wg1", port="o2"),
    PortRef(instance="wg2", port="o1"),
)

# Serialize to JSON
print(nl.to_json())
```

## Connectivity Verification

kfnetlist provides tools for LVS-style connectivity verification: detecting
opens, comparing against reference netlists, and finding geometric shorts.

```python
# Check for open circuits
opens = extracted_nl.detect_opens()
if opens["unconnected_ports"]:
    print(f"Unconnected: {opens['unconnected_ports']}")

# Compare against schematic
diff = extracted_nl.find_net_difference(schematic_nl)
if diff["missing"]:
    print(f"{len(list(diff['missing']))} nets missing from layout")

# Geometric short detection (requires klayout)
from kfnetlist.extract import detect_shorts
shorts = detect_shorts(l2n)
for s in shorts:
    print(f"Short: {s.net_a} <-> {s.net_b} on {s.layer}")
```

For a complete walkthrough, see the
[LVS Verification Guide](https://gdsfactory.github.io/kfnetlist/guides/lvs_verification/).

## Netlist Format Conversion

`kfnetlist.morphnet` (vendored from [morphnet](https://github.com/das-dias/morphnet))
parses every supported format into one `Netlist` model (`Netlist` → `Circuit` definitions
→ `SubCircuit` instances, serialized with the kfnetlist schema names) and writes it back out in
any other. Spectre to Verilog-AMS:

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.vams.writer import write_vams

netlist = parse_spectre("""\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
""")
print(write_vams(netlist))
```

```verilog
module rc_lowpass (in_, out, gnd);
  inout in_, out, gnd;
  resistor #(.value(1k)) R1 (.p(in_), .n(out));
  capacitor #(.value(100p)) C1 (.p(out), .n(gnd));
endmodule
```

Build circuits programmatically with the builder API, then export to any format:

```python
from kfnetlist import morphnet
from kfnetlist.morphnet.netlist import write_spectre, write_spice

rc = morphnet.circuit("rc_lowpass")
for name in ("in_", "out", "gnd"):
    rc.add_terminal(name)
rc.add(
    morphnet.subcircuit("R1", "resistor", value=1e3),
    morphnet.subcircuit("C1", "capacitor", value=100e-12),
)
rc.connect("in_", ("", "in_"), ("R1", "p"))
rc.connect("out", ("", "out"), ("R1", "n"), ("C1", "p"))
rc.connect("gnd", ("", "gnd"), ("C1", "n"))

netlist = morphnet.Netlist(name="rc").add(rc)
print(write_spice(netlist))
```

Any `kfnetlist.Netlist` graph, whether built by hand or extracted from layout, converts too:
`morphnet.from_netlists({"rc": netlist})` gives a morphnet `Netlist` for any writer, and
`morphnet.to_netlists(parse_spice(text))` reads any format back as `kfnetlist.Netlist`
graphs for LVS, open detection or flattening. Every morphnet `Netlist` also round-trips
through YAML, JSON and protobuf, simulation statements included.
See the [format conversion docs](https://gdsfactory.github.io/kfnetlist) and the
example notebooks in [`examples/`](examples/).

## Key Features

- **Rust core** — Netlist, Net, and port types are implemented in Rust for
  speed and memory safety, exposed via PyO3
- **Full serialization** — `to_json()` / `from_json()` and `to_dict()` /
  `from_dict()` on every type
- **Optional Pydantic v2 support** — all types implement
  `__get_pydantic_core_schema__`; install Pydantic separately to use it
- **Equivalent ports** — `Netlist.normalize()` folds electrically-equivalent
  ports into canonical names for netlist comparison
- **Hierarchical flattening** — `Netlist.flatten()` replaces instances by the
  contents of their own cell's netlist (and `flatten_netlists()` does it for a
  whole `{cell name: netlist}` mapping), rewiring nets across both levels
- **Instance removal** — `Netlist.remove_instances()` deletes sub-cell
  instances, merging the nets they touched
- **Port checking** — `PortCheck` bitmask and `check_connection()` for
  geometric port-pair comparison (requires klayout)
- **Connectivity verification** — `detect_opens()`, `find_net_difference()`,
  and `detect_shorts()` for LVS-style verification workflows
- **Netlist extraction** — `kfnetlist.extract` subpackage extracts hierarchical
  netlists from kfactory/klayout cells (requires klayout)

## Rust usage

The Cargo workspace contains `crates/kfnetlist-core` (connectivity),
`crates/kfnetlist-schema` (PIC documents, YAML, and protobuf), and
`crates/kfnetlist-python` (the `kfnetlist._native` extension). Rust consumers can
depend on the core directly, with no schema, Python, or PyO3 dependency:

```toml
[dependencies]
kfnetlist-core = { path = "/path/to/kfnetlist/crates/kfnetlist-core" }
serde_json = "1"
```

```rust
use kfnetlist_core::{Netlist, NetMember, PortRef};
use serde_json::json;

let mut nl = Netlist::default();
nl.create_inst("wg1".into(), "PDK".into(), "straight".into(),
               json!({"width": 0.5}), 1, 1)?;
let input = nl.create_port("in".into());
nl.create_net([
    NetMember::Port(input),
    NetMember::Ref(PortRef { instance: "wg1".into(), port: "o1".into() }),
])?;
let opens = nl.detect_opens();
let serialized = kfnetlist_core::to_json(&nl)?;
```

Run the complete example with `cargo run -p kfnetlist-core --example connectivity`.
Run Rust tests with `cargo test --workspace`, and Python compatibility tests
with `uv run --extra dev --with pydantic pytest`. Maturin uses the binding manifest configured in
`pyproject.toml`, so source and wheel builds still run from the repository root.
See [the Rust API guide](contributing/rust-core.md) for ownership, serialization,
and compatibility details.

The hierarchical PIC document and protobuf types live in `kfnetlist-schema`.
Python exposes them through `kfnetlist.kfnetlist_schema`; protobuf methods exchange
bytes, and YAML parsing runs in Rust. See [the circuit schema guide](contributing/circuit-schema.md)
for examples and migration notes.

## Architecture

```
kfnetlist
├── _native          # Rust extension (PyO3): Netlist, Net, NetlistPort,
│                    #   PortRef, PortArrayRef, NetlistInstance, NetlistArray
├── kfnetlist_schema  # Native circuit/PIC types and YAML loader
├── morphnet         # Netlist format conversion + circuit builder (vendored morphnet)
│   ├── netlist      #   Lark grammars, parsers and writers per format
│   └── morphnet_schema  # Pydantic models over circuit.proto / simulation.proto
├── port_check       # PortCheck bitmask + check_connection()
└── extract          # Netlist extraction from layout cells (requires klayout)
    ├── _algo        #   Main extraction orchestrator
    ├── _geometry    #   Optical net extraction from port adjacency
    ├── _l2n         #   Electrical layout-to-netlist via klayout
    └── _settings    #   Setting serialization helpers
```

## Documentation

Full documentation: https://gdsfactory.github.io/kfnetlist

## License

kfnetlist is released under the [Apache License 2.0](LICENSE).

The draft [explicit netlist references](contributing/explicit-netlist-references.md)
proposal adds `LeafNetlistInstance` / `RefNetlistInstance` and hierarchy validation
without requiring placement or generated layout cell names.
