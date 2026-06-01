# Error Reporting & Short Detection — Gap Analysis

This document compares kfnetlist's current error/diagnostic infrastructure against the elvis error reporting architecture (see [elvis-error-reporting.md](elvis-error-reporting.md)) and proposes an implementation roadmap.

---

## Current State of kfnetlist

kfnetlist is a high-performance netlist data model (Rust core + PyO3 Python bindings) that handles serialization, hierarchical composition, port equivalence folding, and extraction. Its error surface today is minimal:

| Area | What exists | Where |
|------|-------------|-------|
| Operational errors | Bare `PyValueError` / `PyKeyError` / `PyTypeError` | `src/netlist.rs:180-255`, `src/net.rs:49` |
| Validation | Array bounds, unknown instance/port at net creation time | `src/netlist.rs:create_net()`, `create_inst()` |
| Extraction errors | klayout's `check_extraction_errors()` (opaque) | `src/kfnetlist/extract/_l2n.py:112` |
| Diagnostics | None — no structured output, no accumulation, no filtering | — |

---

## What Elvis Has That kfnetlist Does Not

### 1. Named Nets

**Elvis:** Every net carries a name derived from the schematic or layout extraction.

**kfnetlist:** `Net` (`src/net.rs:62-64`) is anonymous — a sorted `Vec<NetMember>` with no `name` field. KLayout's `kdb.Net.name` is captured during L2N parsing (`src/kfnetlist/extract/_parser.py:99`) but **discarded** when data enters the Rust `Netlist` model via `_build_cell_netlist()`.

**Impact:** Without named nets, shorts cannot be meaningfully reported ("net X is shorted to net Y"). This is the single most critical prerequisite.

### 2. Short Detection

**Elvis:** `ShortError` struct — pairs of net names + `Polygon` overlap regions. Detected via polygon intersection between chains on the same layer.

**kfnetlist:** No short detection exists. The discussion in `.claude/netlist-shorts-discussion.md` proposed a member-set intersection approach (two nets sharing `NetMember` elements) but no code was written.

**Two levels of short detection are possible:**

| Level | Mechanism | Data required |
|-------|-----------|---------------|
| **Topological** | Two nets sharing the same `NetMember` (same port connected to two different named nets) | Named nets only |
| **Geometric** | Polygon overlap between shapes belonging to different nets on the same layer | Per-net layer shapes (already parsed in `_parser.py:104-125` but not fed into Rust model) |

### 3. Open Detection

**Elvis:** `OpenError` struct — dangling/unconnected ports (declared but not wired to any net, or nets with only one member).

**kfnetlist:** No open detection. The information is available (top-level `ports` vs members appearing in `nets`) but no code computes the difference.

**Three classes of opens:**

| Class | Description | Detection |
|-------|-------------|-----------|
| **Unconnected top-level port** | Port in `Netlist.ports` that appears in zero nets | Set difference: `{p.name for p in ports}` minus `{m.name for m in net_members if isinstance(m, NetlistPort)}` |
| **Dangling instance port** | Instance port referenced in exactly one net (stub) | Net with a single member, or an instance port never appearing in any net |
| **Singleton net** | Net with only one member after flattening | `len(net) == 1` |

### 4. Structured Error Types

**Elvis:** A `thiserror`-derived `ElvisError` enum for operational errors, plus five LVS error structs (`InstanceError`, `NetError`, `PortError`, `OpenError`, `ShortError`) accumulated in an `LvsResult` container.

**kfnetlist:** All errors are ad-hoc `PyValueError::new_err(format!(...))` strings. No enum, no structured error data, no separation between operational and diagnostic errors.

### 5. Error Accumulation (Collect, Don't Throw)

**Elvis:** LVS comparison errors are **never** thrown as exceptions. They are accumulated in `LvsResult.{instance_errors, net_errors, ...}` and returned as structured data (JSON dict / YAML / lyrdb XML). This allows the caller to inspect, filter, and present errors.

**kfnetlist:** Every validation error is thrown immediately, halting execution. There is no mechanism to collect multiple issues and return them together.

### 6. Error Filtering and Merging Pipeline

**Elvis** has a 6-stage pipeline applied to raw LVS errors before reporting:

1. `filter_equivalent_ports()` — suppress errors for equivalent port groups
2. `filter_equivalent_opens()` — suppress opens when sibling ports are connected
3. `filter_equivalent_nets()` — suppress net errors within equivalence classes
4. `filter_schematic_shorts()` — suppress shorts explained by the schematic
5. `merge_equivalent_port_net_errors()` — group by equivalence class
6. `merge_into_nets()` — collapse transitive errors via union-find

**kfnetlist:** `lvs_equivalent()` (`src/netlist.rs:329-481`) performs port-label canonicalization and net merging via union-find, which is analogous to stages 1, 5, and 6. But it operates on the netlist itself (rewriting it), not on a separate error stream. There is no error-specific filtering.

### 7. Geometric Error Markers / RDB Output

