# Basic Usage

## Parsing Netlists

Every parser takes a `str` of netlist text and returns a `Circuit` model. Here is the same RC lowpass filter parsed from each supported format:

=== "Spectre"

    ```python
    from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre

    circuit = parse_spectre("""\
    subckt rc_lowpass (in_ out gnd)
    R1 (in_ out) resistor value=1k
    C1 (out gnd) capacitor value=100p
    ends rc_lowpass
    """)
    ```

=== "HSPICE"

    ```python
    from kfnetlist.morphnet.netlist.hspice.parser import parse_hspice

    circuit = parse_hspice("""\
    .subckt rc_lowpass in_ out gnd
    R1 in_ out 1k
    C1 out gnd 100p
    .ends rc_lowpass
    """)
    ```

=== "SPICE"

    ```python
    from kfnetlist.morphnet.netlist.spice.parser import parse_spice

    circuit = parse_spice("""\
    .subckt rc_lowpass in_ out gnd
    R1 in_ out 1k
    C1 out gnd 100p
    .ends rc_lowpass
    """)
    ```

=== "Xyce"

    ```python
    from kfnetlist.morphnet.netlist.xyce.parser import parse_xyce

    circuit = parse_xyce("""\
    .subckt rc_lowpass in_ out gnd
    R1 in_ out 1k
    C1 out gnd 100p
    .ends rc_lowpass
    """)
    ```

=== "Verilog-AMS"

    ```python
    from kfnetlist.morphnet.netlist.vams.parser import parse_vams

    circuit = parse_vams("""\
    module rc_lowpass (in_, out, gnd);
      inout in_, out, gnd;
      resistor #(.value(1k)) R1 (.p(in_), .n(out));
      capacitor #(.value(100p)) C1 (.p(out), .n(gnd));
    endmodule
    """)
    ```

=== "Spectre-SPICE"

    ```python
    from kfnetlist.morphnet.netlist.spectre_spice.parser import parse_spectre_spice

    circuit = parse_spectre_spice("""\
    .subckt rc_lowpass in_ out gnd
    R1 in_ out 1k
    C1 out gnd 100p
    .ends rc_lowpass
    """)
    ```

All of these produce the same `Circuit` object with one module, two external module references (resistor, capacitor), and the corresponding connections.

## Writing Netlists

Every writer takes a `Circuit` model and returns formatted netlist text:

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.vams.writer import write_vams
from kfnetlist.morphnet.netlist.hspice.writer import write_hspice
from kfnetlist.morphnet.netlist.xyce.writer import write_xyce

circuit = parse_spectre("""\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
""")

# Convert to any supported format
print(write_vams(circuit))
print(write_hspice(circuit))
print(write_xyce(circuit))
```

## Format Conversion

The core pattern is simple: **parse** with one format, **write** with another.

### Spectre to Verilog-AMS

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.vams.writer import write_vams

spectre_text = """\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
"""

circuit = parse_spectre(spectre_text)
print(write_vams(circuit))
```

```verilog
module rc_lowpass (in_, out, gnd);
  inout in_, out, gnd;
  resistor #(.value(1k)) R1 (.p(in_), .n(out));
  capacitor #(.value(100p)) C1 (.p(out), .n(gnd));
endmodule
```

### Verilog-AMS to Spectre

```python
from kfnetlist.morphnet.netlist.vams.parser import parse_vams
from kfnetlist.morphnet.netlist.spectre.writer import write_spectre

vams_text = """\
module cmos_inverter (in_, out, vdd, vss);
  inout in_, out, vdd, vss;
  mosfet #(.L(0.18u), .W(1u)) M1 (.d(out), .g(in_), .s(vdd), .b(vdd));
  mosfet #(.L(0.18u), .W(0.5u)) M2 (.d(out), .g(in_), .s(vss), .b(vss));
endmodule
"""

circuit = parse_vams(vams_text)
print(write_spectre(circuit))
```

```spectre
subckt cmos_inverter (in_ out vdd vss)
M1 (out in_ vdd vdd) mosfet L=0.18u W=1u
M2 (out in_ vss vss) mosfet L=0.18u W=0.5u
ends cmos_inverter
```

### HSPICE to Spectre

```python
from kfnetlist.morphnet.netlist.hspice.parser import parse_hspice
from kfnetlist.morphnet.netlist.spectre.writer import write_spectre

hspice_text = """\
.subckt rc_lowpass in_ out gnd
R1 in_ out 1k
C1 out gnd 100p
.ends rc_lowpass
"""

circuit = parse_hspice(hspice_text)
print(write_spectre(circuit))
```

