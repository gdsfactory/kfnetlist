# Netlist Extraction

The `kfnetlist.extract` subpackage extracts hierarchical netlists from
kfactory/klayout layout cells. It requires [klayout](https://klayout.de) as a
runtime dependency.

## Architecture

Extraction combines two complementary approaches:

1. **Optical nets** — extracted from geometric port adjacency (ports that
   physically touch in the layout are connected)
2. **Electrical nets** — extracted using klayout's built-in `LayoutToNetlist`
   engine with user-defined connectivity rules

The main `extract()` function orchestrates both, walks the cell hierarchy, and
returns a `dict[str, Netlist]` keyed by cell name.

## Pipeline

```
extract(cell)
    │
    ├── gather equivalent ports from cell/factory metadata
    │
    ├── l2n_elec(cell)              ← electrical connectivity
    │   ├── duplicate layout
    │   ├── materialize port markers as Text shapes
    │   ├── connect layers per connectivity rules
    │   └── klayout extract_netlist()
    │
    └── for each cell in hierarchy:
        ├── get_optical_nets(cell)   ← geometric port adjacency
        │   ├── bucket cell ports by (x, y, layer)
        │   ├── bucket instance ports by (x, y, layer)
        │   └── check_connection() on candidate pairs
        │
        ├── merge optical + electrical nets
        ├── flatten unnamed / excluded instances
        └── apply equivalent port folding if equivalent ports defined
```

## Requirements

The extraction subpackage uses Protocol types to remain decoupled from kfactory's
concrete classes. The only hard dependency is `klayout` (for `kdb.LayoutToNetlist`,
`kdb.Region`, transforms, etc.).

The `wrap_kdb_instance` callback bridges kfnetlist's protocol-based API with
kfactory's instance wrapper. In kfactory, this is typically:

```python
lambda i: Instance(kcl=cell.kcl, instance=i)
```

## Submodules

| Module | Purpose |
|--------|---------|
| [`extract`](overview.md) | Main `extract()` orchestrator |
| [`get_optical_nets`](optical_nets.md) | Geometric port-adjacency extraction |
| [`l2n_elec`](electrical_l2n.md) | Electrical layout-to-netlist |
| [`parse_l2n`](l2n_parsing.py) | Convert L2N results to JSON-serializable dicts |
| [`detect_shorts`](short_detection.py) | Geometric short detection via polygon overlap |
| [`check_connection`](port_checking.py) | Port-pair comparison bitmask |

## kfactory examples

kfactory uses kfnetlist internally for netlist extraction. The kfactory docs
have end-to-end examples showing extraction in practice:

- [Schematic-Driven Design](https://gdsfactory.github.io/kfactory/dev/schematics/overview/) —
  building circuits, extracting netlists with `cell.netlist()`, and comparing
  connectivity
- [Netlist & Schematic I/O](https://gdsfactory.github.io/kfactory/dev/schematics/netlist/) —
  inspecting `Netlist` objects, sorting for stable comparison, serialization,
  and handling electrically-equivalent ports
- [45° Crossing with Virtual Cells](https://gdsfactory.github.io/kfactory/dev/schematics/crossing45/) —
  advanced hierarchical design with netlist verification and code generation

## See Also

| Topic | Where |
|-------|-------|
| Core netlist data model | [Concepts: Netlist Model](../concepts/netlist_model.py) |
| Equivalent ports | [Guides: Equivalent Ports](../guides/equivalent_ports.py) |
| Open detection | [Guides: Open Detection](../guides/open_detection.py) |
