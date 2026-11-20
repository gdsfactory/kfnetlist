# Plan: close the .gsch ↔ kfnetlist integration gaps (follow-up on PR #37)

## Context
PR #37 (`dev/gsch-grammar`, draft, CI green) adds `.gsch` read/write to morphnet. The review report listed the gaps below. The user's ruling on each:

| # | Gap | Ruling |
|---|---|---|
| 4 | `write_gsch` silently drops edits to model-derived params | **Fix**: structured `Expression` in the schema, reaching gsch and all SPICE-family parsers/writers |
| 7 | nyanlib inline `code` blocks are not written | **Fix**: a new `Macro` message |
| 14 | Buses and `__` properties are lost by the bridge | **Fix** |
| 15 | A net named like its port loses the name (YAML + bridge) | **Fix**, targeted |
| 16 | A malformed `__morphnet__` is ignored silently | **Fix**: raise |
| 18 | The header is copied onto every cell | **Report only** (numbers below) |
| 12 | `Terminal{id}` naming convention | **Skip for now** → GitHub issue |
| 5, 9 | Mosaic wire sync; unknown model types called as `X` | **GitHub issues** |
| 2 | Opening the files in the real editors | User does it at gdsfactory+ integration |
| 6, 8, 10 | — | Accepted as is; keep SI `M`/`meg` strictness |

All GitHub issues are assigned to **das-dias** (`gh api user` confirmed the login).

**Branch (my call):** keep working on `dev/gsch-grammar`. The `properties["expr"]` format that #4 replaces exists only in this unmerged PR. Fixing it here means no throwaway format ships and no migration is needed.

## What exploration found (drives the design)
- **No expression or macro type in the schema.**
  - `Parameter.default_value` is a oneof of `PrefixedValue` or `ModelReference` (`crates/kfnetlist-schema/proto/circuit.proto:75-94`).
  - Expressions live in `properties["expr"]`, which this PR introduced: written at `gsch/parser.py:118` and `systemverilog/transformer.py:199`, read by `value_utils.param_text:72` and `gsch/writer.py:67`.
  - The only macro-like construct is `DIRECTIVE_KIND_DEFINE` (`circuit.proto:60-69`).
- **The SPICE-family parsers drop expressions to an empty `ParameterValue()`:**
  - spice `{}`/quotes: `spice.lark:143-145`, `spice/transformer.py:190-194`
  - xyce `BRACE_EXPR`: `xyce/transformer.py:23`
  - spectre: `spectre/transformer.py:144-148`
  - hspice quotes: `hspice/transformer.py:27`
  - SystemVerilog is the only grammar with real expressions (`systemverilog.lark:84-102`).
- **Why #4 happens.**
  - The gsch IR holds only the substituted simulation view: `w={0.15*1e-6*2}`.
  - The real source props live in the stash, and the writer skips params listed in `stash["derived"]` (`gsch/writer.py:293-312`). Source props such as `W` cannot be edited in kfnetlist at all.
  - nyancad's `_eval_params` (`nyancad/netlist.py:276-307`) is pure textual substitution.
- **nyancad and `code`:** it injects the block as SPICE, parsing it first and falling back to raw text (`nyancad/netlist.py:1050-1108`).
- **Why #14 happens.**
  - `public()` (`convert.rs:23-29`) keeps only `__order__` on subcircuit, connection and circuit properties.
  - `Circuit.buses` (`circuit.proto:149-155,181`) becomes unnamed nets on read (`convert.rs:545-561`) and is never set on write (`:439-449`).
  - Port buses already survive (`Terminal.width` plus `range`, stashed whole).
- **Why #15 happens.** `document.rs:281-285` folds a net named like its port into the `ports` form, which has no name, and `to_netlist` rebuilds it unnamed (`:238-246`). The YAML route and `to_netlists(from_netlists())` both lose the name, e.g. `inverter`: `['in_','out','vss']` → `['out',None,None]`.
- **Why #16 happens.**
  - `Stash::take` (`convert.rs:70-73`) turns a non-object into `Stash::default()` and deletes it from `info`.
  - `_bridge.py:87` skips it.
  - The result is a lost header, class names, terminals and params, a redeclared built-in, and no warning.
- **#18 measurements** (report and issue only):

  | Fixture | Header per cell | Header / total JSON |
  |---|---|---|
  | `gsch/ihp_hier_top` | 4554 B | 9108 / 18746 B (49%) |
  | `hspice/hierarchical_subckt` | 487 B (343 B is the `resistor` ext) | 26% |
  | `gsch/ihp_subckt_parent_nets` | 694 B | 27% |

  About 140 B per cell is empty fields.

## Design

