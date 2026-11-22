# `.gsch` → every SPICE dialect and Verilog-A, losslessly; simulation fixtures as protos

## Intent
A `.gsch` schematic converted to ngspice, HSPICE, Xyce, Spectre, Spectre-SPICE or
Verilog-A must read back with that format's parser with **nothing missing**:
libraries, inline code, subcircuits with pins and params, and per element its
master, nets, values and stimulus. `tests/morphnet/test_gsch_conversions.py` is the
acceptance test (11 fixtures × 6 formats); it passes only when no field is lost.

**User rulings:**
- Fix everything; tests green.
- Simulation fixtures are parsed into shared protobuf `Simulation` objects carried by
  the `Netlist`. Every language's *native* way of declaring them is parsed (and
  written) — no invented syntax where a native one exists.
- Each V/I element points to one `Stimulus` (dc, ac magnitude/phase, waveform).
- Verilog-A sources use native primitives; a `.lib` corner and inline SPICE code,
  which Verilog-A cannot express, ride in `(* … *)` attributes the parser reads back.

## Native simulation constructs (research: Verilog-AMS LRM 2.4.0, IEEE 1364/1800)
| Language | Stimulus | Other `Simulation` fields |
|---|---|---|
| ngspice/HSPICE/Xyce | `DC x AC m ph PULSE/SIN/EXP/SFFM/PWL(...)` on V/I lines | `.tran/.ac/...`, `.option`, `.ic`, `.nodeset`, `.temp`, `.meas`, `.print` (already parsed) |
| Spectre/VACASK | `vsource dc= mag= phase= type=pulse val0= ...` | analyses, `save` (already parsed), `simulator lang=` sections |
| Verilog-A/AMS | LRM Annex E Table E.1 primitives `vpulse/vsine/vexp/vpwl` (`i*`), params `dc, mag, phase` + per-kind names; DC/AC-only = `vsine #(.dc(..))` (LRM E.2.2.3) | nodeset = net initializer `electrical a = 5.0;` (§3.6.3.2). Analyses, options, temperature, saves: **no native form** — not written |
| SystemVerilog | same primitive instances (structural netlists we support) | none native |

Table E.1 names: pulse `val0 val1 td rise fall width period`; sine `offset ampl freq td
damp sinephase fmmodindex fmmodfreq`; exp `val0 val1 td0 tau0 td1 tau1`; pwl `wave`.
A `.model` name is the module name (`Mprim #(...) M3 (...)`); there is no `model` param.

## Design
### Schema
- New `value.proto` (package `circuit`): `SIPrefix, PrefixedValue, Operator, UnaryOp,
  BinaryOp, Call, Ternary, Expression, ModelReference, ParameterValue` move there;
  `circuit.proto` and `simulation.proto` import it. Rust paths unchanged; Python gets
  `value_pb2` and a pydantic `_value.py` (breaks the `_circuit` ↔ `_simulation` cycle).
- `simulation.proto`:
  ```proto
  enum WaveformKind { WAVEFORM_KIND_UNSPECIFIED = 0; WAVEFORM_KIND_PULSE = 1;
    WAVEFORM_KIND_SIN = 2; WAVEFORM_KIND_EXP = 3; WAVEFORM_KIND_SFFM = 4; WAVEFORM_KIND_PWL = 5; }
  message Waveform { WaveformKind kind = 1; map<string, ParameterValue> args = 2;
                     repeated ParameterValue points = 3; }  // PWL t0 v0 t1 v1 ...
  message Stimulus { string name = 1; ParameterValue dc = 2; ParameterValue ac_magnitude = 3;
                     ParameterValue ac_phase = 4; Waveform waveform = 5; }
  // Simulation: repeated Stimulus stimuli = 7;
  ```
- Link: the V/I `SubCircuit` has `properties["stimulus"] = <Stimulus.name>`, name
  `"<circuit>/<instance>"`. Plain property → the kfnetlist bridge carries it unchanged;
  `Simulation` already travels in the header stash.
- Canonical waveform arg names (SPICE semantics, Spectre spelling, as `gsch/sim.py` TRAN):
  pulse `val0 val1 delay rise fall width period`; sin `sinedc ampl freq delay theta`;
  exp `val0 val1 delay tau1 td2 tau2` (`td2` absolute, as SPICE); sffm `sinedc ampl
  freq modindex modfreq`; pwl `points`.

### One shared module, `netlist/stimulus.py`
TRAN table moves here from `gsch/sim.py`. Renders and reads each dialect:
SPICE text, Spectre params (VACASK quirks — drop zero `delay`/`theta`, `rise ≤ 0`,
`td2` from the delay, quoted `type` — only for dialect `vacask`), Table E.1 primitives.

### Other fixes
1. One-pin nets survive parsing (source-only `Connection`, as gsch already does).
2. An unconnected pin is written as a named open node `nc_<inst>_<pin>` (not `?`);
   parsers drop a one-pin net of exactly that name → exact round trip.
3. Top circuit is `__top__` whenever a deck has top-level elements (spice, spectre,
   spectre_spice, vams).
4. SPICE: lone non-number in an R/C/L value slot is a param reference unless a
   `.model` of that name exists.
5. Spectre: parse `simulator lang=` sections; keep quoted strings.
6. Verilog-A: expressions in `#(...)`; empty port list; `(* *)` attributes; module
   master = model name; escaped module names; `ground` from the netlist's
   `ground_net`; module attributes `(* spice_lib = "path section\n..." *)` and
   `(* spice_code = "<json list of macros>" *)` on the top module.

## Non-goals
Analyses/options/temperature in Verilog-A/SV (no native form); procedural SV
testbenches (`initial`/`#delay`); simulating Xyce/VACASK/Verilog-A output.

## Constraints
- The 30 nyancad goldens stay green, normaliser unchanged.
- `test_export_survives_the_kfnetlist_bridge` and `test_bridge_lossless` stay green.

## My calls (check these)
- `value.proto` split over defining `Stimulus` in `circuit.proto` (you asked for simulation.proto).
- Link by property, not a typed `SubCircuit` field (no bridge stash work).
- Canonical names are Spectre's; Verilog-A writer maps to Table E.1.
- Open-node name `nc_<inst>_<pin>`.
- Test view compares a device master as `model_name or circuit_name` (Spectre cannot
  tell `X` subckt models from `.model` devices syntactically).
- SystemVerilog gets the same primitives; it is not in the conversion test (you asked for SPICE + Verilog-A).
