# API Reference

## kfnetlist.morphnet.netlist — Parse and Write Functions

All functions are importable directly from `kfnetlist.morphnet.netlist`:

```python
from kfnetlist.morphnet.netlist import parse_spectre, write_spectre
```

Or from their format-specific modules:

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.spectre.writer import write_spectre
```

### HSPICE

#### `parse_hspice(text: str) -> Netlist`

Parse HSPICE netlist text. Handles `.subckt`/`.ends`, `.macro`/`.eom`, device instances, `.model` statements, simulation directives (`.tran`, `.ac`, `.dc`, `.op`, `.fft`, etc.), `.include`, `.lib`, `.param`.

#### `write_hspice(circuit: Netlist) -> str`

Write a `Netlist` to HSPICE format.

### SPICE

#### `parse_spice(text: str) -> Netlist`

Parse generic SPICE netlist text. Supports the common SPICE3 subset shared across simulators.

#### `write_spice(circuit: Netlist) -> str`

Write a `Netlist` to generic SPICE format.

### Xyce

#### `parse_xyce(text: str) -> Netlist`

Parse Xyce netlist text. Supports Xyce-specific syntax extensions.

#### `write_xyce(circuit: Netlist) -> str`

Write a `Netlist` to Xyce format.

### Spectre

#### `parse_spectre(text: str) -> Netlist`

Parse Spectre netlist text. Handles `subckt`/`ends`, instances with `(port list) circuit_name param=value` syntax, model statements, and simulation analyses.

#### `write_spectre(circuit: Netlist) -> str`

Write a `Netlist` to Spectre format.

### Spectre-SPICE

#### `parse_spectre_spice(text: str) -> Netlist`

Parse Spectre-SPICE mixed-mode netlists. Handles both Spectre and SPICE syntax blocks.

#### `write_spectre_spice(circuit: Netlist) -> str`

Write a `Netlist` to Spectre-SPICE format (SPICE-style output).

### Verilog-AMS

#### `parse_vams(text: str) -> Netlist`

Parse Verilog-AMS netlist text. Handles `module`/`endmodule`, named port connections (`.port(net)`), parameter overrides (`#(.param(value))`), natures, and disciplines.

#### `write_vams(circuit: Netlist) -> str`

Write a `Netlist` to Verilog-AMS format.

### SystemVerilog

#### `parse_systemverilog(text: str) -> Netlist`

Parse the structural subset of SystemVerilog (3.1a, Annex A): ANSI and non-ANSI
ports, `parameter`/`localparam`, net declarations, module instances with named,
positional, `.name`, `.*` and empty connections, and `assign`/`alias` net merges.
Behavioral code (`always`, `initial`, `function`, `task`, `generate`, ...) is kept
as text in `behavioral_block_N` circuit properties.

#### `write_systemverilog(circuit: Netlist) -> str`

Write a `Netlist` as structural SystemVerilog with ANSI headers and named
connections. Values are written as plain numbers (SystemVerilog has no SI suffixes).

### GSCH

gdsfactory+ schematics (`.gsch`) are the JSON files written by Mosaic (electrical)
and Livewire (photonic). They are a flat `{key: entry}` map, so there is no Lark
grammar. Everything the `Netlist` has no field for (positions, wires, polylines,
port markers) is stashed as raw JSON, so `write_gsch` restores it.

#### `parse_gsch(text, *, models=None, sim="ngspice", corners=(), name=None) -> Netlist`

Parse `.gsch` JSON text into a `Netlist` with one circuit, the schematic. Exposed
port markers are the circuit's ports, and the net `GND` is ground.

- `models` is the nyanlib mapping `{"models:<fqn>": {...}}` (the content of
  `models.nyanlib`). An inline top-level `"models"` key in the file is merged
  under it.
