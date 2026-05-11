# Installation

## Install kfnetlist

```bash
pip install kfnetlist
```

Or with [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv add kfnetlist
```

The base package has **no runtime Python dependencies** — only the compiled Rust
extension is needed.

### Optional extras

| Extra | What it adds |
|-------|-------------|
| `kfnetlist[dev]` | Testing and linting tools (pytest, ruff, klayout) |

## Building from source

kfnetlist includes a Rust extension built with [maturin](https://www.maturin.rs/)
and [PyO3](https://pyo3.rs/). You need a Rust toolchain (1.70+) and Python 3.12+.

```bash
git clone https://github.com/gdsfactory/kfnetlist.git
cd kfnetlist
pip install maturin
maturin develop --release
```

## Verify the installation

```python
import kfnetlist

print(kfnetlist.__version__)

nl = kfnetlist.Netlist()
nl.create_inst("test", kcl="demo", component="straight", settings={"width": 500})
print("Instance created:", nl.instance_names())
```

If no errors appear, kfnetlist is installed correctly.

## Next steps

- [Quickstart](quickstart.py) — build and inspect your first netlist
- [Netlist Model](../concepts/netlist_model.py) — deep dive into the core data model
