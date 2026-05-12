# Changelog

## 0.1.0

Initial release.

- Rust-backed core types: `Netlist`, `Net`, `NetlistPort`, `PortRef`, `PortArrayRef`,
  `NetlistInstance`, `NetlistArray`
- Full JSON/dict serialization on all types
- Pydantic v2 integration (`__get_pydantic_core_schema__`)
- `Netlist.lvs_equivalent()` for folding electrically-equivalent ports
- `Netlist.flatten_instances()` for merging sub-cell instances
- `PortCheck` bitmask and `check_connection()` for geometric port comparison
- `kfnetlist.extract` subpackage for hierarchical netlist extraction from layout cells
