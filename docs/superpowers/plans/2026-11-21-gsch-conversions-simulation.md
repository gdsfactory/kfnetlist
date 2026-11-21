# Lossless `.gsch` conversions with simulation protos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tests/morphnet/test_gsch_conversions.py` passes for all 11 fixtures × {ngspice, hspice, xyce, spectre, spectre_spice, verilog-a}, with source stimuli carried as `Simulation.stimuli` protos parsed natively by every grammar.

**Architecture:** shared value types move to `value.proto`; `simulation.proto` gains `Stimulus`/`Waveform`; one `netlist/stimulus.py` renders/reads each dialect's native source syntax; parsers and writers call it. Remaining loss sites (one-pin nets, `?`, top choice, Spectre `simulator lang`, Verilog-A grammar/writer) are fixed at their root.

**Tech Stack:** protobuf (prost + protoc pb2), pydantic mirror, lark grammars, Python 3.12+, Rust.

**Spec:** `docs/superpowers/specs/2026-11-21-gsch-conversions-simulation-design.md`

## Global Constraints
- The 30 nyancad goldens (`test_export_matches_nyancad`) stay green; normaliser unchanged.
- `test_export_survives_the_kfnetlist_bridge`, `test_bridge_lossless`, `test_json_matches_the_kfnetlist_schema` stay green.
- Proto enum values prefixed `WAVEFORM_KIND_`; `Simulation.stimuli = 7`; stimulus link `SubCircuit.properties["stimulus"] = "<circuit>/<instance>"`.
- Canonical waveform args (SPICE semantics, Spectre names): pulse `val0 val1 delay rise fall width period`; sin `sinedc ampl freq delay theta`; exp `val0 val1 delay tau1 td2 tau2`; sffm `sinedc ampl freq modindex modfreq`; pwl → `Waveform.points`.
- Verilog-A Table E.1: pulse `val0 val1 td rise fall width period`; sine `offset ampl freq td damp`; exp `val0 val1 td0 tau0 td1 tau1`; pwl `wave`; sffm → `vsine` `offset ampl freq fmmodindex fmmodfreq`; DC/AC-only → `vsine #(.dc(..), .mag(..), .phase(..))`.
- Open pin node name: `nc_<inst>_<pin>`.
- After Rust/grammar changes: `maturin develop --release`; touch `pyproject.toml` so `just test` rebuilds; `git add` new files.
- Commits through the `commit-commands:commit` skill.

## Review Focus
- A SPICE source with only `AC 1` (no DC) → stimulus `ac_magnitude=1`, `dc` unset; written back as `AC 1`, not `DC 0 AC 1`.
- A source whose value is an expression (`DC {vdd/2}`) keeps an `Expression`, in every dialect.
- A V/I element with no `stimulus` property (legacy IR with a `value` param) is still written as today.
- A stimulus inside a subcircuit (child `.gsch` with a source) survives hierarchy and the bridge.
- A genuine user net literally named `nc_X1_a` attached to `X1.a` only is dropped on re-parse (accepted; documented).

---

### Task 1: Schema — `value.proto`, `Stimulus`, `Waveform`

**Files:** Create `crates/kfnetlist-schema/proto/value.proto`, `src/kfnetlist/morphnet/morphnet_schema/_value.py`; modify `circuit.proto`, `simulation.proto`, `crates/kfnetlist-schema/build.rs`, `_circuit.py`, `_simulation.py`, `morphnet_schema/__init__.py`, regenerated `*_pb2.py/.pyi`; tests `tests/morphnet/test_circuit_models.py`, `crates/kfnetlist-schema/tests/schema.rs`.

**Interfaces — Produces:** pydantic `Stimulus(name: str, dc, ac_magnitude, ac_phase: ParameterValue | None, waveform: Waveform | None)`, `Waveform(kind: WaveformKind, args: dict[str, ParameterValue], points: list[ParameterValue])`, `WaveformKind`, `Simulation.stimuli: list[Stimulus]`; all exported from `kfnetlist.morphnet.morphnet_schema`.

