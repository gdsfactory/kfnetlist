# Changelog

## 0.1.5

- **L2N parsing** — `parse_l2n()` and `l2n_to_json()` convert a klayout
  `LayoutToNetlist` to a JSON-serializable dict (or string) with optional
  hierarchy flattening and layer/instance filtering
- **Geometric short detection** — `detect_shorts()` finds polygon overlaps
  between electrically distinct nets on the same layer; `shorts_to_rdb()` and
  `shorts_to_lyrdb()` convert results to KLayout Report Database format
- **Open detection** — `Netlist.detect_opens()` finds unconnected ports and
  singleton nets; `Netlist.find_open_nets(reference)` compares against a
  reference netlist to find missing nets
- **RDB filtering** — `include_from_rdb()`, `exclude_from_rdb()`, and
  `filter_rdb()` filter KLayout `ReportDatabase` objects by category path
  with dot-boundary prefix semantics; `_xml` variants operate on raw lyrdb
  XML strings via the Rust core
- **LvsError enum** — `StrEnum` with typed constants for all standard LVS
  error category paths (`LVS.short`, `LVS.open`, `LVS.net.*`, etc.)
- **Error summary** — `error_summary()` produces a Markdown table from a
  `ReportDatabase`

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