- `sim` is `"ngspice"`, `"xyce"` or `"vacask"` (case-insensitive; anything else
  raises `ValueError`). It picks the model entry of each device: the entry whose
  `implementation` equals `sim`, else the first one in the simulator's native
  language (SPICE for ngspice and Xyce, Spectre for VACASK), else, under VACASK,
  a SPICE library that VACASK loads as foreign (`lang=ngspice` or `lang=xyce`).
  Devices nyancad would not netlist (no Mosaic `nets`, or no model to netlist)
  stay in the circuit with the instance property `sim_skip="1"`. The SPICE and
  Spectre writers skip such instances; `write_gsch` still writes them.
- `corners` is a section name or a sequence of them. Each library takes the first
  of `corners` it has, else its own first section.
- `name` is the circuit name. It defaults to `__top__`, which the writers write
  flat, without a `.subckt` wrapper.

Model libraries become directives on the netlist: a library with sections is a
`LIB` (`.lib path section`), one without is an `INCLUDE` (`.include path`).
The SPICE writers put them at the top of the exported netlist, and the Spectre
writer writes `include "path" section=<section>` (plus `lang=<dialect>` for a SPICE
library loaded by VACASK).

```python
from kfnetlist.morphnet.netlist import parse_gsch, write_spice

netlist = parse_gsch(text, models=models, sim="ngspice", corners=["tt"])
print(write_spice(netlist))
```

#### `read_gsch(path, *, project_root=None, models=None, sim="ngspice", corners=()) -> Netlist`

