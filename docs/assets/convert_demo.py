"""Convert a netlist between formats: ``python convert_demo.py SRC DST < netlist``.

Formats: spice, hspice, xyce, spectre, spectre_spice, vams.
"""

import sys

from kfnetlist.morphnet import netlist

src, dst = sys.argv[1:3]
parse = getattr(netlist, f"parse_{src}")
write = getattr(netlist, f"write_{dst}")
print(write(parse(sys.stdin.read())), end="")
