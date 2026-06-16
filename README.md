# kfnetlist

**kfnetlist** is a standalone, Rust-backed netlist schema for
[kfactory](https://github.com/gdsfactory/kfactory) and netlist tooling.

It provides a fast, type-safe data model for circuit connectivity — instances,
nets, ports, and arrays — with full JSON/dict serialization and Pydantic v2
integration. The core types are implemented in Rust (via PyO3) for performance
and exposed as native Python classes.

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

## Key Features

- **Rust core** — Netlist, Net, and port types are implemented in Rust for
  speed and memory safety, exposed via PyO3
- **Zero runtime dependencies** — the base package has no Python dependencies
- **Full serialization** — `to_json()` / `from_json()` and `to_dict()` /
  `from_dict()` on every type
- **Pydantic v2 support** — all types implement `__get_pydantic_core_schema__`
- **Equivalent ports** — `Netlist.normalize()` folds electrically-equivalent
  ports into canonical names for netlist comparison
- **Instance flattening** — `Netlist.flatten_instances()` merges sub-cell
  instances into the parent, reconnecting touching nets
- **Port checking** — `PortCheck` bitmask and `check_connection()` for
  geometric port-pair comparison (requires klayout)
- **Connectivity verification** — `detect_opens()`, `find_net_difference()`,
  and `detect_shorts()` for LVS-style verification workflows
- **Netlist extraction** — `kfnetlist.extract` subpackage extracts hierarchical
  netlists from kfactory/klayout cells (requires klayout)

## Architecture

```
kfnetlist
├── _native          # Rust extension (PyO3): Netlist, Net, NetlistPort,
│                    #   PortRef, PortArrayRef, NetlistInstance, NetlistArray
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
