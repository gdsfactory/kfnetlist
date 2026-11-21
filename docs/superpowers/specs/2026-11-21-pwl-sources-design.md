# PWL sources in every grammar (inline, from a file, `PULSE (` with a space)

## Intent
Every PWL form is a source, like PULSE: inline points, Spectre's `wave=[t v ...]`,
and PWL read from a file (Cadence `vpwlf`/`ipwlf`). Each parses into a `Stimulus`,
survives every conversion, and `PULSE (0 1 ...)` (space before `(`) parses in every
SPICE grammar.

## Approaches (user picked A)
- **A. Typed `Waveform.file`** — proto `string file = 4` on a PWL waveform; native
  forms where they exist; a module attribute in Verilog-A/SV. *Picked.*
- B. `Waveform.args["file"]` as a string value — no schema change, untyped.
- C. Inline the file's points at write time — runs everywhere, loses the link and
  makes writing depend on the file being found.

## Design
- **Schema:** `Waveform.file = 4` (string). Python mirror: `file: Path | None`
  (`pathlib.Path`), serialized as a POSIX string so Rust↔pydantic JSON stays equal.
  A relative path stays relative (parsers read text; there is no directory to
  resolve against). A PWL waveform has `points` or `file`.
- **Native forms:**

  | Language | Inline PWL | PWL from a file |
  |---|---|---|
  | ngspice, HSPICE, Spectre-SPICE | `PWL(0 0 1n 1.8)` | `PWL FILE "w.txt"` (round-trips; the simulator may reject it) |
  | Xyce | `PWL(0 0 1n 1.8)` | `PWL FILE "w.txt"` (native) |
  | Spectre / VACASK | `type=pwl wave=[0 0 1n 1.8]` | `type=pwl file="w.txt"` (native; how Cadence netlists `vpwlf`) |
  | Verilog-A / SystemVerilog | `vpwl #(.wave('{0, 0, 1n, 1.8}))` | `(* pwl_file = "w.txt" *) vpwl V1 (...)` (instance attribute; no native form) |

- **OS-agnostic path resolver, the same in Python and Rust:**
  - Stored form (schema, JSON, every netlist dialect): POSIX separators, relative
    kept relative. `posix_file(path) -> str` turns `data\w.txt` or a `Path` into
    `data/w.txt`.
  - `resolve_file(file, base=None) -> Path` (Python, `pathlib`) and
    `resolve_file(file: &str, base: Option<&Path>) -> PathBuf` (Rust,
    `std::path`) both:
    - accept `/` and `\` as separators;
    - treat `/x`, `C:\x`, `C:/x` and `\\server\share\x` as absolute on every host;
    - join a relative path to `base`;
    - normalize `.` and `..` lexically, with no filesystem access or symlinks, so
      the same answer comes out on every OS.
  - Python lives in `kfnetlist.morphnet.netlist.paths`; Rust in
    `kfnetlist_schema::paths`. Both test against one shared case table
    (`tests/data/path_cases.json`, read by pytest and by the Rust test via
    `include_str!`), so the two implementations cannot drift.
  - `Waveform.file` in Python is a `Path` built through the resolver (no base); a
    caller who knows the netlist's directory calls `resolve_file(file, base)`.
- **Grammars:** SPICE-family `FUNC_CALL` allows whitespace before `(`; a
  `FILE "..."` / `FILE=...` source token after `PWL`; the Spectre grammar reads
  `[...]` values (with spaces) and `file="..."`; the Verilog-A grammar reads
  attribute instances before an instance statement.
- **Fixes the two deferred minors:** Spectre `wave=[...]` parse and the
  `str(ParameterValue)` text in `from_spectre`; `PULSE (` with a space.

## Non-goals
Reading the file's contents; resolving against the working directory or following
symlinks (`Path.resolve()`); ngspice `filesource` code models; moving
`.include`/`.lib` paths onto the resolver (it is generic and can take them later).

## Acceptance
- Round trip in every dialect for: inline PWL, PWL from a file (relative and
  nested path), `PULSE (...)` with a space, Spectre `wave=[...]`.
- Rust↔pydantic JSON parity with `file` set; `Waveform.file` is a `Path` in Python.
- The shared path-case table passes in both pytest and `cargo test`. It covers
  POSIX, Windows-drive, UNC, mixed separators, `..` and a base join, and the tests
  run on the Linux, macOS and Windows CI.
- The strict conversion test and the full suite stay green.

## My calls (check these)
- The Python `Path` is kept as written, not `.resolve()`d.
- ngspice/HSPICE get Xyce's `PWL FILE "w.txt"` form.
- Verilog-A/SV attribute name `pwl_file`, on the source instance.