- [ ] Write failing test `test_stimulus_json_matches_rust` in `test_circuit_models.py`: a `Netlist` with `simulation.stimuli=[Stimulus(name="__top__/V1", dc=num(0.9), waveform=Waveform(kind=PULSE, args={"val0": num(0), "val1": expr("vdd")}))]`; assert pydantic JSON == Rust JSON round trip (pattern of the existing JSON parity test) and `Netlist.from_json(nl.to_json()) == nl`.
- [ ] Run: `uv run --with . --with pydantic --extra dev pytest tests/morphnet/test_circuit_models.py -k stimulus` → FAIL (ImportError).
- [ ] Move the 10 value types to `value.proto`; `import "value.proto";` in both protos; add `Waveform`, `Stimulus`, `WaveformKind`, `Simulation.stimuli = 7`; add file to `build.rs` (`compile_protos` list + `rerun-if-changed`); `just compile-schema-py`; point `_circuit.py` value classes at `value_pb2` via new `_value.py` (move `_one_of`, `model_rebuild` block there).
- [ ] Add Rust test in `schema.rs` (`morphnet_only_fields_survive_kfnetlist` style): a stimulus + `properties["stimulus"]` survive `to_netlists` → `from_netlists`.
- [ ] Run `maturin develop --release && just test && just test-rust` → PASS. Commit "Add Stimulus and Waveform to the simulation schema".

### Task 2: `netlist/stimulus.py` — one module, every dialect

**Files:** Create `src/kfnetlist/morphnet/netlist/stimulus.py`, `tests/morphnet/test_stimulus.py`; move `TRAN`/`OMIT`/`waveform()` from `gsch/sim.py`.

**Interfaces — Produces:**
- `stimulus_of(netlist: Netlist, ref: SubCircuit) -> Stimulus | None`; `attach(netlist: Netlist, circuit: str, ref: SubCircuit, stim: Stimulus) -> None` (sets name, property, appends, creating `Simulation` if needed).
- `spice_text(stim: Stimulus, dialect: str, resolve=None) -> str` → `"DC 0.9 AC 1 PULSE(0 1.8 1n 10p 10p 1n 2n)"`; `parse_spice(tokens: list[str]) -> Stimulus` (tokens after the nets; `FUNC(args)` single tokens).
- `spectre_params(stim, dialect: str) -> list[tuple[str, str]]` (VACASK quirks only for `"vacask"`); `from_spectre(params: dict[str, ParameterValue | str]) -> Stimulus | None`.
- `primitive(stim, current: bool) -> tuple[str, list[tuple[str, str]]]` (`("vpulse", [("dc","0.9"), ("val0","0"), ("td","1n"), ...])`); `from_primitive(master: str, params: dict) -> Stimulus | None`.

- [ ] Write failing tests: parametrized round trip for each dialect × {DC only, AC only, DC+AC, PULSE, SIN, EXP, SFFM, PWL, an `Expression` arg}: `parse_spice(spice_text(s).split…) == s`, `from_spectre(dict(spectre_params(s, "spectre"))) == s`, `from_primitive(*primitive(s, False)) == s`; `spice_text` of the gsch inverter source == `"DC 0.9 AC 1"`; VACASK pulse with `delay=0` drops `delay`; exp `td2` rebased only for vacask.
- [ ] Run → FAIL. Implement. Run → PASS. Commit "Add one stimulus module for every source dialect".

### Task 3: gsch builds stimuli; SPICE and Spectre writers render them

**Files:** `gsch/sim.py` (`source()` returns a `Stimulus`), `gsch/parser.py` (attach; no `value`/`computed` for sources), `gsch/writer.py` (write `dc`/`ac`/`tran` props from the stimulus; drop source `check_derived`), `spice/writer.py`, `spectre/writer.py` (V/I via `stimulus.py`; legacy `value` path kept), tests in `test_gsch_export.py`.

- [ ] Failing tests: `read_gsch(ihp_hier_top)` has 3 stimuli, `V1` has `properties["stimulus"]=="__top__/V1"` and no `value` param; editing the stimulus `dc` and `write_gsch` writes the new `dc` prop.
- [ ] Implement; the gsch `sim` argument no longer changes sources (dialect quirks live in `spectre_params`).
- [ ] Run `pytest tests/morphnet/test_gsch_export.py tests/morphnet/test_gsch_writer.py tests/test_morphnet_bridge.py` → PASS, goldens unchanged. Commit.

### Task 4: SPICE-family grammars read sources and references

**Files:** `grammars/spice.lark`, `hspice.lark`, `xyce.lark` (add `FUNC_CALL: /[A-Za-z_]\w*\([^)]*\)/` to `token`; xyce/hspice also braced/quoted expression tokens), `spice/transformer.py` (V/I → `parse_spice` + attach; R/C/L lone ident → `Expression(reference)` unless a `.model` of that name is defined anywhere in the deck — collect model names before building subckts; top = `__top__` when top-level instances exist), `spectre_spice/parser.py:69` (same top rule), tests `test_spice_parser.py`, `test_xyce_parser.py`, `test_hspice_parser.py`.

