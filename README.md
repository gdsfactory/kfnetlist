# kfnetlist

**kfnetlist** is a standalone, Rust-backed netlist schema for
[kfactory](https://github.com/gdsfactory/kfactory) and LVS tooling.

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

## Key Features

- **Rust core** — Netlist, Net, and port types are implemented in Rust for
  speed and memory safety, exposed via PyO3
- **Zero runtime dependencies** — the base package has no Python dependencies
- **Full serialization** — `to_json()` / `from_json()` and `to_dict()` /
  `from_dict()` on every type
- **Pydantic v2 support** — all types implement `__get_pydantic_core_schema__`
- **LVS equivalence** — `Netlist.lvs_equivalent()` folds electrically-equivalent
  ports for layout-vs-schematic comparison
- **Instance flattening** — `Netlist.flatten_instances()` merges sub-cell
  instances into the parent, reconnecting touching nets
- **Port checking** — `PortCheck` bitmask and `check_connection()` for
  geometric port-pair comparison (requires klayout)
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