**Elvis:** Errors carry geometric `Value` markers (`Box`, `Edge`, `Point`, `Polygon`) serialized to KLayout's lyrdb XML via the `elvis-rdb` crate. Users visualize errors in KLayout's marker browser.

**kfnetlist:** No geometric marker infrastructure. The L2N parser *does* extract per-net polygon shapes (`_parser.py:104-125`), but these stay in the JSON dict and never reach the Rust model or any error-reporting path.

### 8. Error Summary and CLI Reporting

**Elvis:** `error_summary(rdb)` produces a markdown table; the CLI prints a one-line summary to stderr (`LVS FAILED: 5 error(s) (1 instance, 2 net, ...)`).

**kfnetlist:** No summary, no CLI, no formatted output of any kind.

---

## Features In Progress (Partially Implemented)

### `group_nets()` Method

Tests exist (`tests/test_group_nets.py`) for a `Netlist.group_nets(equivalent_ports=...)` method that:
- Merges nets whose top-level ports belong to the same equivalence group
- Removes non-canonical ports from the output
- Returns a new `Netlist` (non-mutating)
- Preserves untouched nets

This method **does not yet exist** in the Rust code (`src/netlist.rs`). It is related to but distinct from `lvs_equivalent()` — `group_nets` operates at the top-level port layer only, while `lvs_equivalent` also rewrites instance port references.

---

## Proposed Implementation Roadmap

### Phase 1 — Named Nets and Topological Short Detection

**Goal:** Give nets identity so shorts can be reported.

#### 1a. Add `name: Option<String>` to `Net`

```rust
// src/net.rs
pub struct Net {
    pub(crate) name: Option<String>,   // NEW
    pub(crate) members: Vec<NetMember>,
}
```

- Serde: serialize as `{"name": "VDD", "members": [...]}` (currently `transparent`, will need a struct format or a custom Serialize)
- Python: expose as `net.name` (read/write property)
- Construction: `Net([...])` keeps `name=None`; `Net([...], name="VDD")` sets it
- Backward compatibility: JSON without `name` deserializes to `None` (use `#[serde(default)]`)

#### 1b. Carry names from L2N extraction

In `_build_cell_netlist()` (`src/kfnetlist/extract/_algo.py:174`), after `elec_circ.each_net()`, the `kdb.Net.name` is available but currently unused. Propagate it:

```python
# _algo.py, inside the electrical net walk
net_name = net.name if net.name else None
# ... build net_refs ...
if len(net_refs) > 1:
    new_net = Net(net_refs)
    new_net.name = net_name  # NEW
    nl.add_net(new_net)
```

#### 1c. Topological short detection

Add a `detect_shorts()` method on `Netlist` (Rust side):

```rust
pub struct NetlistShort {
    pub net_a: String,       // name of first net
    pub net_b: String,       // name of second net
    pub shared: Vec<NetMember>, // members present in both
}
```

Algorithm: build `HashMap<NetMember, Vec<usize>>` mapping each member to the net indices containing it. Any member appearing in 2+ named nets constitutes a short.

### Phase 2 — Open Detection

#### 2a. Unconnected port detection

```rust
impl Netlist {
    pub fn detect_opens(&self) -> Vec<NetlistOpen> { ... }
}

pub struct NetlistOpen {
    pub kind: OpenKind,      // UnconnectedPort, DanglingInstancePort, SingletonNet
    pub member: NetMember,   // the unconnected member
    pub net_name: Option<String>, // if it's a singleton in a named net
}
```

#### 2b. Integration with extraction

Run `detect_opens()` after `_build_cell_netlist()` returns, before or after `lvs_equivalent()`.

### Phase 3 — Structured Error Types and Accumulation

#### 3a. Operational error enum

```rust
// src/error.rs (new file)
#[derive(Error, Debug)]
pub enum KfNetlistError {
    #[error("Unknown instance: {0}")]
    UnknownInstance(String),
    #[error("Array bounds exceeded: instance {instance}, ia={ia}, ib={ib}")]
    ArrayBoundsExceeded { instance: String, ia: i64, ib: i64 },
    #[error("Undefined port: {0}")]
    UndefinedPort(String),
    #[error("Serialization error: {0}")]
    SerializationError(String),
    #[error("Parse error: {0}")]
    ParseError(String),
}
```

Replace the scattered `PyValueError::new_err(format!(...))` calls in `netlist.rs` with this enum, converting at the FFI boundary (like elvis does).

#### 3b. Diagnostic result container

```rust
pub struct DiagnosticResult {
    pub shorts: Vec<NetlistShort>,
    pub opens: Vec<NetlistOpen>,
}
```

Returned by a `Netlist.validate()` or `Netlist.diagnostics()` method — never thrown as exceptions.

### Phase 4 — Geometric Short Regions

#### 4a. Per-net shape storage

Extend `Net` (or a parallel structure) to carry per-layer polygon data. The L2N parser already extracts this (`_parser.py:104-125`) — thread it through to the Rust model.

