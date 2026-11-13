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
| `to_json(**kwargs) -> str` | Serialize to JSON string |
| `from_json(json_str: str) -> Self` | Deserialize from JSON string (classmethod) |
| `to_yaml(**kwargs) -> str` | Serialize to YAML string |
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
| `options` | `options` | `dict[str, str]` | Simulation options |

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
