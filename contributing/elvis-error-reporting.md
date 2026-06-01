# Error Reporting in Elvis

This document describes how netlisting and LVS errors are defined, propagated, and reported across the Rust core, the `elvis-rdb` crate, and the Python interface.

## Architecture Overview

Error reporting flows through three layers:

```
┌──────────────────────────────────────────────────────────────────┐
│  Python (elvis package)                                          │
│  dict / rdb.ReportDatabase / bool / ValueError exceptions        │
├──────────────────────────────────────────────────────────────────┤
│  PyO3 FFI Boundary (elvis-python)                                │
│  ElvisError → PyValueError    LvsResult → JSON/YAML/lyrdb str    │
├──────────────────────────────────────────────────────────────────┤
│  Rust Core (elvis-core)                                          │
│  ElvisError (thiserror)       LvsResult (5 error vectors)        │
│                               LvsReport (serde-serializable)     │
│                               ReportDatabase (elvis-rdb)         │
├──────────────────────────────────────────────────────────────────┤
│  elvis-rdb                                                       │
│  KLayout lyrdb XML serialization with geometric markers          │
└──────────────────────────────────────────────────────────────────┘
```

There are two distinct error channels:

1. **Operational errors** — problems that prevent execution (bad file path, invalid JSON, missing cell). These use `Result<T, ElvisError>` in Rust and become `ValueError` in Python.
2. **LVS comparison errors** — mismatches found during verification. These are accumulated in `LvsResult` and returned as structured data (JSON dict, YAML, or KLayout RDB), never as exceptions.

---

## Operational Errors (`ElvisError`)

Defined in `crates/elvis-core/src/error.rs`:

```rust
#[derive(Error, Debug)]
pub enum ElvisError {
    GdsError(String),
    IoError(#[from] std::io::Error),
    MetadataParseError(String),
    CellNotFound(String),
    SerializationError(String),
    ParseError(String),
}

pub type Result<T> = std::result::Result<T, ElvisError>;
```

Each variant carries a descriptive string message. The `thiserror` `#[error(...)]` attribute generates the `Display` impl automatically (e.g. `"GDS file error: ..."`, `"Cell not found: ..."`).

### Propagation through Rust

Functions in `elvis-core` return `Result<T>` and propagate with `?`:

```rust
// crates/elvis-core/src/netlist/extractor.rs
pub fn extract_with_positions<P: AsRef<Path>>(...) -> Result<ExtractionResult> {
    let gds = GdsData::load(gds_path)?;
    let top_cell_name = gds
        .top_cell_name()
        .ok_or_else(|| ElvisError::CellNotFound("No cells found in GDS".to_string()))?;
    // ...
}
```

### Crossing the FFI boundary

In `crates/elvis-python/src/lib.rs`, every `ElvisError` is converted to `PyValueError` via `.map_err()`:

```rust
let netlist = elvis_core::extract_netlist_with_tolerance(gds_path, tolerance_nm)
    .map_err(|e| PyValueError::new_err(e.to_string()))?;
```

This pattern is applied uniformly — all Rust errors become Python `ValueError` with the original error message as the string payload. There are no custom Python exception classes for operational errors.

### Conservative netlist module

The conservative netlist module (`crates/elvis-core/conservative-netlist/`) uses `Result<T, String>` instead of `ElvisError`. Config validation collects all undeclared layers before returning:

```rust
// conservative-netlist/config.rs
pub fn validate(&self) -> Result<(), String> {
    // ... collect unknown layers ...
    Err(format!("connectivity references undeclared layers: {}", list.join(", ")))
}
```

---

## LVS Comparison Errors

LVS errors are not exceptions — they are structured data accumulated during comparison and returned to the caller.

### Error types

Defined in `crates/elvis-core/src/lvs/mod.rs`:

| Type | Variants | Meaning |
|------|----------|---------|
| `InstanceError` | `MissingInLayout`, `MissingInSchematic`, `ComponentMismatch` | Instance-level mismatches |
| `NetError` | `MissingInLayout`, `MissingInSchematic` | Connectivity mismatches (ports always length >= 2) |
| `PortError` | `MissingInLayout`, `MissingInSchematic`, `Mismatch` | Top-level port mismatches |
| `OpenError` | (struct) | Dangling/unconnected ports |
| `ShortError` | (struct) | Unexpected polygon overlaps between chains |

### LvsResult container

```rust
pub struct LvsResult {
    pub ok: bool,
    pub instance_errors: Vec<InstanceError>,
    pub net_errors: Vec<NetError>,
    pub port_errors: Vec<PortError>,
    pub open_errors: Vec<OpenError>,
    pub short_errors: Vec<ShortError>,
}
```

The `ok` field is `true` when all five vectors are empty.

### Error filtering and merging pipeline

Before errors are reported, they pass through several filtering stages (all in `lvs/mod.rs`):

