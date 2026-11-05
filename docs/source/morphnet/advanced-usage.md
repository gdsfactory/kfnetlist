# Advanced Usage

## Working with the Netlist Model

### Netlist Structure

A `Netlist` is the top-level container. It holds `Circuit` definitions, and each
`Circuit` holds `SubCircuit` instances. These are the kfnetlist schema
(`circuit.proto`) names, used unchanged in protobuf, JSON and YAML; only `ports` and
`port_name` serialize as `terminals` and `terminal_name`:

```
Netlist
├── name: str
├── top_circuit: str
├── circuits: list[Circuit]
│   ├── name, class_name: str
│   ├── ports: list[Port]                          # schema: terminals
│   ├── parameters: list[Parameter]
│   ├── subcircuits: list[SubCircuit]
│   │   └── name, circuit_name, class_name, parameters
│   ├── connections: list[Connection]
│   ├── buses: list[Bus]
│   └── directives: list[Directive]
├── ext_circuits: list[ExternalCircuit]            # body-less definitions (resistor, mosfet, PDK cells)
├── directives: list[Directive]                    # .include, .lib, .param, ...
├── libraries: dict[str, ExternalLibrary]
└── simulation: Simulation | None                  # analyses, output requests, measurements
```

Files written before this naming (`modules`, `top_module`, `module_references`,
`module_name`, `ext_modules`) still load.

### Inspecting Circuits

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre

netlist = parse_spectre("""\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
""")

circuit = netlist.circuits[0]
print(circuit.name)  # "rc_lowpass"

# List port names
for port in circuit.ports:
    print(f"  {port.name} ({port.direction.name})")

# List instances
for sub in circuit.subcircuits:
    print(f"  {sub.name} -> {sub.circuit_name}")
    for param in sub.parameters:
        print(f"    {param.name} = {param.default_value}")
```

### Inspecting Connections

Connections are point-to-point links between port references:

```python
for conn in circuit.connections:
    src = conn.source
    tgt = conn.target
    print(
        f"  net {conn.name}: {src.instance_name}.{src.port_name} -> "
        f"{tgt.instance_name}.{tgt.port_name}"
    )
```

### Modifying Circuits

kfnetlist.morphnet models are mutable Pydantic models: the builder methods (`Circuit.add`, `Circuit.connect`, `Netlist.add`, ...) edit them in place. To derive a modified copy without touching the original, use `model_copy`:

```python
from kfnetlist.morphnet import Port, PortDirection

modified = netlist.model_copy(update={"name": "my_modified_circuit"})

modified_circuit = circuit.model_copy(
    update={
        "name": "rc_lowpass_v2",
        "ports": circuit.ports + [Port(name="extra", direction=PortDirection.INPUT)],
    }
)
```

## Protobuf Serialization

### Binary Serialization

Compact binary format for storage or cross-language interop (C++, Java, Go, etc.):

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.morphnet_schema import Netlist

netlist = parse_spectre("""\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
""")

# Serialize to bytes
data = netlist.to_proto_bytes()
print(f"Binary size: {len(data)} bytes")

# Deserialize
restored = Netlist.from_proto_bytes(data)
assert restored == netlist
```

### JSON Serialization

```python
json_str = netlist.to_json()
restored = Netlist.from_json(json_str)
assert restored == netlist
```

## Simulation Data

kfnetlist.morphnet parses simulation directives (analyses, output requests, measurements) into structured models.

### Parsing Simulation Statements

```python
from kfnetlist.morphnet.netlist.hspice.parser import parse_hspice
from kfnetlist.morphnet.morphnet_schema import AnalysisKind

netlist = parse_hspice("""\
.macro inv vin vout vdd gnd
M1 vout vin vdd vdd pmos w=1u l=100n
M2 vout vin gnd gnd nmos w=500n l=100n
.eom inv
.tran 1n 10u
.print TRAN V(vout)
.end
""")

sim = netlist.simulation
print(f"Analyses: {len(sim.analyses)}")
print(f"Output requests: {len(sim.output_requests)}")

analysis = sim.analyses[0]
print(f"Kind: {analysis.kind.name}")  # TRAN
print(f"Arguments: {analysis.arguments}")  # ["1n", "10u"]

output = sim.output_requests[0]
print(f"Variables: {output.variables}")  # ["V(vout)"]
```