Read a `.gsch` file and the `.gsch` schematics its devices instantiate. Only
wired devices (with Mosaic `nets`) whose `model` ends in `.gsch` and is not a
library model (no nyanlib `models` entries) are followed, as in nyancad. Each such
child, resolved against `project_root` (which defaults to the file's directory),
becomes a subcircuit named by its nyanlib `name`, else the file stem. Its ports,
sorted by name, are the pins and its prop defaults are the header parameters. A
missing child file, or two children with the same circuit name, raise
`ValueError` with the path. When `models` is `None`, the project's
`build/models.nyanlib` is read, else `models.nyanlib`. The libraries of the whole
hierarchy are gathered on the netlist, top first.

#### `write_gsch(netlist: Netlist) -> str`

Write the top circuit of a `Netlist` as `.gsch` JSON text. Instances and port
markers parsed from a `.gsch` keep their keys and layout fields; the others get
`type`, `name`, `x` and `y` on a grid. Wires, `net`/`via`/`taper` entries and
polylines whose endpoints survive are restored. An unedited
`write_gsch(parse_gsch(text, models=...))` is JSON-equal to `text`: device pins
keep their spelling (`A`/`B`, not SPICE's `p`/`n`), and a MOS bulk the parser
tied to ground is not written unless it was moved to another net.

#### Scope of the simulation export

The export follows nyancad's netlister (`nyancad/netlist.py` in gdsfactoryplus):
model selection, pin order, parameter expressions, sources and waveforms, and the
library includes. It writes the **circuit netlist**, not the simulator scaffolding
(title, `.end`, analysis and `control` cards, VACASK `load *.osdi` and model
cards). Pass the result to your own simulator deck.

Remaining differences from nyancad's output:

- Element names: the SPICE writer adds the device letter only when it is missing
  (`R1`, where InSpice writes `RR1`); the VACASK writer adds none (`m1`, where
  InSpice writes `xm1`).
- Numbers keep the user's text (`1n`, `1meg`); InSpice writes floats with units
  (`1e-09s`). The values are the same.
- Xyce netlists use `PARAMS:` on subcircuit headers and X calls. VACASK
  subcircuit parameters go on a `parameters` line in the body, as in nyancad.
- Scaffolding: the VACASK output starts with `ground 0`, which nyancad also
  writes; the other scaffolding (title, `load`/`model` cards, `control`) is not
  written.
- InSpice raises on parameters an element class does not know (for example
  `width=` on a built-in `nmos`); morphnet writes them through.
- Libraries are ordered top circuit first, then its children in device order;
  nyancad sorts by model key. The set is the same. With several matching corners
  the first one in the caller's order wins.
- Instances without a `name` keep their key, with its `:`.
- InSpice's element-class filtering is not mirrored: all parameters pass through,
  including ones VACASK has no name for.
- Source edge cases: values use the morphnet SI syntax, and a missing required
  pulse or exponential field raises `ValueError`.
- Unknown `spice-type` letters are called like subcircuits (`X`).
- Fixtures where nyancad crashes still netlist, with `nc_<instance>_<pin>` nodes for open pins.

#### Parameters and write-back

`parse_gsch` gives each device the parameters of the simulation view:

- **Source** (`properties["role"] == "source"`): an entry prop merged with its
  model's prop defaults. A source param is **editable**: `write_gsch` writes its
  value back to the entry's `props`, and the SPICE, Spectre, VACASK, SystemVerilog
  and Verilog-AMS writers leave it out of the device parameters and print its value
  where a derived parameter refers to it.
- **Derived**: a model `params` entry, an `Expression` over the source props
  (`w = width * 1e-6`). Not written to `props`.
- **Computed**: a value the simulation code works out from the props (`$mfactor`), and a model param named like the prop it reads
  (`w = w * 2`), which is one param holding the substituted value. Any other
  model param that reads that prop (`ad = w * 0.5`) holds its substituted value
  too, since `w` then names the device param.
- **Defaults**: model prop defaults the entry does not set. They are written back
  only once edited.

A V/I source has no parameters: its `dc`, `ac` and `tran` props become a
`Stimulus` (above). `write_gsch` writes an edited stimulus back to those props.

An edit to a derived or computed param makes `write_gsch` raise `ValueError`
naming the props to edit, for example `M1: 'w' is derived from model expression
'width * 1e-6'; edit 'width' instead`. An unedited param is not an error.

#### Known limits

- Props removed from a simulated instance are not written back by `write_gsch`.
- A file written from a non-gsch source has no Mosaic wires. Mosaic recomputes
  `nets` on the first edit; Livewire keeps them.
- Restored Mosaic `wire` entries are written as parsed. Mosaic recomputes `nets`
  from the wires on its first edit, so a connectivity edit made through the IR
  can be undone when the old wires still join the old pins.
- Through the kfnetlist bridge, the key order inside `.gsch` entries is not
  preserved: `write_gsch` output after `from_netlists(to_netlists(nl))` is
  JSON-equal to the output for `nl`, not text-equal.
- Inline nyanlib `code` blocks become `Netlist.macros`; equal blocks appear once
  across the hierarchy. A writer that cannot take the block's language (VACASK, SPICE
  writers for a `spectre` block, ...) writes a `skipped macro <name> (<language>)`
  comment and warns.
- An unconnected pin is written on its own node, `nc_<instance>_<pin>` (the
  instance as written, `XA` for SPICE); parsers drop a one-pin net named
  `nc_<instance>_...` on that instance, so it reads back unconnected. A one-pin
  net with any other name is kept.

---

## Bridge to `kfnetlist.Netlist`

`morphnet.to_netlists()` and `morphnet.from_netlists()` are lossless: what
`kfnetlist.Netlist` has no field for travels in two properties, so
`from_netlists(to_netlists(nl))` writes the same text as `nl`.

| Property | Type | Description |
|---|---|---|
| `Netlist.directives` | `list[dict[str, str]]` | File directives `{"kind", "name", "value"}`; `kind` is one of `include`, `lib`, `global`, `option`, `param`, `define`, `timescale` |
| `Netlist.info` | `dict[str, Any]` | Free-form metadata; morphnet data with no kfnetlist counterpart is under `info["__morphnet__"]` |

Both return fresh snapshots, like `instances`, `nets` and `ports`. They are
**excluded from equality**, so LVS comparisons ignore them. Instance `info` keys
that start with `__` (such as `__morphnet__`) are likewise excluded from instance
equality.

The document header (`name`, `properties`, `ext_circuits`, `libraries`,
`simulation`) is stored on every cell, so `from_netlists()` of any subset of the
cells, or with another `toplevel`, keeps it. Cells from several documents take the
toplevel's header plus the external circuits it lacks, by name.

An expression parameter is a string setting holding its canonical text (`2 * l`);
its tree rides in the instance's `info["__morphnet__"]`. Unchanged text restores
the tree; edited text is parsed again (`raw` when it does not parse). Any other
string or bool setting becomes a `raw` expression kept verbatim (`nch-lvt`,
`true`).
`CircuitDocument.net_names` and `CircuitDocument.directives` expose net names and
directives on the document side.

---

## kfnetlist.morphnet.morphnet_schema — Data Models

All models are importable from `kfnetlist.morphnet.morphnet_schema`:

```python
from kfnetlist.morphnet.morphnet_schema import Netlist, Circuit, Port, SIPrefix
```

### Base Class

#### `ProtoModel`

Base class for all kfnetlist.morphnet data models. Extends `pydantic.BaseModel` (mutable, `populate_by_name=True`) with protobuf, JSON and YAML serialization.

**Methods:**

| Method | Description |
|---|---|
| `to_proto() -> ProtoMessage` | Convert to a protobuf Message |
| `to_proto_bytes() -> bytes` | Serialize to binary protobuf |
| `from_proto_bytes(data: bytes) -> Self` | Deserialize from binary protobuf (classmethod) |
| `from_proto(msg: ProtoMessage) -> Self` | Convert from a protobuf Message (classmethod) |
| `to_json(**kwargs) -> str` | Serialize to JSON string (unset fields and empty `macros` left out, as in Rust) |
| `from_json(json_str: str) -> Self` | Deserialize from JSON string (classmethod) |
| `to_yaml(**kwargs) -> str` | Serialize to YAML string (same keys as `to_json`) |
| `from_yaml(yaml_str: str) -> Self` | Deserialize from YAML string (classmethod) |
| `model_copy(update={...})` | Create a modified copy (inherited from Pydantic) |

### Core Models

#### `Netlist`

Top-level container: circuit definitions, external circuits, directives and simulation.

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Netlist name |
| `top_circuit` | `top_circuit` | `str` | Name of the top-level circuit |
| `circuits` | `circuits` | `list[Circuit]` | Circuit definitions |
| `ext_circuits` | `ext_circuits` | `list[ExternalCircuit]` | Body-less circuit definitions (devices, models, PDK cells) |
| `properties` | `properties` | `dict[str, str]` | Arbitrary key-value properties |
| `directives` | `directives` | `list[Directive]` | Include, lib, param directives |
| `simulation` | `simulation` | `Simulation \| None` | Simulation configuration |
| `libraries` | `libraries` | `dict[str, ExternalLibrary]` | External model libraries by name |
| `macros` | `macros` | `list[Macro]` | Verbatim blocks, written after the directives |

#### `Circuit`

A circuit definition: ports, parameters, subcircuit instances and connections.

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Circuit name |
| `class_name` | `class_name` | `str` | Class/type name |
| `ports` | `terminals` | `list[Port]` | Port declarations |
| `parameters` | `parameters` | `list[Parameter]` | Parameter declarations |
| `model_interfaces` | `model_interfaces` | `list[ModelInterface]` | Model function definitions |
| `subcircuits` | `subcircuits` | `list[SubCircuit]` | Instances of other circuits |
| `connections` | `connections` | `list[Connection]` | Point-to-point connections |
| `buses` | `buses` | `list[Bus]` | Bus definitions |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |
| `directives` | `directives` | `list[Directive]` | Circuit-level directives |
| `macros` | `macros` | `list[Macro]` | Verbatim blocks, written inside the circuit |

#### `ExternalCircuit`

A primitive or externally-defined device (resistor, mosfet, etc.).

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Device name |
| `class_name` | `class_name` | `str` | Class/type name |
| `library_name` | `library_name` | `str` | Library providing the device |
| `group_name` | `group_name` | `str` | Group within the library |
| `ports` | `terminals` | `list[Port]` | Port declarations |
| `parameters` | `parameters` | `list[Parameter]` | Parameter declarations |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |
| `kind` | `kind` | `ExternalCircuitKind` | Device kind (DEVICE, MODEL, etc.) |

#### `SubCircuit`

An instance of a circuit or external circuit inside a parent circuit.

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Instance name |
| `circuit_name` | `circuit_name` | `str` | Referenced circuit name |
| `class_name` | `class_name` | `str` | Class/type name |
| `parameters` | `parameters` | `list[Parameter]` | Parameter values for this instance |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |

#### `Connection`

A point-to-point connection between two port references on a net.

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Net name |
| `source` | `source` | `PortReference \| None` | Source port reference |
| `target` | `target` | `PortReference \| None` | Target port reference |
| `domain` | `domain` | `SignalDomain` | Signal domain |
| `weight` | `weight` | `int` | Connection weight |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |

### Port Models

#### `Port`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Port name |
| `direction` | `direction` | `PortDirection` | INOUT, INPUT, or OUTPUT |
| `domain` | `domain` | `SignalDomain` | Signal domain |
| `width` | `width` | `int` | Bus width |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |
| `discipline` | `discipline` | `str` | Verilog-AMS discipline or SystemVerilog net type |

#### `PortReference`

A reference to a specific port on a specific instance.

| Field | Schema name | Type | Description |
|---|---|---|---|
| `instance_name` | `instance_name` | `str` | Name of the instance |
| `port_name` | `terminal_name` | `str` | Name of the port |

#### `Bus`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Bus name |
| `width` | `width` | `int` | Bus width |
| `domain` | `domain` | `SignalDomain` | Signal domain |
| `connections` | `connections` | `list[Connection]` | Bus connections |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |

### Parameter Models

#### `Parameter`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Parameter name |
| `default_value` | `default_value` | `ParameterValue \| None` | Default value |
| `description` | `description` | `str` | Description |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |

#### `ParameterValue`

A oneof value — exactly one field should be set:

| Field | Schema name | Type | Description |
|---|---|---|---|
| `prefixed_value` | `prefixed_value` | `PrefixedValue \| None` | SI-prefixed numeric value |
| `model_ref` | `model_ref` | `ModelReference \| None` | Reference to a model |
| `expression` | `expression` | `Expression \| None` | Expression tree or raw text |

#### `Expression`

A oneof, exactly one field set. JSON and YAML name the set field directly
(`{"binary": {"op": 3, "lhs": ..., "rhs": ...}}`), in Python and Rust alike:

| Field | Type | Description |
|---|---|---|
| `literal` | `PrefixedValue` | A number |
| `reference` | `str` | A parameter name (may contain `$`) |
| `unary` | `UnaryOp` | `op` (`-` or `!`) and `operand` |
| `binary` | `BinaryOp` | `op` (`+ - * / % ** == != < <= > >= && \|\|`), `lhs`, `rhs` |
| `call` | `Call` | `name` and `args` |
| `ternary` | `Ternary` | `cond`, `then`, `otherwise` |
| `raw` | `str` | Text no grammar parsed, kept verbatim |

`parse_expression(text) -> Expression` and `format_expression(expr, dialect,
resolve=None, *, named=False) -> str` live in
`kfnetlist.morphnet.netlist.expression`. `parse_expression` strips one outer `{}`
or `'...'`, never raises, and returns `Expression(raw=text)` when the text does not
parse. `^` is not in the grammar (it is XOR in SystemVerilog), so text with `^`
stays raw. `format_expression` prints the canonical form (`2 * x`) and wraps a
compound expression per dialect; `resolve(name)` substitutes a reference. An
unknown dialect raises `ValueError`.

| Dialect | Wrapping | Example |
|---|---|---|
| `ngspice`, `xyce` | `{...}` | `{2 * x}` |
| `hspice` | `'...'` | `'2 * x'` |
| `spectre`, `vacask`, `systemverilog`, `vams`, `gsch` | bare | `2 * x` |

A number or a bare name is never wrapped. Raw text is wrapped only when
`named=True` (the value of a `k=v` parameter) and it is not already wrapped, so
`x^2` becomes `{x^2}` in `k=v` position; a positional value such as `DC 1 AC 1`
stays verbatim. `parameter_value(text)` and `value_text(pval, dialect)` in the
same module build a `ParameterValue` from text and print one as `k=v` text.

#### `PrefixedValue`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `double_value` | `double_value` | `float` | Numeric value |
| `prefix` | `prefix` | `SIPrefix` | SI prefix (KILO, MEGA, PICO, etc.) |

#### `ModelReference`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `model_interface_name` | `model_interface_name` | `str` | Model interface name |
| `arguments` | `arguments` | `dict[str, ParameterValue]` | Model arguments |

#### `ModelInterface`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Interface name |
| `function_name` | `function_name` | `str` | Function name |
| `parameters` | `parameters` | `list[Parameter]` | Parameters |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |

### Directive Models

#### `Directive`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `kind` | `kind` | `DirectiveKind` | Directive type |
| `name` | `name` | `str` | Directive name/key |
| `value` | `value` | `str` | Directive value |

#### `Macro`

A multi-line block in one simulator language, written verbatim where the writer's
dialect accepts that language: SPICE writers take `spice`, `ngspice`, `xyce` and
`hspice`; Spectre takes `spectre` and wraps SPICE bodies in `simulator lang=spice`
/ `simulator lang=spectre`; SystemVerilog takes `systemverilog` and `verilog`;
Verilog-AMS takes `verilog-ams`, `verilog-a` and `vams`. Any other block is a
`skipped macro <name> (<language>)` comment (`*` in SPICE, `//` elsewhere) plus a
warning, so a macro is never dropped silently. The VACASK writer
takes none, not even `spectre`: every macro is skipped, as nyancad drops them.

`parse_gsch` reads a macro from a nyanlib model entry's inline `code` (language
`spice` when the entry names none, as nyancad injects it). Equal macros (name,
language, body) appear once across the hierarchy; a block with the name of another
but different code is kept as well, with a warning. The kfnetlist bridge merges
cells' macros the same way. `write_gsch` does not write macros back. A netlist's macros come after its directives; a circuit's inside it.

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Macro name (a nyanlib model entry name) |
| `language` | `language` | `str` | Language of the body (`spice`, `spectre`, ...) |
| `body` | `body` | `str` | The block, written as is |
| `properties` | `properties` | `dict[str, str]` | Arbitrary properties |

