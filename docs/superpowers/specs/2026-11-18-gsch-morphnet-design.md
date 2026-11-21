# Design + plan: `.gsch` (Mosaic/Livewire) in morphnet, with library headers and nyancad-parity export

## Context

gdsfactory+ saves schematics as `.gsch`, edited by Mosaic (electrical, the default editor) and Livewire (photonic). We want kfnetlist's morphnet to **parse `.gsch` and write it back** so these schematics flow through kfnetlist, and to **export SPICE/Spectre that runs the way nyancad's netlister output does**, with each used model's **library path (`.lib`/`.include`) at the top**. Everything must survive the kfnetlist bridge (`to_netlists` → manipulate → `from_netlists`): directives, model data and the editor layout.

Facts that shape the design:
- **`.gsch` is JSON** ("nyancir"): a flat `{key: entry}` map, entry kind by `type`. Schema: `gdsfactoryplus/crates/gfp-schematics/src/nyancir.rs`, spec `gdsfactoryplus/specs/nyancir_format.md`. The stdlib `json` module parses it; no Lark grammar.
- **The library path is not in `.gsch`.** It lives in `build/models.nyanlib` → `"models:<fqn>".models[]` (`implementation, language, name, spice-type, library, sections, port-order, params, code`).
- **Reference implementation for export:** `gdsfactoryplus/frontend/mosaic/python/nyancad/nyancad/netlist.py`.

| Concern | nyancad lines |
|---|---|
| Entry selection | 721-742 |
| Corner selection | 108-124 |
| Element mapping | 795-943 |
| Sources | 746-776, `_TRAN_PARAM_MAP` 241-273 |
| Params | `_eval_params` 276-307 |
| `GND` → `0` | 792 |
| Libraries / hierarchy | 996-1053 |
| Expected behaviour (tests) | `nyancad/tests/test_netlist.py` |

- **Morphnet today:**
  - It has `Directive(INCLUDE/LIB)`, and writers emit `netlist.directives` first.
  - Writers write instance names verbatim. `ExternalCircuit.properties["spice_prefix"]` is set but never read.
  - Non-numeric params are written as `0`.
  - Spectre drops LIB. Only a circuit named `__top__` is written flat. There is no `GND` → `0`.
- **The bridge today:**
  - `kfnetlist.Netlist` = instances + nets + ports only.
  - `convert.rs` keeps per-instance `__info__` and `__setting__<k>` JSON, but drops string settings from params (`convert.rs:33` ponytail).
  - It also drops circuit info, directives, ext circuits, non-`__` properties and editor net names.

## Goals
1. `parse_gsch` / `write_gsch`: both dialects in. Output that opens in **Livewire** and passes **Mosaic validation**. Lossless parse → write.
2. **Export parity with nyancad**: `parse_gsch(..., sim=, corners=)` followed by `write_spice`/`write_spectre` produces a circuit netlist equivalent to nyancad's `inspice_netlist` (same elements, nodes, models, params, library lines) for ngspice, Xyce and VACASK.
3. **A lossless bridge**: for any IR from `parse_gsch`, `from_netlists(to_netlists(nl))` gives the same `write_spice`, `write_spectre` and `write_gsch` output.

