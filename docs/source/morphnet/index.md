# kfnetlist.morphnet

A bidirectional netlist parser built on [Lark](https://github.com/lark-parser/lark), enabling translation between SPICE-family circuit netlist formats (HSPICE, Xyce, Spectre, Spectre-SPICE), Verilog-AMS and structural SystemVerilog.

All formats share a common intermediate representation defined in [Protocol Buffers](https://protobuf.dev/) and wrapped with [Pydantic v2](https://docs.pydantic.dev/) models, making it straightforward to parse, transform, and serialize netlists programmatically.

## Key Features

- **7 netlist formats** — HSPICE, SPICE, Xyce, Spectre, Spectre-SPICE, Verilog-AMS, SystemVerilog
- **Electrical and photonic** — terminals named `o1`, `o2`, ... are waveguide terminals in every format; `e1`, ... and unprefixed names are electrical
- **Bidirectional** — every format has both a parser and a writer
- **Common IR** — all formats parse into the same `Netlist` model (`Netlist` → `Circuit` definitions → `SubCircuit` instances), which serializes to protobuf, JSON and YAML with the kfnetlist schema (`circuit.proto`) field names
- **Protocol Buffers** — compact binary serialization for cross-language interop
- **Pydantic v2** — type-safe data models with JSON and YAML support
- **Lark grammars** — each format is defined by a clean EBNF grammar

## Architecture

```
spectre.scs ──┐                          ┌── spectre.scs
hspice.sp  ───┤  parse_*()   write_*()   ├── hspice.sp
xyce.cir   ───┼──────────► Netlist ──────►├── xyce.cir
spice.sp   ───┤          (protobuf +      ├── spice.sp
vams.vams  ───┤           pydantic)       ├── vams.vams
netlist.sv ───┘                           └── netlist.sv
                             │
                        to_yaml / from_yaml
                             │
                          netlist.yaml
```

Each format follows the same internal pipeline:

```
raw text → preprocess → Lark grammar → parse tree → Transformer → Netlist
Netlist → Writer → formatted text
```

## Quick Example

```python
from kfnetlist.morphnet.netlist.spectre.parser import parse_spectre
from kfnetlist.morphnet.netlist.vams.writer import write_vams

spectre_netlist = """\
subckt rc_lowpass (in_ out gnd)
R1 (in_ out) resistor value=1k
C1 (out gnd) capacitor value=100p
ends rc_lowpass
"""

netlist = parse_spectre(spectre_netlist)
print(write_vams(netlist))
```

Output:

```verilog
module rc_lowpass (in_, out, gnd);
  inout in_, out, gnd;
  resistor #(.value(1k)) R1 (.p(in_), .n(out));
  capacitor #(.value(100p)) C1 (.p(out), .n(gnd));
endmodule
```

## Supported Formats

| Format | Parser | Writer |
|---|---|---|
| HSPICE | `kfnetlist.morphnet.netlist.hspice.parser.parse_hspice` | `kfnetlist.morphnet.netlist.hspice.writer.write_hspice` |
| SPICE | `kfnetlist.morphnet.netlist.spice.parser.parse_spice` | `kfnetlist.morphnet.netlist.spice.writer.write_spice` |
| Xyce | `kfnetlist.morphnet.netlist.xyce.parser.parse_xyce` | `kfnetlist.morphnet.netlist.xyce.writer.write_xyce` |
| Spectre | `kfnetlist.morphnet.netlist.spectre.parser.parse_spectre` | `kfnetlist.morphnet.netlist.spectre.writer.write_spectre` |
| Spectre-SPICE | `kfnetlist.morphnet.netlist.spectre_spice.parser.parse_spectre_spice` | `kfnetlist.morphnet.netlist.spectre_spice.writer.write_spectre_spice` |
| Verilog-AMS | `kfnetlist.morphnet.netlist.vams.parser.parse_vams` | `kfnetlist.morphnet.netlist.vams.writer.write_vams` |
| SystemVerilog | `kfnetlist.morphnet.netlist.systemverilog.parser.parse_systemverilog` | `kfnetlist.morphnet.netlist.systemverilog.writer.write_systemverilog` |

Every parser and writer is also exported from `kfnetlist.morphnet.netlist`. See
[Parsing netlist formats](netlist_formats.md) and
[Converting between formats](format_conversion.md) for worked examples of each.

## Installation

```bash
pip install kfnetlist
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add kfnetlist
```

See [Getting Started](getting-started.md) for development setup instructions.

## License

kfnetlist.morphnet is licensed under the [Apache License 2.0](https://github.com/gdsfactory/kfnetlist/blob/main/LICENSE).