### Simulation Models

#### `Simulation`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `analyses` | `analyses` | `list[Analysis]` | Simulation analyses |
| `output_requests` | `output_requests` | `list[OutputRequest]` | Print/plot/probe/save requests |
| `measurements` | `measurements` | `list[Measurement]` | .meas statements |
| `initial_conditions` | `initial_conditions` | `InitialCondition \| None` | Initial conditions |
| `node_sets` | `node_sets` | `InitialCondition \| None` | Node sets |
| `temperatures` | `temperatures` | `list[float]` | Temperature list |
| `stimuli` | `stimuli` | `list[Stimulus]` | What drives each V/I source |
| `options` | `options` | `dict[str, str]` | Simulation options |

#### `Stimulus` and `Waveform`

A V/I source element names its stimulus in `properties["stimulus"]`
(`"<circuit>/<instance>"`); `stimulus_of(netlist, ref)` in
`kfnetlist.morphnet.netlist.stimulus` finds it. Values are `ParameterValue`s, so a
source reading a parameter (`DC {vdd/2}`) keeps its expression.

| Field | Type | Description |
|---|---|---|
| `Stimulus.name` | `str` | `"<circuit>/<instance>"` |
| `Stimulus.dc` / `ac_magnitude` / `ac_phase` | `ParameterValue \| None` | DC value, AC magnitude and phase |
| `Stimulus.waveform` | `Waveform \| None` | Transient shape |
| `Waveform.kind` | `WaveformKind` | `PULSE`, `SIN`, `EXP`, `SFFM`, `PWL` |
| `Waveform.args` | `dict[str, ParameterValue]` | SPICE semantics, Spectre names: pulse `val0 val1 delay rise fall width period`; sin `sinedc ampl freq delay theta`; exp `val0 val1 delay tau1 td2 tau2` (`td2` from time 0); sffm `sinedc ampl freq modindex modfreq` |
| `Waveform.points` | `list[ParameterValue]` | PWL `t0 v0 t1 v1 ...` |