### A. `Expression` in the schema (#4)
`circuit.proto`:
```proto
enum Operator { OPERATOR_UNSPECIFIED=0; ADD=1; SUB=2; MUL=3; DIV=4; POW=5; MOD=6;
                NEG=7; NOT=8; EQ=9; NE=10; LT=11; LE=12; GT=13; GE=14; AND=15; OR=16; }
message UnaryOp   { Operator op = 1; Expression operand = 2; }
message BinaryOp  { Operator op = 1; Expression lhs = 2; Expression rhs = 3; }
message Call      { string name = 1; repeated Expression args = 2; }
message Ternary   { Expression cond = 1; Expression then = 2; Expression otherwise = 3; }
message Expression { oneof node {
    PrefixedValue literal = 1; string reference = 2; UnaryOp unary = 3;
    BinaryOp binary = 4; Call call = 5; Ternary ternary = 6;
    string raw = 7;            // dialect text no grammar parsed (kept verbatim)
} }
// ParameterValue.oneof value += Expression expression = 3;
```
Enum value names follow the proto's prefixing convention (`OPERATOR_ADD`, …). `PrefixedValue` literals keep the SI-suffix form, so `2.2u` stays `2.2, MICRO`.

- **Python:**
  - New `morphnet/netlist/expression.py`:
    - `parse_expression(text) -> Expression` uses a shared `grammars/expression.lark`, extracted from the SV expression rules. On failure it falls back to `raw`.
    - `format_expression(expr, dialect, resolve=None)`.
  - Dialect wrapping: ngspice/xyce `{}`, hspice `'…'`, spectre/vacask/SV/VAMS bare. The `**` vs `pow()` operator table is the builder's call.
  - `value_utils.param_text` prints expressions through it.
  - Every `properties["expr"]` read and write goes away.
  - Pydantic mirror in `morphnet_schema/_circuit.py`.
  - `just compile-schema-py`; prost regenerates through `build.rs`.
- **Parsers:**
  - spice/hspice `{}`/quoted, xyce `{}`, spectre bare expressions, SV and gsch all produce `Expression`.
  - Plain numbers stay `prefixed_value`.
- **gsch write-back, the real #4 fix:**
  - The parser puts the instance's source props into the IR as Parameters with `properties["role"]="source"`, e.g. `W`.
  - Model-derived params become an `Expression` over `reference`s to them, unsubstituted: `w = W*2`.
  - SPICE and Spectre writers do not emit `role=source` params.
  - When printing, writers resolve a `reference` that names an instance-local source param to its value. This reproduces nyancad's substitution, so **the golden netlists stay byte-identical**.
  - `write_gsch` writes source params back to `props`, so an edit to `W` reaches both the `.gsch` and the SPICE output.
  - A derived param edited away from its expression raises `ValueError` naming the source props to edit instead; it is no longer silently dropped.
  - The `stash["derived"]` mechanism is removed.
- **Bridge:**
  - `convert.rs` gets a small Rust printer (canonical text) so an expression param shows as a readable kfnetlist setting string.
  - The AST rides in the parameter stash.
  - Reverse direction: text equal to the printed stash restores the AST; edited text becomes `Expression{raw}`.
  - `_bridge.py` then runs `parse_expression` on `raw` leaves, so edits come back structured.

