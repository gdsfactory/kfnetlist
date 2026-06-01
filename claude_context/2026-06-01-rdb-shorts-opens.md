# Session: RDB, Short Detection, and Open Detection Implementation

**Date:** 2026-06-01  
**Branch:** `conservative-netlisting`

---

## What was done

Three major features were implemented in this session, closing gaps identified in `contributing/error-reporting-gap-analysis.md` against the Elvis error-reporting architecture (`contributing/elvis-error-reporting.md`).

---

### 1. RDB Module (KLayout Report Database)

Replicated the `elvis-rdb` crate interface inside kfnetlist.

#### Rust — `src/rdb.rs`

Full KLayout lyrdb XML data model and serialization, matching Elvis's `elvis-rdb` crate:

- **Types:** `ReportDatabase`, `Category`, `Item`, `Value` (Text/Box/Polygon/Edge/Point), `Tag`, `Cell`
- **Builder API:** `ReportDatabase::new()`, `.with_top_cell()`, `.add_category()`, `.add_cell()`, `.add_item()`; `Item::new()`, `.with_text()`, `.with_box()`, `.with_edge()`, `.with_point()`, `.with_polygon()`, `.with_comment()`, `.with_tag()`; `Category::new()`, `.with_description()`, `.with_subcategory()`
- **Serialization:** `ReportDatabase::to_lyrdb()` → KLayout-compatible lyrdb XML
- **Filtering:** `include_from_rdb(xml, paths)`, `exclude_from_rdb(xml, paths)`, `filter_rdb(xml, predicate)` — dot-boundary prefix matching (e.g., `"LVS.net"` matches `"LVS.net.missing_in_layout"` but NOT `"LVS.network"`)
- **10 Rust unit tests** covering serialization, value formats, filtering, prefix matching, edge cases

#### PyO3 bindings — `src/lib.rs`

Three filtering functions exposed on the `_native` module:
- `include_from_rdb(xml: str, paths: list[str]) -> str`
- `exclude_from_rdb(xml: str, paths: list[str]) -> str`
- `filter_rdb(xml: str, predicate: Callable[[str], bool]) -> str`

The `filter_rdb` predicate wrapper captures and re-raises Python exceptions.

#### Python modules

| File | Purpose |
|------|---------|
| `src/kfnetlist/_errors.py` | `LvsError` StrEnum — 10 category path constants (`LVS.instance.missing_in_layout`, `LVS.short`, etc.) |
| `src/kfnetlist/_rdb.py` | klayout `rdb.ReportDatabase` wrappers — `include_from_rdb()`, `exclude_from_rdb()`, `filter_rdb()` with XML round-trip through tempfiles |
| `src/kfnetlist/_summary.py` | `error_summary(rdb)` — markdown table generator from klayout RDB |
| `src/kfnetlist/__init__.py` | Updated — exports both XML-level (`*_xml`) and klayout-level functions, plus `LvsError` and `error_summary` |
| `src/kfnetlist/_native.pyi` | Updated — type stubs for the three new functions |

#### Tests — `tests/test_rdb.py`

14 Python tests: include/exclude exact, prefix, multiple, empty; filter with predicate and error propagation; dot-boundary semantics; LvsError enum values and integration with filtering.

---

### 2. Geometric Short Detection

#### `src/kfnetlist/extract/_shorts.py`

Detects polygon overlaps between different nets using klayout's native `Region &` boolean intersection:

- **`ShortResult`** dataclass — `net_a`, `net_b`, `layer`, `overlap` (kdb.Region)
- **`detect_shorts(l2n, *, short_layers, circuit_name)`** — iterates all nets per layer, computes pairwise region intersections, returns non-empty overlaps
- **`shorts_to_rdb(shorts, *, cell_name, dbu)`** — builds a klayout `rdb.ReportDatabase` with `LVS.short` category, text descriptions, and polygon markers
- **`shorts_to_lyrdb(shorts, *, cell_name, dbu)`** — serializes to lyrdb XML string via `shorts_to_rdb` + klayout save/load