Every parser reads its language's own source syntax into a stimulus, and every
writer writes it back:

| Language | Native form |
|---|---|
| ngspice, HSPICE, Xyce, Spectre-SPICE | `V1 a 0 DC 0.9 AC 1 0 PULSE(0 1.8 1n 10p 10p 1n 2n)` (a lone value is the DC value; a param name is braced, `{vdd}`) |
| Spectre | `V1 (a 0) vsource dc=0.9 mag=1 type=pulse val0=0 ...` |
| VACASK | the Spectre form with InSpice's spelling: quoted `type`, no zero `delay`/`theta`, no `rise <= 0`, `td2` from the delay |
| Verilog-A/AMS, SystemVerilog | Verilog-AMS LRM Annex E Table E.1 primitives: `vpulse #(.dc(0.9), .val0(0), .td(1n))`; `vsine`/`vexp`/`vpwl` (`i*` for current); a DC/AC source is `vsine #(.dc(..))` (LRM E.2.2.3). Names map `delay`→`td`, `sinedc`→`offset`, `theta`→`damp`, exp `delay tau1 td2 tau2`→`td0 tau0 td1 tau1`, sffm → `vsine` `fmmodindex fmmodfreq`, PWL → `wave` `'{t0, v0, ...}`. SystemVerilog numbers have no SI suffix. |

