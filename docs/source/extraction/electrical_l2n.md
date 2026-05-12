# Electrical Layout-to-Netlist

`l2n_elec()` builds a klayout `LayoutToNetlist` object from electrical port
markers. It handles the electrical side of netlist extraction, complementing the
geometric optical extraction.

## How it works

1. **Duplicate the layout** — works on a copy to avoid mutating the original
2. **Materialize port markers** — for each cell in the hierarchy, ports whose
   `port_type` is in `mark_port_types` are written as `kdb.Text` shapes on
   their respective layers
3. **Apply connectivity rules** — layers from the `connectivity` sequence are
   connected together in the L2N engine
4. **Extract** — klayout runs its built-in extraction and error checking

## Function signature

```python
def l2n_elec(
    cell: RootCellLike,
    mark_port_types: Iterable[str] = ("electrical", "RF", "DC"),
    connectivity: Sequence[Sequence[kdb.LayerInfo]] | None = None,
    port_mapping: Mapping[str, Mapping[str, str]] | None = None,
) -> kdb.LayoutToNetlist:
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `cell` | — | Root cell to extract from (protocol-typed) |
| `mark_port_types` | `("electrical", "RF", "DC")` | Port types to materialize as text markers |
| `connectivity` | `None` (uses `cell.kcl.connectivity`) | Layer connectivity rules |
| `port_mapping` | `None` | Remap port names before marking (used with equivalent ports) |

### Returns

A `kdb.LayoutToNetlist` object with the extracted electrical netlist.

## Port mapping

When `port_mapping` is provided, ports whose names appear in the mapping for
their cell are renamed before materialization. This collapses multiple
equivalent ports into a single canonical port name, preventing them from being
marked as separate electrical nodes.

## See Also

| Topic | Where |
|-------|-------|
| Optical extraction | [Optical Nets](optical_nets.md) |
| Full extraction pipeline | [Extraction Overview](overview.md) |
| Equivalent ports | [Guides: Equivalent Ports](../guides/equivalent_ports.py) |
