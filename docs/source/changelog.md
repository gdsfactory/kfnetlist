# Changelog

## Unreleased

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