Verilog-A has no analysis, option, temperature or save statements; those
`Simulation` fields are not written to it. Its native forms that are read and
written:

- **Nodesets**: a top-module net initializer `electrical b = 5.0;` (LRM §3.6.3.2)
  is `node_sets.conditions["V(b)"]`.
- **Device models**: a `.model` device is called by its model name, with an empty
  `paramset <model> <primitive>; endparamset` (LRM §7.5) so a reader knows its kind
  and pins.
- **What it cannot say** rides in attributes (IEEE 1364 §3.8) of the module:
  `(* spice_lib = "path section\n..." *)` for SPICE libraries and
  `(* spice_code = "<json>" *)` / `(* spice_module_code = "<json>" *)` for inline
  code in another language, on the top module and on each module.

#### `Analysis`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `kind` | `kind` | `AnalysisKind` | Analysis type (OP, DC, AC, TRAN, etc.) |
| `name` | `name` | `str` | Analysis name |
| `arguments` | `arguments` | `list[str]` | Positional arguments |
| `options` | `options` | `dict[str, str]` | Named options |

#### `OutputRequest`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `kind` | `kind` | `OutputRequestKind` | PRINT, PLOT, PROBE, or SAVE |
| `analysis_type` | `analysis_type` | `str` | Associated analysis type |
| `variables` | `variables` | `list[str]` | Variable expressions |