1. **`filter_equivalent_ports()`** — suppresses errors for equivalent port groups
2. **`filter_equivalent_opens()`** — suppresses open errors when sibling ports are connected
3. **`filter_equivalent_nets()`** — suppresses net errors within equivalent groups
4. **`filter_schematic_shorts()`** — suppresses shorts explained by the schematic
5. **`merge_equivalent_port_net_errors()`** — groups errors by equivalence class
6. **`merge_into_nets()`** — collapses transitive electrical net errors via union-find

This pipeline reduces noise so users see meaningful mismatches rather than redundant pairs.

---

## Output Formats

LVS results can be serialized in three formats, selected by the `format` parameter.

### JSON / YAML (serializable report)

`LvsResult::to_report()` converts to `LvsReport`, a serde-serializable struct:

```rust
pub struct LvsReport {
    pub ok: bool,
    pub error_count: usize,
    pub instance_errors: Vec<InstanceErrorReport>,   // skipped if empty
    pub net_errors: Vec<NetErrorReport>,
    pub port_errors: Vec<PortErrorReport>,
    pub open_errors: Vec<OpenErrorReport>,
    pub short_errors: Vec<ShortErrorReport>,
}
```

Each `*Report` type has an `error_type` string field (e.g. `"missing_in_layout"`, `"component_mismatch"`) plus the relevant data flattened into optional fields. The `From<&ErrorType>` trait impls handle the conversion.

Example JSON output:

```json
{
  "ok": false,
  "error_count": 2,
  "instance_errors": [
    {
      "error_type": "missing_in_layout",
      "name": "mzi_1",
      "component": "mzi"
    }
  ],
  "net_errors": [
    {
      "error_type": "missing_in_schematic",
      "ports": ["splitter_1,o2", "combiner_1,o1"]
    }
  ]
}
```

### KLayout lyrdb (Report Database)

`LvsResult::to_rdb_with_positions()` converts errors into an `elvis_rdb::ReportDatabase`, which is then serialized to KLayout's lyrdb XML format via `to_lyrdb()`.

#### Category hierarchy

Errors are organized into a hierarchical category tree:

```
LVS
├── instance
│   ├── missing_in_layout
│   ├── missing_in_schematic
│   └── component_mismatch
├── net
│   ├── missing_in_layout
│   └── missing_in_schematic
├── port
│   ├── missing_in_layout
│   ├── missing_in_schematic
│   └── mismatch
├── open
└── short
```

#### Geometric markers

Each error `Item` carries geometric `Value` markers for visualization in KLayout's marker browser:

| Error type | Marker types |
|-----------|-------------|
| Instance errors | `Box` around instance ports or schematic placements |
| Net errors | `Edge` hub-and-spoke connecting port centroids |
| Port errors | `Point` at port coordinates |
| Open errors | `Box` around dangling ports |
| Short errors | `Polygon` for overlap regions |

Items can also carry a `comment` field for drill-down detail text shown in KLayout's marker browser detail pane.

---

## The `elvis-rdb` Crate

`crates/elvis-rdb/` is a standalone crate that handles KLayout Report Database serialization. It does not define error types itself — it provides the data model for representing and serializing error reports.

### Core types

| Type | Purpose |
|------|---------|
| `ReportDatabase` | Top-level container: description, generator, top cell, tags, categories, cells, items |
| `Category` | Hierarchical error grouping (name, description, subcategories) |
| `Item` | Single error: category path, cell, geometric values, optional tags/comment |
| `Value` | Geometric marker enum: `Text`, `Box`, `Polygon`, `Edge`, `Point` |
| `Tag` | Metadata tag attachable to items |
| `Cell` | Cell name declaration |

### Serialization

`ReportDatabase::to_lyrdb()` produces XML compatible with KLayout's marker browser. The `Point` variant is emitted as a tiny polygon (±0.001 micron square) since lyrdb has no native point element.

### RDB filtering

The crate also provides functions for filtering lyrdb XML by category path:

- `include_from_rdb(xml, paths)` — keep only items matching specified category paths
- `exclude_from_rdb(xml, paths)` — drop items matching specified paths
- `filter_rdb(xml, predicate)` — generic predicate-based filtering

Path matching uses dot-boundary prefix semantics: query `"LVS.net"` matches `"LVS.net.missing_in_layout"` but not `"LVS.netlist"`.

---

## Python Interface

### Entry points

| Function | Return type | Description |
|----------|-------------|-------------|
| `elvis.lvs()` | `dict[str, Any]` | Full LVS report as JSON dict |
| `elvis.lvs_ok()` | `bool` | Pass/fail boolean |
| `elvis.lvs_rdb()` | `klayout.rdb.ReportDatabase` | KLayout RDB object (requires `klayout` extra) |
| `elvis.extract_netlist()` | `dict[str, Any]` | Extracted netlist as dict |
| `elvis.error_summary()` | `str` | Markdown table from an RDB |

