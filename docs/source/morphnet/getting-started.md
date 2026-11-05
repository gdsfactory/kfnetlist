# Getting Started

## Installation

### From PyPI

```bash
pip install kfnetlist
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add kfnetlist
```

### Development Setup

Requires [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just):

```bash
git clone https://github.com/gdsfactory/kfnetlist.git
cd kfnetlist
just dev      # install deps, build the Rust extension, install pre-commit hooks
just test     # run the test suite
just lint     # ruff check
just format   # ruff format
```

## Your First Parse

Parse a Spectre netlist into kfnetlist.morphnet's intermediate representation:

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre

text = """\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
"""

netlist = parse_spectre(text)

print(netlist.top_circuit)  # "rc_lowpass"
print(len(netlist.circuits))  # 1
```

The `netlist` object is a `Netlist` model — kfnetlist.morphnet's common intermediate representation. Every parser produces the same type, regardless of the input format.

## Your First Conversion

Convert from one format to another by combining a parser with a writer:

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.hspice.writer import write_hspice

spectre_text = """\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
"""

netlist = parse_spectre(spectre_text)
hspice_text = write_hspice(netlist)
print(hspice_text)
```

Output:

```spice
.subckt rc_lowpass in_ out gnd
R1 in_ out 1k
C1 out gnd 100p
.ends rc_lowpass
```

## YAML Roundtrip

Every `Netlist` object can be serialized to and from YAML for portable interchange:

```python
from kfnetlist.morphnet.morphnet_schema import Netlist
from kfnetlist.morphnet.netlist.hspice.parser import parse_hspice

netlist = parse_hspice("""\
.subckt rc_lowpass in_ out gnd
R1 in_ out 1k
C1 out gnd 100p
.ends rc_lowpass
""")

yaml_str = netlist.to_yaml()
restored = Netlist.from_yaml(yaml_str)

assert restored == netlist
```

## Project Structure

```
src/kfnetlist/morphnet/
  morphnet_schema/     # Pydantic + protobuf data models (Netlist, Circuit, Port, etc.)
  netlist/
    grammars/          # Lark EBNF grammar files for each format
    hspice/            # HSPICE parser, writer, transformer, preprocessor
    spectre/           # Spectre parser, writer, transformer, preprocessor
    spectre_spice/     # Spectre-SPICE parser, writer, preprocessor
    spice/             # Generic SPICE parser, writer, transformer, preprocessor
    vams/              # Verilog-AMS parser, writer, transformer, preprocessor
    xyce/              # Xyce parser, writer, transformer, preprocessor
    net_utils.py       # Connectivity utilities
    value_utils.py     # SI value parsing and formatting
    simulation_data.py # Simulation analysis helpers
```