- [ ] Failing tests: `V1 a 0 DC 0.9 AC 1 PULSE(0 1.8 1n 10p 10p 1n 2n)` → stimulus with those fields and no model `AC`; `R1 a b rload` → value `Expression(reference="rload")`; `R1 a b rmod` with `.model rmod r` → model; deck with `.subckt foo` + top elements → `top_circuit == "__top__"`; xyce `R1 a b {w*2}` → expression value.
- [ ] Implement; run spice/hspice/xyce/spectre_spice test files + `just test` → PASS. Commit.

### Task 5: One-pin nets and named open pins

**Files:** `net_utils.py` (`net_map_to_connections` emits source-only `Connection` for one-ref nets except those named `open_node(ref)`; add `open_node(inst: str, pin: str) -> str`), `gsch/parser.py:487-494` (drop its now-duplicate block), `spice/writer.py:219,255`, `spectre/writer.py:203` (`?` → `open_node`), `tests/morphnet/test_net_utils.py:37-42` (flip to the new behaviour).

- [ ] Failing tests: single-port net → one source-only connection; a net named `nc_X1_a` with only `X1.a` → none; writer output for `ihp_subckt_parent_nets` has `nc_A_S`, no `?`.
- [ ] Implement; `just test` → PASS. Commit.

### Task 6: Spectre reads stimuli and `simulator lang` sections

**Files:** `spectre/transformer.py` (vsource/isource params → `from_spectre` + attach; keep QSTRING text; top = `__top__` rule), `spectre/parser.py` (split `simulator lang=` sections, parse SPICE sections with `parse_spice` and merge — reuse `spectre_spice/preprocess.py` with initial language `spectre`), `tests/morphnet/test_spectre_parser.py`.

- [ ] Failing tests: `V1 (a 0) vsource dc=0.9 type=pulse val0=0 val1=1.8 period=2n` → stimulus; a file starting `simulator lang=spice` / `.subckt rdiv a b` / `simulator lang=spectre` / `X1 (in mid) rdiv` parses with circuits `rdiv` and `__top__`.
- [ ] Implement; `just test` → PASS. Commit.

### Task 7: Verilog-A reads and writes natively

**Files:** `grammars/vams.lark` (override values = shared expression grammar or a balanced-paren VALUE; `module m;` and `()` port lists; `(* name = "str", ... *)` attribute instances before `module` and module items; net initializer `electrical a = 5.0;`), `vams/transformer.py` (primitives → `from_primitive` + attach; attributes `spice_lib`/`spice_code` → LIB directives / macros; initializers → `Simulation.node_sets`; strip `\` from module types; top `__top__` rule), `vams/writer.py` (masters via `primitive()` for V/I; device master = `model_name or circuit_name`; escaped module/master names; `ground` from circuit or netlist `ground_net`; empty port list `module __top__;`; top-module attributes `(* spice_lib = "..." *)` (entries `\n`-joined) and `(* spice_code = "<json>" *)` for macros not in a Verilog language; node_sets as initializers), tests `test_vams_parser.py`, `test_vams_writer.py`.

- [ ] Failing tests: `vpulse #(.dc(0.9), .val0(0), .val1(1.8), .td(1n)) V1 (p, n);` → stimulus pulse `delay=1n`; `.l(0.13 * 1e-6)` → expression; `module t;` parses; writer for `ihp_hier_top` contains `Mprim #(`, `vsine #(.dc(1.8))`, `(* spice_lib = "ihp/models/ngspice/models/cornerMOSlv.lib mos_ff` and parse round-trips both libs; `electrical a = 5.0;` ↔ `node_sets`.
- [ ] Implement; `just test` → PASS. Commit.

### Task 8: SystemVerilog shares the primitives

**Files:** `grammars/systemverilog.lark` / `systemverilog/transformer.py` (primitive masters → stimulus), `systemverilog/writer.py` (V/I via `primitive()`), `tests/morphnet/test_systemverilog_writer.py`.

- [ ] Failing test: SV write → parse of a netlist with a pulse stimulus keeps it. Implement; `just test` → PASS. Commit.

### Task 9: Acceptance test, docs, PR

**Files:** `tests/morphnet/test_gsch_conversions.py` (view adds per-element `stimulus`; master = `model_name or circuit_name`), `docs/source/changelog.md`, `docs/source/morphnet/api-reference.md` (Stimulus, native constructs table, open-node rule), PR #37 body.

- [ ] Run `pytest tests/morphnet/test_gsch_conversions.py` → 67 passed. `just test && just test-rust && just pre-commit` → green.
- [ ] Commit; push; `gh pr checks 37 --watch` → all green.
