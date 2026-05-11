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
    ├── gather LVS-equivalent ports from cell/factory metadata
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
        └── apply lvs_equivalent() if equivalent ports defined
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
| [`check_connection`](port_checking.py) | Port-pair comparison bitmask |

## See Also

| Topic | Where |
|-------|-------|
| Core netlist data model | [Concepts: Netlist Model](../concepts/netlist_model.py) |
| LVS equivalence | [Guides: LVS Equivalence](../guides/lvs_equivalence.py) |