```spectre
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
```

## From and to kfnetlist Netlists

morphnet's `Circuit` and kfnetlist's `Netlist` share one schema (`circuit.proto`), so
two functions bridge them. Any netlist you build or extract with kfnetlist can be
written in every format, and every format can be read back as `Netlist`s for LVS,
open detection or flattening:

```python
from kfnetlist import Netlist, NetlistPort, PortRef, morphnet
from kfnetlist.morphnet.netlist import parse_spectre, write_spectre

nl = Netlist()
nl.create_inst("R1", kcl="", component="resistor", settings={"value": 1000.0})
nl.create_inst("C1", kcl="", component="capacitor", settings={"value": 1e-10})
for port in ("vin", "vout", "gnd"):
    nl.create_port(port)
nl.create_net(NetlistPort("vin"), PortRef("R1", "p"))
nl.create_net(PortRef("R1", "n"), PortRef("C1", "p"), NetlistPort("vout"))
nl.create_net(PortRef("C1", "n"), NetlistPort("gnd"))

circuit = morphnet.circuit_from_netlists({"rc": nl}, toplevel="rc")
print(write_spectre(circuit))

netlists = morphnet.circuit_to_netlists(parse_spectre(write_spectre(circuit)))
```

Output:

```spectre
subckt rc (vin gnd vout)
R1 (vin vout) resistor value=1000
C1 (vout gnd) capacitor value=1e-10
ends rc
```

Things to know:

- **Pin order.** Built-in devices (`resistor`, `capacitor`, `inductor`, `diode`,
  `bjt`, `mosfet`, `vsource`, `isource`) get the same pin order the SPICE parser
  uses. For other components, add an `ext_module(..., ports=[...])` to the circuit
  so positional formats (SPICE, Spectre) know their pin order.
- **Net names.** A net that contains a top-level port is named after the port.
  Other nets are named `net_<i>`, because kfnetlist's document model does not
  carry net names yet.
- **Values.** SI prefixes are applied (`1k` becomes `1000.0`). Non-numeric
  parameters (model references) are not converted to `Netlist` settings, and
  directives, libraries and simulation data stay on the `Circuit`.
- **Names.** Instance names are written as-is. SPICE infers the device type from
  the first letter, so use SPICE prefixes (`R1`, `C1`, `X...` for subcircuit
  calls) when SPICE output matters.
- **Standalone package.** The vendored schema registers `circuit.proto` in
  protobuf's global pool, as the standalone `mphnet` package does. Don't import
  both in the same process.

## YAML Interchange

### Serializing to YAML

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre

circuit = parse_spectre("""\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
""")

yaml_str = circuit.to_yaml()
print(yaml_str)
```

### Loading from YAML

```python
from kfnetlist.morphnet.morphnet_schema import Circuit

circuit = Circuit.from_yaml(yaml_str)
print(circuit.top_module)  # "rc_lowpass"
```

### Roundtrip

```python
from kfnetlist.morphnet.morphnet_schema import Circuit
from kfnetlist.morphnet.netlist.hspice.parser import parse_hspice

circuit = parse_hspice("""\
.subckt rc_lowpass in_ out gnd
R1 in_ out 1k
C1 out gnd 100p
.ends rc_lowpass
""")

yaml_str = circuit.to_yaml()
restored = Circuit.from_yaml(yaml_str)
assert restored == circuit
```

## Supported Formats Reference

| Format | Parser | Writer | File Extensions |
|---|---|---|---|
| HSPICE | `parse_hspice` | `write_hspice` | `.sp`, `.hsp` |
| SPICE | `parse_spice` | `write_spice` | `.sp`, `.spice` |
| Xyce | `parse_xyce` | `write_xyce` | `.cir`, `.xyce` |
| Spectre | `parse_spectre` | `write_spectre` | `.scs` |
| Spectre-SPICE | `parse_spectre_spice` | `write_spectre_spice` | `.scs` |
| Verilog-AMS | `parse_vams` | `write_vams` | `.vams`, `.va` |

All parsers and writers are importable from `kfnetlist.morphnet.netlist`:

```python
from kfnetlist.morphnet.netlist import (
    parse_hspice,
    write_hspice,
    parse_spectre,
    write_spectre,
    parse_spectre_spice,
    write_spectre_spice,
    parse_spice,
    write_spice,
    parse_vams,
    write_vams,
    parse_xyce,
    write_xyce,
)
```
