# PWL sources in every grammar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** inline PWL, PWL from a file and `PULSE (` with a space parse into `Stimulus` in every grammar and round-trip; file paths go through one OS-agnostic resolver, the same in Python and Rust.

**Architecture:** `Waveform.file` (proto string, Python `Path`); `paths.py` / `paths.rs` with one shared case table; `stimulus.py` renders/reads the file form per dialect; grammar tokens for `FUNC (`, `FILE "…"`, Spectre `[...]`, Verilog-A instance attributes.

**Tech Stack:** protobuf (prost + protoc), pydantic, lark, Rust std::path, pathlib.

**Spec:** `docs/superpowers/specs/2026-11-21-pwl-sources-design.md`

## Global Constraints
- Stored path form: POSIX separators, relative kept relative.
- `resolve_file` accepts `/` and `\`; `/x`, `C:\x`, `C:/x`, `\\server\share\x` are absolute on every host; lexical `.`/`..`; no filesystem access.
- Native forms per the spec's table; Verilog-A/SV attribute name `pwl_file` on the source instance.
- After Rust/proto changes: `maturin develop --release`, `just compile-schema-py`, touch `pyproject.toml`.
- Full suite + `just test-rust` + `just pre-commit` green per task; strict conversion test stays 66/66.

## Review Focus
- A Windows-authored netlist `PWL FILE "data\w.txt"` → `Waveform.file == Path("data/w.txt")` and writes back `data/w.txt` on every OS.
- `resolve_file("../w.txt", base)` never touches the filesystem and gives the same parts on Windows and POSIX.
- `PULSE (0 1 1n)` and `PULSE(0 1 1n)` read the same stimulus.
- A PWL waveform with both `points` and `file` is rejected (oneof-like rule), not silently written with one dropped.
- Spectre `wave=[0 0 1n {vdd}]` keeps the expression point.

---

### Task 1: OS-agnostic path resolver (Python + Rust, one case table)
**Files:** Create `src/kfnetlist/morphnet/netlist/paths.py`, `crates/kfnetlist-schema/src/paths.rs` (export from `lib.rs`), `tests/data/path_cases.json`, `tests/morphnet/test_paths.py`; Rust test in `crates/kfnetlist-schema/tests/paths.rs` reading the table with `include_str!("../../../tests/data/path_cases.json")`.
**Produces:** Python `posix_file(path: str | PurePath) -> str`, `resolve_file(file: str | PurePath, base: str | PurePath | None = None) -> PurePosixPath | PureWindowsPath`-agnostic result returned as `pathlib.Path` built from the normalized parts; Rust `posix_file(path: &str) -> String`, `resolve_file(file: &str, base: Option<&str>) -> String` (normalized POSIX string; callers make a `PathBuf`).
- [ ] Case table rows `{file, base, posix, resolved, absolute}`: `w.txt`; `data\w.txt`; `./a/../w.txt`; `../w.txt` with base `/proj/sim`; `C:\lib\w.txt`; `C:/lib/w.txt` with base `/x` (stays C:); `\\srv\share\w.txt`; `/abs/w.txt` with base `/x`; `a//b/./w.txt`.
- [ ] Failing pytest + cargo test over the table → implement both → green. Commit.

### Task 2: Schema `Waveform.file`
**Files:** `simulation.proto` (`string file = 4;`), regenerated pb2, `_simulation.py` (`file: Path | None`, serialized via `posix_file`, validated via `resolve_file`; reject points+file), test in `tests/morphnet/test_circuit_models.py` (Rust↔pydantic JSON parity with `file="data/w.txt"`, `Waveform(file="data\\w.txt").file == Path("data/w.txt")`, points+file → ValueError).
- [ ] Failing test → implement → green. Commit.

### Task 3: `stimulus.py` renders and reads PWL files and spaced functions
**Files:** `stimulus.py`, `tests/morphnet/test_stimulus.py`.
- [ ] Cases: `pwl_file` (file `data/w.txt`) for SPICE (`PWL FILE "data/w.txt"`), Spectre (`type=pwl file="data/w.txt"`), primitive (`vpwl`, no `wave`; file returned separately for the writer's attribute); `parse_spice("PULSE (0 1 1n)") == parse_spice("PULSE(0 1 1n)")`; `from_spectre` reads `wave` given as a ParameterValue or text with expressions; points+file never emitted together.
- [ ] Failing → implement (`primitive()` returns the file via a new `primitive_file(stim) -> str | None`) → green. Commit.

### Task 4: Grammars and writers
**Files:** `grammars/{spice,hspice,xyce}.lark` (`FUNC_CALL` with `\s*` before `(`; `FILE` keyword + quoted/bare path tokens after `PWL`), `spice/transformer.py` (join), `grammars/spectre.lark` (`[...]` VALUE with spaces), `spectre/transformer.py`, `grammars/vams.lark` + `vams/transformer.py` (attribute instances before `instance_stmt`; `pwl_file` → `Waveform.file`), `vams/writer.py` + `systemverilog/writer.py` (emit `(* pwl_file = "…" *)`), SV grammar/transformer if needed; tests: one parametrized round-trip file `tests/morphnet/test_pwl_sources.py` over every dialect × {inline PWL, PWL file, `PULSE (`, Spectre `wave=[...]` with an expression}.
- [ ] Failing → implement → green; strict conversion test 66/66. Commit; docs (changelog, api-reference native-forms table, resolver); push; CI green.