### Analysis Kinds

The `AnalysisKind` enum supports:

| Kind | Description |
|------|-------------|
| `OP` | Operating point |
| `DC` | DC sweep |
| `AC` | AC frequency sweep |
| `TRAN` | Transient analysis |
| `NOISE` | Noise analysis |
| `TF` | Transfer function |
| `SENS` | Sensitivity |
| `PZ` | Pole-zero |
| `DISTO` | Distortion |
| `FOUR` | Fourier |
| `FFT` | Fast Fourier Transform |

### FFT Example

```python
from kfnetlist.morphnet.netlist.hspice.parser import parse_hspice
from kfnetlist.morphnet.morphnet_schema import AnalysisKind

netlist = parse_hspice("""\
.fft V(out) NP=1024 START=0 STOP=10u
.end
""")

fft = netlist.simulation.analyses[0]
assert fft.kind == AnalysisKind.FFT
print(fft.options)  # {"NP": "1024", "START": "0", "STOP": "10u"}
```

## Preprocessing Raw Text

Each format has a preprocessor that normalizes raw input before parsing (strips comments, joins line continuations, normalizes whitespace). You can call them directly:

```python
from kfnetlist.morphnet.netlist.hspice.preprocess import preprocess_hspice
from kfnetlist.morphnet.netlist.spectre.preprocess import preprocess_spectre
from kfnetlist.morphnet.netlist.vams.preprocess import preprocess_vams

cleaned = preprocess_hspice(raw_text)
cleaned = preprocess_spectre(raw_text)
cleaned = preprocess_vams(raw_text)
```

This is useful when you need to inspect the cleaned text before parsing, or when building a custom pipeline.

## Value Utilities

The `value_utils` module provides functions for working with SPICE-style SI-prefixed numbers.

### Parsing SI Numbers

```python
from kfnetlist.morphnet.netlist.value_utils import parse_si_number
from kfnetlist.morphnet.morphnet_schema import SIPrefix

pv = parse_si_number("10k")
print(pv.double_value)  # 10.0
print(pv.prefix)  # SIPrefix.KILO

pv = parse_si_number("2.2u")
print(pv.double_value)  # 2.2
print(pv.prefix)  # SIPrefix.MICRO

pv = parse_si_number("100meg")
print(pv.double_value)  # 100.0
print(pv.prefix)  # SIPrefix.MEGA
```

### Formatting SI Values

```python
from kfnetlist.morphnet.netlist.value_utils import format_si_value
from kfnetlist.morphnet.morphnet_schema import PrefixedValue, SIPrefix

pv = PrefixedValue(double_value=100.0, prefix=SIPrefix.PICO)
print(format_si_value(pv))  # "100p"

pv = PrefixedValue(double_value=4.7, prefix=SIPrefix.KILO)
print(format_si_value(pv))  # "4.7k"
```

### Parsing Parameter Numbers

```python
from kfnetlist.morphnet.netlist.value_utils import parse_parameter_number

# Plain numbers -> prefixed_value with no SI prefix
pv = parse_parameter_number("42")
print(pv.prefixed_value.double_value)  # 42.0

# SI-prefixed -> prefixed_value
pv = parse_parameter_number("10k")
print(pv.prefixed_value.double_value)  # 10.0
print(pv.prefixed_value.prefix.name)  # "KILO"
```

### Device Port Templates

The module provides lookup dictionaries for standard SPICE device types:

```python
from kfnetlist.morphnet.netlist.value_utils import DEVICE_PORT_TEMPLATES, DEVICE_PREFIX_TO_CIRCUIT

print(DEVICE_PORT_TEMPLATES["M"])  # ["d", "g", "s", "b"]
print(DEVICE_PORT_TEMPLATES["R"])  # ["p", "n"]

print(DEVICE_PREFIX_TO_CIRCUIT["M"])  # "mosfet"
print(DEVICE_PREFIX_TO_CIRCUIT["R"])  # "resistor"
```