#### `Measurement`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `name` | `name` | `str` | Measurement name |
| `analysis_type` | `analysis_type` | `str` | Associated analysis type |
| `body` | `body` | `str` | Measurement body |

#### `InitialCondition`

| Field | Schema name | Type | Description |
|---|---|---|---|
| `conditions` | `conditions` | `dict[str, str]` | Node/value pairs |

### Enums

#### `PortDirection`

`INOUT` (0), `INPUT` (1), `OUTPUT` (2)

#### `SignalDomain`

`UNSPECIFIED` (0), `ELECTRICAL` (1), `WAVEGUIDE` (2)

#### `SIPrefix`

`UNSPECIFIED` (0), `QUECTO` (1), `RONTO` (2), `YOCTO` (3), `ZEPTO` (4), `ATTO` (5), `FEMTO` (6), `PICO` (7), `NANO` (8), `MICRO` (9), `MILLI` (10), `CENTI` (11), `DECI` (12), `DECA` (13), `HECTO` (14), `KILO` (15), `MEGA` (16), `GIGA` (17), `TERA` (18), `PETA` (19), `EXA` (20), `ZETTA` (21), `YOTTA` (22), `RONNA` (23), `QUETTA` (24)

#### `ExternalCircuitKind`

`UNSPECIFIED` (0), `DEVICE` (1), `MODEL` (2), `NATURE` (3), `DISCIPLINE` (4)

