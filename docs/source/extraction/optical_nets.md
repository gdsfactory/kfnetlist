# Optical Net Extraction

`get_optical_nets()` extracts connectivity from geometric port adjacency in a
layout cell. Two ports that physically overlap at the same position, on the same
layer, and facing opposite directions are considered connected.

## How it works

1. **Bucket cell ports** by snapped `(x, y)` position and layer key
2. **Bucket instance ports** by their transformed `(x, y)` position and layer
   key (array instances are expanded element-by-element)
3. **Check candidate pairs** in neighboring buckets using `check_connection()`:
   - Cell-to-cell: requires `opposite` orientation
   - Cell-to-instance: requires `same` orientation (snapped)
   - Instance-to-instance: requires `opposite` orientation
4. Pairs passing the bitmask check become `Net` entries

## Bitmask checks

The required check is built from `PortCheck` flags:

```python
base_check = PortCheck.position + PortCheck.layer + PortCheck.port_type
if not allow_width_mismatch:
    base_check += PortCheck.width
```

## Function signature

```python
def get_optical_nets(
    cell: CellLike,
    port_types: Sequence[str] = ("optical",),
    *,
    allow_width_mismatch: bool = False,
) -> list[Net]:
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `cell` | — | Cell to extract from (protocol-typed) |
| `port_types` | `("optical",)` | Only consider ports whose `port_type` is in this sequence |
| `allow_width_mismatch` | `False` | If `True`, skip the width check in the bitmask |

### Returns

A `list[Net]` where each net connects exactly two port members (cell port or
instance port) that are geometrically adjacent.

## See Also

| Topic | Where |
|-------|-------|
| Port checking details | [Port Checking](port_checking.py) |
| Electrical extraction | [Electrical L2N](electrical_l2n.md) |
| Full extraction pipeline | [Extraction Overview](overview.md) |