Uses existing `_parser._discover_layer_regions()` and `_parser._layer_display_name()` helpers. Exported from `kfnetlist.extract.__init__`.

#### Tests — `tests/test_shorts.py`

13 tests:
- `detect_shorts`: no-short layouts, separated nets, bridge-merged nets, layer filtering, circuit parameter, nonexistent circuit
- `shorts_to_rdb`: empty, correct structure (category path, text values), polygon values
- `shorts_to_lyrdb`: valid XML, empty, klayout round-trip, Rust filtering integration

---

### 3. Open Detection

#### Rust — `src/netlist.rs`

Two new methods on `Netlist`:

- **`detect_opens()`** → Python dict:
  - `unconnected_ports`: sorted list of port names declared in `self.ports` but absent from all nets
  - `singleton_nets`: list of `Net` objects with exactly one member (dangling stubs)
- **`find_open_nets(reference)`** → list of `Net`:
  - Set difference `set(reference.nets) - set(self.nets)`
  - Uses `HashSet<&Net>` for O(n) lookup (Net already derives Hash + Eq)

Updated `src/kfnetlist/_native.pyi` with both signatures.

#### Tests — `tests/test_opens.py`

13 tests:
- `detect_opens`: unconnected port, all connected, no ports, singleton net, no singletons, multiple sorted, combined
- `find_open_nets`: identical, missing detected, extras not reported, empty reference, empty extracted, insertion-order independence

---

## Files changed

### New files
- `src/rdb.rs` — Rust RDB data model + lyrdb XML serialization + filtering
- `src/kfnetlist/_errors.py` — `LvsError` StrEnum
- `src/kfnetlist/_rdb.py` — klayout RDB filtering wrappers
- `src/kfnetlist/_summary.py` — `error_summary()` markdown table
- `src/kfnetlist/extract/_shorts.py` — geometric short detection
- `tests/test_rdb.py` — RDB module tests
- `tests/test_shorts.py` — short detection tests
- `tests/test_opens.py` — open detection tests

### Modified files
- `src/lib.rs` — added `mod rdb`, three `#[pyfunction]` filtering functions, registered on module
- `src/netlist.rs` — added `detect_opens()` and `find_open_nets()` methods
- `src/kfnetlist/__init__.py` — new exports (LvsError, filtering functions, error_summary)
- `src/kfnetlist/_native.pyi` — type stubs for new functions and methods
- `src/kfnetlist/extract/__init__.py` — exports ShortResult, detect_shorts, shorts_to_rdb, shorts_to_lyrdb

### Test results
- **10 Rust tests** — all pass
- **124 Python tests** — all pass (excluding pre-existing `test_group_nets` failures for unimplemented `group_nets()` and `test_port_check` which requires kfactory)

---

## Architecture decisions

1. **RDB types are Rust-only, not pyclasses.** The Python side uses klayout's native `rdb.ReportDatabase` for building reports and the Rust filtering functions operate on XML strings. This matches Elvis's architecture.

2. **Short detection uses klayout's Region boolean ops** rather than Rust-side polygon clipping (no `geo`/`rstar` dependencies). The L2N already has per-net shape data via `shapes_of_net()`.

3. **Open detection is in Rust on `Netlist`** because `Net` already has `Hash`/`Eq` making `HashSet` lookups efficient. The `find_open_nets(reference)` method implements the schematic-vs-extracted set difference.

4. **Generator string:** RDB uses `"kfnetlist"` instead of Elvis's `"elvis"`.

---

## What's next (from gap analysis)

| Gap | Status |
|-----|--------|
| RDB / lyrdb output | **Done** |
| Geometric short detection | **Done** |
| Open detection | **Done** |
| Named nets | Not started — prerequisite for meaningful short reporting |
| Structured operational errors (`KfNetlistError` enum) | Not started |
| Error accumulation (collect, don't throw) | Not started |
| Error filtering pipeline | Not started |
| `group_nets()` method | Tests exist, impl missing |
| Error summary / CLI | `error_summary()` done, CLI not started |
