# Placement-Aware Netlist Flavor — Work Summary

## Goal
Add a new netlist flavor that carries **instance placement** (and the placed cell name) alongside connectivity, produced on demand from `extract()`. The existing `Netlist`/`NetlistInstance` types stay untouched; the new flavor is a true subclass.

## Design
Rust-native inheritance via PyO3 `#[pyclass(extends = ...)]`, mirroring the existing `PortArrayRef(PortRef)` pattern. Three new types:

| Type | Role |
|------|------|
| `Placement` | Purely **geometric** value object — *where* an instance sits: `x`, `y` (µm), `orientation` (deg), `mirror`, `bbox` (dict `{left,bottom,right,top}`, klayout convention) |
| `PlacedInstance(NetlistInstance)` | Adds `cell` (the layout cell name — distinct from `component`/factory name) and `placement`. Inherits all connectivity fields. |
| `PlacedNetlist(Netlist)` | Instances are `PlacedInstance`; exposes a `placements` map and a `from_netlist(nl, placements, cells)` upgrade classmethod. Inherits nets/ports/flatten/sort/LVS. |

Key decision: **`cell` is an instance property, not a placement property** — corrected after the first pass put it on `Placement`.

## Extraction
`extract(..., include_placement=False)`:
- **Off** → `dict[str, Netlist]`, byte-identical to before.
- **On** → `dict[str, PlacedNetlist]`. Connectivity is built/flattened/normalized/sorted on a plain `Netlist` exactly as today, then **upgraded** at the end — placement (`inst.dcplx_trans`, `inst.instance.dbbox()`) and cell name (`inst.cell.name`) attached only for surviving instances.

This post-processing-upgrade approach avoids keeping a parallel placement map consistent through every base mutation.

## Compatibility
- Base types changed only by a `subclass` capability flag — no new fields, no wire-format change. Verified by a backward-compat test.
- Placement is **excluded from equality**, so LVS comparisons are unaffected.
- `PlacedNetlist.create_inst` keeps the base parameter order (trailing optional `cell`/`placement`) → LSP-clean override (`ty` enforced).

## Files changed
| File | Change |
|------|--------|
| `src/placement.rs` | **New** — the three types, serde wire structs, upgrade/merge helpers |
| `src/lib.rs` | Register the three classes |
| `src/instance.rs`, `src/netlist.rs` | `subclass` flag; two methods made `pub(crate)`; `deep_clone` exposed |
| `src/kfnetlist/_native.pyi` | Type stubs for the new types |
| `src/kfnetlist/__init__.py` | Re-export `Placement`, `PlacedInstance`, `PlacedNetlist` |
| `src/kfnetlist/extract/_algo.py` | `include_placement` flag + `_placement_for` helper |
| `tests/test_placement.py` | **New** — 16 tests |
| `contributing/overview.md`, `contributing/extraction.md` | API tables, wire format, extraction section |
| `docs/source/guides/placement.py` + `docs/zensical.yml` | **New** executable guide + nav entry |

## Verification
- **131 tests pass** (16 new); example guide runs end-to-end.
- `ruff`, `rustfmt`, and `ty` all clean.
- Rust toolchain (rustup) installed in-container; native ext rebuilt via `maturin develop --release` and installed editable.

## Notes / follow-ups
- The end-to-end `extract(include_placement=True)` path is covered via the `_placement_for` helper (a full kfactory-shaped cell hierarchy isn't available in the test deps, consistent with the existing extraction tests).
- `orientation` is stored as float degrees (handles arbitrary/rotated placements); `bbox` is the transformed bbox in parent-cell µm coordinates.