### B. `Macro` in the schema (#7)
```proto
message Macro { string name = 1; string language = 2; string body = 3; map<string,string> properties = 4; }
// Circuit.macros (repeated, next free field), Netlist.macros (repeated)
```
- **gsch:** `sim.library()` reads `entry["code"]` and emits `Macro(name=entry name, language=entry language, body=code)` on the Netlist. Macros are gathered across the hierarchy and deduplicated by name, like libraries. The `ponytail:` comment at `sim.py:115` goes.
- **Writers** emit `body` verbatim after the directives when `language` matches the dialect family:
  - SPICE family: `spice`/`ngspice`/`xyce`.
  - Spectre: `spectre`, plus SPICE bodies wrapped in `simulator lang=spice` / `simulator lang=spectre`.
  - Otherwise: a `// skipped macro <name> (<language>)` comment plus `warnings.warn`, never a silent drop.
  - VACASK falls under "otherwise" (builder's call: it has no `simulator lang` switch).
- **Bridge (my call):** macros ride the `__morphnet__` stash, circuit-level in the module stash and netlist-level in the header. No kfnetlist-core change: unlike directives, nobody asked for macros on `kfnetlist.Netlist`.
- **Fixture:** add a nyanlib entry with `code` and regenerate its golden netlist with `golden/regen.py`, so nyancad stays the reference.

### C. Bridge carries buses and `__` properties (#14)
- `public()` no longer discards keys the bridge does not own. Foreign `__*` keys go to the owning object's stash:
  - subcircuit → instance stash
  - circuit → module stash
  - connection → module stash keyed by `(source, target)`
- `Circuit.buses` is stashed as proto JSON in the module stash and restored in `to_proto_circuit`. Its member nets keep their current read-side behaviour.
- **Acceptance:** `test_bridge_lossless` gains a fixture with `Bus` (builder in `tests/morphnet/conftest.py:103`) and foreign `__x` properties on every carrier.

### D. Named port nets (#15)
- `document.rs:283`: fold into the `ports` form only when `net.name.is_none()`.
- Flip `tests/test_schema_models.py:630-636` and the changelog entry (`docs/source/changelog.md:47-49`).
- Cost: bridged YAML gets bulkier for named port nets.

### E. Malformed `__morphnet__` (#16)
- `Stash::take` returns `Err("info['__morphnet__'] must be an object")`, surfaced as `ValueError`.
- `_bridge.py:87` raises the same instead of skipping.
- Add a Python test for each path.

## Tasks (executed with subagent-driven development: one implementer + review per task, commits through the `commit-commands:commit` skill)
1. D + E: small bridge fixes and tests.
2. C: buses and foreign `__` properties through the bridge.
3. A, schema part: proto `Expression`, pydantic mirror, `expression.py`, shared grammar and per-dialect printing; writers switch from `expr` to `Expression`.
4. A, parsers: spice/hspice/xyce/spectre/SV produce `Expression`; one round-trip test per dialect.
5. A, gsch and bridge: source/derived params, write-back with an explicit error, Rust printer, raw re-parse in `_bridge.py`.
6. B: `Macro` proto, gsch `code`, writers, fixture and golden.
7. Docs:
   - API reference: Expression, Macro, write-back rules.
   - Changelog.
   - Copy this design to `docs/superpowers/specs/2026-11-20-gsch-integration-gaps-design.md`.
   - Update the PR #37 body.
8. GitHub issues, all with `--assignee das-dias`:
   - **#5:** Mosaic drops wires on files written from non-gsch sources. Mosaic/Livewire need a netlist snapshot saved on every edit, or periodically, to stay in sync.
   - **#9:** Unknown model types are called as subcircuits (`X`), as nyancad does. The limitation is described in the issue. The subcircuit can reference another circuit model from a library included at the top of the cell.
   - **#12:** a `Terminal{id}` naming convention in core. The issue also covers the `?` bug found here: the SPICE and Spectre writers (`spice/writer.py:202,237`, `spectre/writer.py:182`) write every unconnected pin as node `?`, which shorts them together. It lists the 8 ad-hoc naming sites.
   - **My additions**, found in this exploration:
     - **#18:** header duplication, with the measurements above.
     - **#17:** no wire-format version field, plus `deny_unknown_fields` on stashed proto, so new proto fields break older readers.
     - **#20:** `GND`→`0` is netlist-wide, so subckt instance lines get `0` while the `.subckt` header keeps `GND` (`spice/writer.py:53,125,156`).

## Schema feedback (beyond A/B, for the user to decide; also recorded in the #17 issue)
1. **Version field:** `Netlist.schema_version`. Older readers could then reject newer data with a clear message instead of a `deny_unknown_fields` error.
2. **Typed fields for semantics carried in string properties today:** `ground_net` per Circuit (fixes #20 scoping), `spice_prefix`, `model_name`, `sim_skip`, `dialect`, parameter `role`.
3. **Unconnected pins:** a first-class marker such as `PortReference.no_connect` or a single-ended `Connection`. `?` and one-ref-net workarounds would no longer be needed; this pairs with #12.
4. **`Circuit.buses`:** no parser fills it. Either the HDL parsers populate it (they flatten to `name[i]` nets today) or it is removed.

## Verification
- **Per task:** `maturin develop --release && just test && just test-rust && just pre-commit`. New files must be `git add`-ed and `pyproject.toml` touched so `just test` rebuilds.
- **The 27 gsch golden netlists stay byte-identical** after A. B adds new goldens from `regen.py`.
- **Lossless bridge:** `test_bridge_lossless` stays green and gains the buses, `__` and expression cases.
- **Expression round trip:** parse → write → parse for a `{a*b+1}` param in spice/xyce/spectre/hspice/SV.
- **gsch edit flow:** edit source `W` through `to_netlists` → `from_netlists`, then `write_gsch` shows the new `W` and `write_spice` shows the new `w`. Editing derived `w` directly raises `ValueError`.
- **#15:** `inverter` net names survive both YAML and the bridge.
- **#16:** a non-dict `__morphnet__` raises on both paths.
- **CI:** push, then `gh pr checks 37 --watch`, until green on all OSes.
- **Issues:** `gh issue list --assignee das-dias` shows the 6 new issues.