## Non-goals
- Simulator scaffolding nyancad gets from InSpice's `Simulation`: analyses, `.end`/`control` blocks, VACASK `load "*.osdi"` / `model sp_resistor` cards. That is the caller's job, as in gdsfactory+.
- Downloading http(s) libraries.
- Synthesising polylines or auto-layout.
- Writing directives into `.gsch`.
- Byte-identical text with nyancad (e.g. `R1` vs InSpice's `RR1`). Parity means the same circuit.

## Anti-goals
- A `.gsch` that Mosaic rejects. So no `net`/`subckt` entry types; every non-wire entry has `type`, `name`, `x`, `y`.
- Polylines in `{device, port}` form, which Livewire deletes. Keys ≠ `name`.
- Directives or info affecting `Netlist` equality. LVS stays header- and layout-agnostic, the same as placement.

## Approaches (picked: 1)
1. **Plain-JSON `gsch/` subpackage; sim semantics resolved at parse time into generic IR fields; existing writers taught those generic fields; bridge made lossless in Rust.** ← chosen
2. Lark JSON grammar. Rejected: more code, no gain.
3. Calling gdsfactory+'s Rust converter. Rejected: adds a gfp dependency and uses a polyline form Livewire deletes.
4. A separate `lower_for_sim()` pass after parsing. Rejected: the user wants `sim`/`corners` passed to the parser, and that keeps the IR one-per-sim.

User decisions so far:
- Livewire is the write target.
- The caller passes the simulator and corners.
- Directives are stored on `kfnetlist.Netlist`.
- Export is runnable like nyancad.
- Everything, including layout, survives the bridge.

---

## Phase 1 — Lossless bridge (Rust core + schema + bindings)

- **`crates/kfnetlist-core/src/netlist.rs`**:
  - New `Directive { kind: String, name: String, value: String }` (kind ∈ include|lib|global|option|param|define|timescale).
  - `Netlist` gains `directives: Vec<Directive>` and `info: serde_json::Map<String, Value>`.
  - Both also go on `NetlistWire` with `#[serde(default, skip_serializing_if = ...)]`, so existing JSON is unchanged.
  - Both are threaded through `to_wire`/`from_wire` and **excluded from `equals`**.
  - Flatten (`flatten.rs`, `src/kfnetlist/_flatten.py`) keeps the top's `info` and the **union of all directives, deduplicated, top first**.
- **`crates/kfnetlist-python/src/netlist.rs`**:
  - `directives` property: a fresh `list[dict[str,str]]` snapshot, with a setter that validates `kind`.
  - `info` property: a fresh dict snapshot plus a setter, mirroring `NetlistInstance.info` handling (`info_from_py`).
  - Update `_native.pyi`.
- **`crates/kfnetlist-schema/src/{document,convert}.rs`**:
  - `CircuitDocument.directives`. `to_netlist`/`from_netlist` copy `info` and `directives`; today `info` is dropped there.
  - String/bool settings ↔ `p::Parameter` with `properties["expr"]`, as an exact string. This resolves the `convert.rs:33` ponytail, so morphnet writers see them.
  - Non-reserved (`!startswith("__")`) `SubCircuit.properties` / `Circuit.properties` ↔ `info["__morphnet__"]["properties"]`.
  - Terminal `domain`/`direction` ↔ `info["__morphnet__"]["terminals"]`.
  - `Circuit.directives` ↔ `CircuitDocument.directives`.
  - Document level:
    - `p::Netlist.directives` ↔ the toplevel module's directives. With no toplevel, the last module is used, matching the morphnet convention. `to_proto_netlist` lifts the union of all modules' directives, deduplicated, top first.
    - `ext_circuits` and `libraries` ↔ the toplevel module's `info["__morphnet__"]`, as protobuf JSON.
  - Net names: keep the IR's `Connection.name` as the kfnetlist `Net` name instead of renaming to port name or `net_<i>`.
- `src/kfnetlist/morphnet/_bridge.py`: keep the built-in ext-circuit fill, but only when the restored document has none for that name.
- **Acceptance:** `tests/test_morphnet_bridge.py::test_bridge_lossless` runs every existing format fixture plus the gsch fixtures through `to_netlists` → `from_netlists` and gets identical writer output.

## Phase 2 — `.gsch` parse/write (`src/kfnetlist/morphnet/netlist/gsch/{__init__,parser,writer}.py`)

**`parse_gsch(text, *, models=None, sim="ngspice", corners=(), name=None) -> Netlist`**
- `models` is the parsed `models.nyanlib` dict; an inline `"models"` key is merged under it. `corners` is `str | Sequence[str]`.
- **Connectivity:** nodes are `(entry key, port)`, merged with a small dict union-find.
  - Mosaic `nets` maps. `polyline` terminals in all 3 PortRef forms. `type: "net"` `ports`. `via`/`taper` act as junctions.
  - The net name is the editor's: Mosaic net, else polyline `net`, else `net_<n>`.
  - Built with `net_utils.add_port_to_net` + `net_map_to_connections`.
- **Instances:** name = `name` or key.
  - The whole raw entry goes into `properties["__info__"]` as `{"gsch": entry, "model": fqn, ...}`, i.e. the bridge-carried slot.
  - Props go into `__setting__<k>` plus numeric/`expr` Parameters.
- **Top pins:** `port` entries with variant absent/emitter/detector, attached via `attached_port` else `nets.P`. Domain from `nature`.
- **Raw entries kept on the circuit:**
  - port entries and `wire`/`text` entries (so Mosaic wiring survives) → `Circuit.properties` / info `gsch_ports`, `gsch_wires`
  - polylines → `gsch_routes`
- **Domains:** device `ports[].port_type` → nyanlib port `type` → `domain_of(name)`.
- **Circuit name:** `name` arg, else the `schema:` key prefix, else `top`. The schema prefix is kept for `write_gsch`.

**`write_gsch(netlist) -> str`**: writes the top circuit.
- **Keys:** bare, equal to `name`.
- **Instances:** stash first, then overwrite `name`, `nets` (`connections_to_instance_nets`, with editor pin case restored from the stash or the Mosaic map), `props` and `model`.
  - `type`: from the stash, else the Mosaic symbol for built-ins (`mosfet` → `nmos`/`pmos` from the stash or `nmos`), else `ckt`.
  - `x`/`y`: from the stash, else a square grid with pitch 4.
- **Ports:** stash, or `{type:"port", name, x, y, nets:{P}, attached_port, nature}`.
- **Re-emitted from the stash:** wires/text, plus polylines whose endpoints still exist.
- **Known limit (`ponytail:`):** files written from non-gsch sources have no Mosaic wires. Mosaic recomputes `nets` on the first edit and loses them; Livewire keeps them.

## Phase 3 — nyancad-parity export

**At parse time**, for `sim`, in `parse_gsch`:
- **Model entry:** exact `implementation`, then the sim's native language (ngspice/xyce → spice, vacask → spectre), then a foreign library under VACASK.
- **Library directives:**
  - With a section: `LIB "path section"` (corner = first of `corners` present in `sections`, deterministic, else `sections[0]`). Without one: `INCLUDE`.
  - VACASK foreign libraries carry `lang` in `Directive.name`.
  - `code` blocks are written to no file. A `ponytail:` comment notes this: emit them as an INCLUDE of a temp file when needed.
  - Libraries are gathered over the whole hierarchy and deduplicated.
- **Built-ins** (nyancad 910-943):
  - Type mapping: resistor/capacitor/inductor/diode/vsource/isource as is; nmos/pmos → `mosfet`; npn/pnp → `bjt`.
  - Pins lower-cased to `DEVICE_PORT_TEMPLATES` (P/N → p/n, D G S B, C B E). A missing bulk goes to `0`.
  - Values: `resistance`/`capacitance`/`inductance` → `value`.
  - Sources: `DC x AC y` or `SIN(...)`/`PULSE(...)` via `_TRAN_PARAM_MAP` as a positional `value` expr.
  - Types not emitted by nyancad (led, photodiode, …, with no model) are skipped.
- **Model-backed devices:**
  - `spice-type` X/SUBCKT → instance of an `ExternalCircuit(name=entry.name, ports=port-order or sorted, spice_prefix="X")`.
  - D/M/Q → the primitive with `properties["model_name"]` (`m_`+lower for foreign VACASK).
  - R/C/L/V/I → the primitive.
  - `params` evaluated like `_eval_params` (textual substitution over model defaults + props; `{}` only for ngspice) → `expr`.
- **Ground:** `Netlist.properties["ground_net"]="GND"`.
- **Top circuit** named `__top__`, so it is written flat. Its schema name is kept for `write_gsch`.

**`read_gsch(path, *, project_root=None, models=None, sim=..., corners=...)`**
- Loads `models` from `project_root/build/models.nyanlib`, falling back to `project_root/models.nyanlib`.
- Follows child `model`s ending in `.gsch`, resolved against `project_root` as Livewire does, with cycle guard.
- Children become `Circuit`s whose ports are the child model's ports, sorted. The children's model params go on the header.

**Generic writer upgrades** (`spice/`, `spectre/` writers; hspice/xyce/spectre_spice inherit where they share code):
- `Parameter.properties["expr"]` is written verbatim, including a positional `value`.
- `spice_prefix` is honoured: the letter is prepended when the name does not already start with it (case-insensitive). X is used for calls to defined `Circuit`s.
- `properties["ground_net"]` → written as node `0`. Spectre also writes `ground 0` for VACASK-style output when set.
- SPICE subckt params go on the `.subckt` header line.
- Spectre:
  - `LIB` → `include "p" section=s [lang=..]`
  - parser/grammar `include ... section=` (`grammars/spectre.lark`, `spectre/transformer.py`)
  - R/C/L `value` → `r=`/`c=`/`l=`, V/I → `dc=`/`mag=`
  - lower-cased names for VACASK (driven by an IR flag `properties["dialect"]="vacask"`)

## Phase 4 — Wiring + docs
- `netlist/__init__.py` exports `parse_gsch`, `write_gsch`, `read_gsch`.
- The docs follow the SystemVerilog pattern from commit 3384117: `api-reference.md`, `index.md` table, `netlist_formats.py` extension table, `format_conversion.py`, changelog.
- Copy this design to `docs/superpowers/specs/2026-11-18-gsch-morphnet-design.md`.

## Reuse
- `net_utils.add_port_to_net`, `net_map_to_connections`, `connections_to_instance_nets`, `domain_of`
- `value_utils.parse_si_number`, `DEVICE_PORT_TEMPLATES`, `DEVICE_PREFIX_TO_CIRCUIT`, `format_si_value`
- `morphnet_schema` `Directive`/`DirectiveKind`/`ExternalCircuit`
- convert.rs `put`/`get` helpers
- export_spice.py X-prefix precedent

## Verification
- **Fixtures** in `tests/morphnet/netlists/gsch/`, copied from `gdsfactoryplus/tests/integration/refs` and `sdk/tests/fixtures`:
  - `ihp_rc_filter`, `ihp_cmos_inverter`, a hierarchical pair (`ihp_subckt_child`/`_parent`), `livewire_two_straights`, `spclo_gc2`
  - a trimmed `models.nyanlib` with library + sections, a VACASK entry and a foreign NgSpice lib
- **Phase 1:**
  - Rust `crates/kfnetlist-core/tests/model.rs`: wire JSON with and without the new fields, where old JSON is byte-identical; equality ignores them.
  - Rust `crates/kfnetlist-schema/tests/schema.rs`: string settings, properties, terminals, directives and ext circuits round-trip through proto.
  - Python `test_bridge_lossless`.
- **Phase 2:** `tests/morphnet/test_gsch_parser.py` and `test_gsch_writer.py`:
  - nets per fixture, domains, top pins (ground not exposed)
  - parse → write → parse is equal, and stashed `irl_*`/wires are kept
  - output from `parse_spice` uses only Mosaic types, has `x`/`y`/`name` everywhere, no `net`/`subckt` entries, and polylines only in the `component_id` form
- **Phase 3:** `tests/morphnet/test_gsch_export.py`.
  - For each fixture × {ngspice, xyce, vacask}, compare against **golden netlists generated once from nyancad** (`inspice_netlist`), normalised:
    - element set and node lists, with element-letter prefixes and case normalised
    - model names, params, library lines
  - The golden files are committed, so the tests don't depend on nyancad.
  - Corner selection: a list, the fallback to `sections[0]`, and multi-family.
  - `GND` → `0`. Hierarchy hoists child libraries.
  - If an `ngspice` binary is on PATH, run `ngspice -b` on the RC filter with an `.op` appended; skip otherwise.
- **Run:** `maturin develop --release && just test && just test-rust && just pre-commit`.
- **Manual:** open written `.gsch` files in the gdsfactory+ VS Code extension in Livewire and in Mosaic.

## Delivery
- Branch `dev/gsch-grammar` from `main`, created before any edits.
- Commit per phase via the `commit-commands` skill (per memory), not raw `git commit`. Leave the untracked `CLAUDE.md` alone.
- When all phases pass verification, push and open a **draft PR** to `main` with `gh pr create --draft` (the GitHub MCP server failed to connect; `gh` is the fallback).
  - The body summarises the phases, the "calls I made" list and the known limits.
  - Hand the PR URL to the user for review.

## Calls I made (check these)
1. **Directive format:** `kind` is a string in core, keeping core prost-free. Python sees `directives` as `list[dict]`, with no new pyclass.
2. **Bridge storage:**
   - Morphnet-only data rides in `info["__morphnet__"]`. Document-level `ext_circuits`/`libraries`/directives live on the toplevel module; with no toplevel, the last module is used.
   - Flatten and lift both take the union of directives across the hierarchy.
3. **Parse-time sim resolution:** one IR per sim, so re-parse to export for another simulator.
4. **What parity means:** the circuit netlist, not InSpice's simulation wrapper. Element letters are prepended only when missing (`R1`, not `RR1`).
5. **Corner choice:** when several match, the first corner in the caller's order (nyancad picks arbitrarily).
6. **Layout:** the raw `.gsch` entry is stashed for a lossless layout round trip; a grid is used otherwise.
7. **Mosaic wiring:** files written from scratch are Livewire-first, so Mosaic loses their `nets` on the first edit.
8. **Inline `code`:** deferred.