#### 4b. Polygon intersection for short regions

Given two nets with overlapping members, compute the geometric intersection of their shapes on shared layers. This yields the physical region of the short, analogous to elvis's `ShortError` with `Polygon` markers.

Without short regions, a detected short tells the user *that* something is wrong but not *where* in the layout. For real designs with thousands of nets, an unlocatable short is effectively useless. This phase should use klayout's built-in `Region` boolean operations (`&` operator) rather than reimplementing polygon clipping in Rust — klayout's geometry engine is well-tested and already a dependency of the extraction path.

### Phase 5 — Output Formats, RDB, and Reporting

These are not optional — they are the primary way users consume error data. Detection without structured output has no practical value.

#### 5a. Serializable report struct

```rust
pub struct DiagnosticReport {
    pub ok: bool,
    pub short_count: usize,
    pub open_count: usize,
    pub shorts: Vec<ShortReport>,
    pub opens: Vec<OpenReport>,
}
```

With `serde::Serialize` for JSON/YAML output.

#### 5b. KLayout RDB output

Serialize detected errors (with geometric regions from Phase 4) to KLayout's lyrdb XML format for visualization in the marker browser. This is the primary debugging workflow for layout engineers — the marker browser is how they locate and understand errors spatially.

Implementation options:
- **Python-side** (`_rdb.py` helper): construct `klayout.rdb.ReportDatabase` directly, leveraging klayout's own RDB API. Simpler, no new Rust crate needed, directly mirrors elvis's Python `_rdb.py` wrapper.
- **Rust-side** (standalone crate like `elvis-rdb`): full control over XML serialization, usable from CLI without Python. Higher upfront cost but decoupled from klayout runtime.

Recommendation: start with the Python-side approach (lower friction, klayout is already required for extraction), and extract to a Rust crate later if CLI or non-Python consumers emerge.

#### 5c. Error summary

A `diagnostic_summary()` function producing a markdown table (like elvis's `error_summary()`), plus a one-line stderr summary for CI integration:

```
NETLIST CHECK FAILED: 3 error(s) (2 short, 1 open)
```

#### 5d. Error filtering pipeline

Before reporting, raw errors must pass through filtering/merging stages to avoid flooding the user with redundant entries:

1. **Filter equivalent port shorts** — suppress shorts between ports in the same equivalence group (they are intentional)
2. **Filter singleton opens** — suppress opens on ports that are intentionally unconnected (e.g. NC pins, if declared)
3. **Merge transitive shorts** — if net A is shorted to B, and B to C, report one short group {A, B, C} rather than two pairs
4. **Deduplicate by region** — multiple member-level shorts mapping to the same physical polygon should be collapsed

Without this pipeline, a single routing short on a power rail can generate hundreds of raw errors (one per member overlap). The pipeline is what makes error output usable.

---

## Summary of Gaps

| Capability | Elvis | kfnetlist | Priority |
|-----------|-------|-----------|----------|
| Named nets | Yes | **No** | **P0** — prerequisite for everything |
| Topological short detection | Yes (member overlap) | **No** | **P0** |
| Geometric short regions | Yes (polygon intersection) | **No** (data available in parser) | **P0** — without regions, shorts are unlocatable |
| Open detection | Yes | **No** | P1 |
| Structured operational errors | `ElvisError` enum | Ad-hoc `PyValueError` strings | P1 |
| Error accumulation | `LvsResult` container | Throw-on-first-error | **P0** — errors must be collected, not thrown |
| Error filtering pipeline | 6-stage pipeline | Partial (union-find in `lvs_equivalent`) | **P0** — raw error lists are unusable without deduplication |
| RDB / geometric markers | `elvis-rdb` crate | **No** | **P0** — KLayout visualization is the primary consumer |
| Error summary / CLI | `error_summary()` + CLI | **No** | **P0** — structured output is how users consume results |
| `group_nets()` method | N/A | Tests written, impl missing | **P0** |

---

## Design Decisions Still Open

1. **Eager vs. lazy short detection** — Should shorts be checked on every `create_net()` / `add_net()` call (eager), or only when `detect_shorts()` / `validate()` is explicitly called (lazy)? Lazy is simpler and avoids performance overhead during construction, but eager catches issues immediately.

2. **Net naming strategy** — Should *all* nets be named (auto-generating names for unnamed optical nets), or should only nets with explicit names from L2N extraction carry names? Auto-naming is noisy; explicit-only means optical-only shorts are invisible.

3. **Where does short detection live** — Rust side (fast, available from Python via PyO3) or Python side (simpler, can use klayout's `Region` boolean ops for geometric shorts)? Topological shorts are trivial in Rust; geometric shorts may need klayout.

4. **Diagnostic result shape** — Flat list of errors (like elvis's `LvsResult`) or per-net annotation? The flat list is simpler for filtering and serialization.

5. **Backward compatibility of `Net` serialization** — Adding a `name` field changes the JSON shape. Should we use `#[serde(default)]` for reading old JSON, or version the format?