#### `DirectiveKind`

`UNSPECIFIED` (0), `INCLUDE` (1), `LIB` (2), `GLOBAL` (3), `OPTION` (4), `PARAM` (5), `DEFINE` (6), `TIMESCALE` (7)

#### `AnalysisKind`

`UNSPECIFIED` (0), `OP` (1), `DC` (2), `AC` (3), `TRAN` (4), `NOISE` (5), `TF` (6), `SENS` (7), `PZ` (8), `DISTO` (9), `FOUR` (10), `FFT` (11)

#### `OutputRequestKind`

`UNSPECIFIED` (0), `PRINT` (1), `PLOT` (2), `PROBE` (3), `SAVE` (4)

---

## kfnetlist.morphnet.netlist.value_utils — Value Utilities

```python
from kfnetlist.morphnet.netlist.value_utils import parse_si_number, format_si_value
```

#### `parse_si_number(token: str) -> PrefixedValue`

Parse a SPICE-style SI-prefixed number (e.g., `"10k"`, `"2.2u"`, `"100meg"`) into a `PrefixedValue`. Raises `ValueError` if the token is not valid.

#### `format_si_value(pv: PrefixedValue) -> str`

Format a `PrefixedValue` as a SPICE-style string (e.g., `"10k"`, `"2.2u"`).

#### `parse_parameter_number(token: str) -> ParameterValue`

Parse a numeric token into the most appropriate `ParameterValue` variant. Whole integers return `int_value`; everything else returns `prefixed_value`.

#### `is_si_number(token: str) -> bool`

Check whether a token looks like an SI-prefixed number.

#### Constants

| Constant | Type | Description |
|---|---|---|
| `SI_SUFFIX_TO_PREFIX` | `dict[str, SIPrefix]` | Maps suffix strings (`"k"`, `"u"`, `"meg"`, etc.) to `SIPrefix` enum values |
| `PREFIX_TO_SI_SUFFIX` | `dict[SIPrefix, str]` | Reverse mapping from `SIPrefix` to suffix strings |
| `DEVICE_PORT_TEMPLATES` | `dict[str, list[str]]` | Maps device prefix letters to port name lists (e.g., `"M"` -> `["d", "g", "s", "b"]`) |
| `DEVICE_PREFIX_TO_CIRCUIT` | `dict[str, str]` | Maps device prefix letters to external circuit names (e.g., `"M"` -> `"mosfet"`) |

---

## kfnetlist.morphnet.netlist.net_utils — Network Utilities

```python
from kfnetlist.morphnet.netlist.net_utils import (
    net_map_to_connections,
    connections_to_instance_nets,
)
```

#### `net_map_to_connections(net_map: NetMap) -> list[Connection]`

Convert a net-based connectivity map (`dict[str, list[PortReference]]`) to point-to-point `Connection` objects. For each net with N port references, produces N-1 connections.

#### `connections_to_instance_nets(connections: list[Connection]) -> dict[tuple[str, str], str]`

Build an `(instance_name, port_name) -> net_name` lookup from a list of `Connection` objects. Used by writers to reconstruct instance lines with correct net names.

#### `add_port_to_net(net_map: NetMap, net_name: str, instance_name: str, port_name: str) -> None`

Register a port reference on a net in the net map.

#### Type Aliases

| Alias | Definition | Description |
|---|---|---|
| `NetMap` | `dict[str, list[PortReference]]` | Maps net names to port references |