### Error handling pattern

**Operational errors** surface as `ValueError`:

```python
try:
    result = elvis.lvs("layout.gds", schematic)
except ValueError as e:
    print(f"LVS failed to run: {e}")
    # e.g. "GDS file error: ...", "Cell not found: ...",
    #       "Failed to parse schematic JSON: ..."
```

**LVS comparison errors** are returned in the dict, never raised:

```python
result = elvis.lvs("layout.gds", schematic)
if not result["ok"]:
    print(f"{result['error_count']} error(s)")
    for err in result["instance_errors"]:
        print(f"  {err['error_type']}: {err['name']} ({err.get('component', '')})")
    for err in result["net_errors"]:
        print(f"  {err['error_type']}: {' <-> '.join(err['ports'])}")
```

### LvsError enum

`python/elvis/_errors.py` defines a `StrEnum` mapping Python-friendly names to RDB category paths:

```python
class LvsError(StrEnum):
    INSTANCE_MISSING_IN_LAYOUT = "LVS.instance.missing_in_layout"
    INSTANCE_MISSING_IN_SCHEMATIC = "LVS.instance.missing_in_schematic"
    INSTANCE_COMPONENT_MISMATCH = "LVS.instance.component_mismatch"
    NET_MISSING_IN_LAYOUT = "LVS.net.missing_in_layout"
    NET_MISSING_IN_SCHEMATIC = "LVS.net.missing_in_schematic"
    PORT_MISSING_IN_LAYOUT = "LVS.port.missing_in_layout"
    PORT_MISSING_IN_SCHEMATIC = "LVS.port.missing_in_schematic"
    PORT_MISMATCH = "LVS.port.mismatch"
    OPEN = "LVS.open"
    SHORT = "LVS.short"
```

This enum is used for RDB filtering (e.g. `include_from_rdb(rdb, [LvsError.SHORT])`), not for raising exceptions.

### Error summary

`elvis.error_summary(rdb)` generates a markdown table from a KLayout `ReportDatabase`:

```
| cell     | error type                    | description             |
| -------- | ----------------------------- | ----------------------- |
| mzi_top  | LVS.instance.missing_in_layout| mzi_1 (component: mzi)  |
| mzi_top  | LVS.net.missing_in_schematic  | splitter_1,o2 <-> ...   |
```

### RDB filtering from Python

The Python layer wraps `elvis-rdb` filtering with KLayout RDB round-tripping:

```python
from elvis import lvs_rdb, include_from_rdb, LvsError

rdb = lvs_rdb("layout.gds", schematic, short_layers=[(1, 0)])
shorts_only = include_from_rdb(rdb, [LvsError.SHORT])
```

Internally this serializes the KLayout RDB to XML, calls the Rust filter, and reloads the result.

---

## CLI Error Reporting

The CLI (`crates/elvis-cli/`) prints a summary to stderr after LVS:

```
LVS FAILED: 5 error(s) (1 instance, 2 net, 0 port, 1 open, 1 short)
```

Or on success:

```
LVS PASSED
```

The full report goes to stdout (or a file via `--output`) in the requested format. The CLI exits with code 1 on LVS failure.

Warnings for invalid CLI arguments (e.g. malformed layer specs) are printed to stderr inline:

```
Warning: Invalid layer format 'bad', expected 'layer,datatype'
```

---

## Key File Reference

| File | Role |
|------|------|
| `crates/elvis-core/src/error.rs` | `ElvisError` enum (operational errors) |
| `crates/elvis-core/src/lvs/mod.rs` | LVS error types, comparison, filtering, merging, RDB conversion, report serialization |
| `crates/elvis-core/src/lvs/runner.rs` | LVS orchestration (`run_lvs`) |
| `crates/elvis-core/src/netlist/extractor.rs` | Netlist extraction with `Result<T, ElvisError>` |
| `crates/elvis-core/src/netlist/output.rs` | Netlist serialization (YAML/JSON) |
| `crates/elvis-core/conservative-netlist/config.rs` | Config validation with `Result<T, String>` |
| `crates/elvis-rdb/src/lib.rs` | RDB data model and lyrdb XML serialization |
| `crates/elvis-python/src/lib.rs` | PyO3 bindings, `ElvisError` → `PyValueError` |
| `crates/elvis-cli/src/lib.rs` | CLI output formatting and exit codes |
| `python/elvis/__init__.py` | Python API: `lvs()`, `lvs_ok()`, `lvs_rdb()` |
| `python/elvis/_errors.py` | `LvsError` StrEnum (category path constants) |
| `python/elvis/_summary.py` | `error_summary()` markdown table generator |
| `python/elvis/_rdb.py` | RDB filtering wrappers |
