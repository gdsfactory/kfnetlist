# ---
# jupyter:
#   jupytext:
#     formats: py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Connectivity Verification (LVS)
#
# Layout vs. Schematic (LVS) verification confirms that the physical layout
# of a circuit matches its intended connectivity. In photonic and electronic
# design, the **schematic** defines the intended connections between
# components, while the **extracted netlist** captures what was actually
# built in the layout.
#
# kfnetlist provides the building blocks for a complete LVS workflow:
# detect opens, compare against a reference, and find geometric shorts.
# This guide walks through each step and shows how to interpret the
# results.
#
# ## Verification methods
#
# | Method | LVS category | What it detects | Requires klayout? |
# |--------|-------------|-----------------|-------------------|
# | `detect_opens()` | Open circuit | Unconnected ports, singleton nets | No |
# | `find_net_difference(ref)` | Net mismatch | Missing / extra nets vs. reference | No |
# | `detect_shorts(l2n)` | Short circuit | Geometric polygon overlaps between nets | Yes |
# | `normalize()` | Pre-processing | Folds equivalent ports before comparison | No |
# | `check_connection()` | Port validation | Geometric port-pair alignment checks | Yes |

# %% [markdown]
# ## Step 1 — Build the netlists
#
# A typical LVS flow compares two netlists:
#
# - **Schematic netlist** — the golden reference (what you intended)
# - **Extracted netlist** — what was actually built (from layout extraction)
#
# Below we construct both by hand, deliberately introducing errors in the
# extracted netlist to demonstrate each detection method.

# %%
from kfnetlist import Netlist, NetlistPort, PortRef

# -- Schematic (golden reference) --
schematic = Netlist()
schematic.create_inst("mmi", kcl="PDK", component="mmi1x2", settings={"width": 500})
schematic.create_inst("wg1", kcl="PDK", component="straight", settings={"length": 10_000})
schematic.create_inst("wg2", kcl="PDK", component="straight", settings={"length": 10_000})

schematic.create_port("in")
schematic.create_port("out1")
schematic.create_port("out2")

schematic.create_net(NetlistPort(name="in"), PortRef(instance="mmi", port="o1"))
schematic.create_net(PortRef(instance="mmi", port="o2"), PortRef(instance="wg1", port="o1"))
schematic.create_net(PortRef(instance="mmi", port="o3"), PortRef(instance="wg2", port="o1"))
schematic.create_net(PortRef(instance="wg1", port="o2"), NetlistPort(name="out1"))
schematic.create_net(PortRef(instance="wg2", port="o2"), NetlistPort(name="out2"))
schematic.sort()

print(f"Schematic: {len(schematic.nets)} nets, {len(schematic.ports)} ports")

# %%
# -- Extracted netlist (from layout) --
# Errors introduced:
#   1. The mmi→wg2 connection is missing (open)
#   2. wg2.o1 is left dangling as a singleton net (stub)
#   3. An extra net connects wg2.o2 directly to "in" (unintended)

extracted = Netlist()
extracted.create_inst("mmi", kcl="PDK", component="mmi1x2", settings={"width": 500})
extracted.create_inst("wg1", kcl="PDK", component="straight", settings={"length": 10_000})
extracted.create_inst("wg2", kcl="PDK", component="straight", settings={"length": 10_000})

extracted.create_port("in")
extracted.create_port("out1")
extracted.create_port("out2")

extracted.create_net(NetlistPort(name="in"), PortRef(instance="mmi", port="o1"))
extracted.create_net(PortRef(instance="mmi", port="o2"), PortRef(instance="wg1", port="o1"))
# Missing: mmi.o3 → wg2.o1
extracted.create_net(PortRef(instance="wg2", port="o1"))  # singleton (dangling stub)
extracted.create_net(PortRef(instance="wg1", port="o2"), NetlistPort(name="out1"))
extracted.create_net(PortRef(instance="wg2", port="o2"), NetlistPort(name="out2"))
extracted.sort()

print(f"Extracted: {len(extracted.nets)} nets, {len(extracted.ports)} ports")

# %% [markdown]
# ## Step 2 — Pre-process with equivalent ports
#
# Before comparing, fold electrically-equivalent ports into canonical names
# using `normalize()`. This prevents false mismatches on components like
# pads where multiple pins connect to the same metal plane.
#
# In this example neither netlist has equivalent ports, so `normalize()` is
# a no-op — but it should always be part of the workflow.

# %%
equivalent_ports = {
    # "pad": [["p1", "p2"]],  # uncomment if your design has equivalent port groups
}

schematic_norm = schematic.normalize(cell_name="top", equivalent_ports=equivalent_ports)
extracted_norm = extracted.normalize(cell_name="top", equivalent_ports=equivalent_ports)

schematic_norm.sort()
extracted_norm.sort()
print("Normalization applied")

# %% [markdown]
# ## Step 3 — Detect opens
#
# `detect_opens()` inspects a **single** netlist for signs of incomplete
# wiring. It returns a dict with two keys:
#
# - **`unconnected_ports`** — top-level ports not referenced by any net
# - **`singleton_nets`** — nets with exactly one member (dangling stubs)

# %%
opens = extracted_norm.detect_opens()

print("Unconnected ports:", opens["unconnected_ports"])

singleton_nets = list(opens["singleton_nets"])
print(f"Singleton nets: {len(singleton_nets)}")
for net in singleton_nets:
    members = [
        f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
        for m in net
    ]
    print(f"  dangling: {' — '.join(members)}")

# %% [markdown]
# ### Interpreting open detection results
#
# | Result | LVS meaning | Severity | Typical cause |
# |--------|------------|----------|---------------|
# | Unconnected port | Definite open — a declared port is not wired | Error | Missing route to a top-level pin |
# | Singleton net | Potential open — a port is wired but goes nowhere | Warning | Broken connection, dangling stub |

# %% [markdown]
# ## Step 4 — Compare against reference
#
# `find_net_difference(reference)` compares two netlists by symmetric
# difference on their nets. It returns:
#
# - **`missing`** — nets in the reference that are absent from the
#   extracted netlist (connections that should exist but don't)
# - **`extra`** — nets in the extracted netlist that are absent from the
#   reference (unintended connections)

# %%
diff = extracted_norm.find_net_difference(schematic_norm)

missing = list(diff["missing"])
extra = list(diff["extra"])

print(f"Missing nets (in schematic but not in layout): {len(missing)}")
for net in missing:
    members = [
        f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
        for m in net
    ]
    print(f"  {' — '.join(members)}")

print(f"\nExtra nets (in layout but not in schematic): {len(extra)}")
for net in extra:
    members = [
        f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
        for m in net
    ]
    print(f"  {' — '.join(members)}")

# %% [markdown]
# ### Interpreting net differences
#
# | Result | LVS meaning | Severity | Typical cause |
# |--------|------------|----------|---------------|
# | Missing net | Open — a connection exists in the schematic but not in the layout | Error | Broken or missing route |
# | Extra net | Unintended connection — a connection exists in the layout but not in the schematic | Warning | Accidental coupling, routing error |

# %% [markdown]
# ## Step 5 — Detect geometric shorts (requires klayout)
#
# `detect_shorts(l2n)` finds polygon overlaps between electrically distinct
# nets on the same layer. This requires a completed klayout
# `LayoutToNetlist` extraction.
#
# ```python
# from kfnetlist.extract import detect_shorts
#
# shorts = detect_shorts(l2n)
#
# for s in shorts:
#     print(f"SHORT: {s.net_a} <-> {s.net_b} on {s.layer}")
#     print(f"  Overlap area: {s.overlap.area()} dbu^2")
#     print(f"  Bounding box: {s.overlap.bbox()}")
# ```
#
# ### ShortResult fields
#
# | Field | Type | Description |
# |-------|------|-------------|
# | `net_a` | `str` | Name of the first net |
# | `net_b` | `str` | Name of the second net |
# | `layer` | `str` | Layer display name where the overlap occurs |
# | `overlap` | `kdb.Region` | The overlapping polygon region |
#
# The `overlap` region can be used to compute the area of the short
# (`s.overlap.area()`), get its bounding box (`s.overlap.bbox()`), or
# visualize it in klayout's layout viewer.
#
# ### Filtering by layer
#
# Use the `short_layers` parameter to restrict detection to specific layers:
#
# ```python
# from klayout import db as kdb
#
# # Only check metal layers
# shorts = detect_shorts(
#     l2n,
#     short_layers=[kdb.LayerInfo(1, 0), kdb.LayerInfo(2, 0)],
# )
# ```

# %% [markdown]
# ## Step 6 — Build a verification summary
#
# Aggregate all findings into a single pass/fail report.

# %%
def build_verification_summary(opens_result, diff_result, shorts=None):
    """Aggregate verification results into a structured summary."""
    n_unconnected = len(opens_result["unconnected_ports"])
    n_singletons = len(list(opens_result["singleton_nets"]))
    n_missing = len(list(diff_result["missing"]))
    n_extra = len(list(diff_result["extra"]))
    n_shorts = len(shorts) if shorts else 0

    passed = (n_unconnected == 0 and n_missing == 0 and n_shorts == 0)

    return {
        "pass": passed,
        "unconnected_ports": n_unconnected,
        "singleton_nets": n_singletons,
        "missing_nets": n_missing,
        "extra_nets": n_extra,
        "shorts": n_shorts,
    }


summary = build_verification_summary(opens, diff)

status = "PASS" if summary["pass"] else "FAIL"
print(f"VERIFICATION RESULT: {status}")
print(f"  Opens: {summary['unconnected_ports']} unconnected port(s), "
      f"{summary['singleton_nets']} singleton net(s)")
print(f"  Net differences: {summary['missing_nets']} missing, "
      f"{summary['extra_nets']} extra")
print(f"  Shorts: {summary['shorts']}")

# %% [markdown]
# ## Exploring report data
#
# The dicts returned by `detect_opens()` and `find_net_difference()` are
# the primary "report database" in kfnetlist. Here is how to explore them
# programmatically.

# %% [markdown]
# ### Iterating net members
#
# Each net in the `missing` or `extra` lists is a `Net` object that can be
# iterated to inspect its members:

# %%
for net in list(diff["missing"]):
    port_refs = []
    netlist_ports = []
    for m in net:
        if isinstance(m, PortRef):
            port_refs.append(f"{m.instance}.{m.port}")
        elif isinstance(m, NetlistPort):
            netlist_ports.append(m.name)
    print(f"Missing net: ports={netlist_ports}, refs={port_refs}")

# %% [markdown]
# ### Classifying findings by category
#
# You can tag each finding with an LVS error category for structured
# reporting:

# %%
findings = []

for port_name in opens["unconnected_ports"]:
    findings.append({
        "category": "open",
        "severity": "error",
        "detail": f"Unconnected top-level port: {port_name}",
    })

for net in list(opens["singleton_nets"]):
    member = next(iter(net))
    label = (f"{member.instance}.{member.port}"
             if isinstance(member, PortRef) else member.name)
    findings.append({
        "category": "open",
        "severity": "warning",
        "detail": f"Singleton net (dangling stub): {label}",
    })

for net in list(diff["missing"]):
    members = [
        f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
        for m in net
    ]
    findings.append({
        "category": "net_mismatch",
        "severity": "error",
        "detail": f"Missing net: {' — '.join(members)}",
    })

for net in list(diff["extra"]):
    members = [
        f"{m.instance}.{m.port}" if isinstance(m, PortRef) else f"<{m.name}>"
        for m in net
    ]
    findings.append({
        "category": "net_mismatch",
        "severity": "warning",
        "detail": f"Extra net: {' — '.join(members)}",
    })

print(f"Total findings: {len(findings)}")
for f in findings:
    print(f"  [{f['severity'].upper():7s}] {f['category']:15s} | {f['detail']}")

# %% [markdown]
# ### Filtering by severity or category
#
# Since findings are plain dicts, standard Python filtering works:

# %%
errors_only = [f for f in findings if f["severity"] == "error"]
opens_only = [f for f in findings if f["category"] == "open"]

print(f"Errors: {len(errors_only)}, Opens: {len(opens_only)}")

# %% [markdown]
# ## Complete verification workflow
#
# Here is the full flow as a reusable pattern:
#
# ```python
# from kfnetlist import Netlist, NetlistPort, PortRef
#
# def verify_connectivity(
#     extracted: Netlist,
#     schematic: Netlist,
#     equivalent_ports: dict | None = None,
#     l2n=None,
#     short_layers=None,
# ) -> dict:
#     """Run all connectivity checks and return a structured report."""
#     eq = equivalent_ports or {}
#
#     # 1. Normalize equivalent ports
#     ext = extracted.normalize(cell_name="top", equivalent_ports=eq)
#     sch = schematic.normalize(cell_name="top", equivalent_ports=eq)
#     ext.sort()
#     sch.sort()
#
#     # 2. Detect opens in extracted netlist
#     opens = ext.detect_opens()
#
#     # 3. Compare against schematic
#     diff = ext.find_net_difference(sch)
#
#     # 4. Detect geometric shorts (if L2N available)
#     shorts = []
#     if l2n is not None:
#         from kfnetlist.extract import detect_shorts
#         shorts = detect_shorts(l2n, short_layers=short_layers)
#
#     # 5. Build summary
#     n_unconnected = len(opens["unconnected_ports"])
#     n_missing = len(list(diff["missing"]))
#     n_shorts = len(shorts)
#
#     return {
#         "pass": n_unconnected == 0 and n_missing == 0 and n_shorts == 0,
#         "opens": opens,
#         "diff": diff,
#         "shorts": shorts,
#         "summary": {
#             "unconnected_ports": n_unconnected,
#             "singleton_nets": len(list(opens["singleton_nets"])),
#             "missing_nets": n_missing,
#             "extra_nets": len(list(diff["extra"])),
#             "shorts": n_shorts,
#         },
#     }
# ```

# %% [markdown]
# ## Mapping to LVS error categories
#
# | kfnetlist finding | Traditional LVS category | Severity | Typical cause |
# |---|---|---|---|
# | Unconnected port | Open | Error | Missing route to a top-level pin |
# | Singleton net | Open (potential) | Warning | Dangling stub, broken connection |
# | Missing net (vs. reference) | Net mismatch / open | Error | Missing or broken route in layout |
# | Extra net (vs. reference) | Net mismatch | Warning | Unintended connection, routing error |
# | `ShortResult` | Short | Error | Metal overlap between distinct nets |
# | `PortCheck` failure | DRC / port alignment | Warning | Misaligned or wrong-width port |

# %% [markdown]
# ## Future: structured error reporting
#
# kfnetlist is working toward structured error reporting inspired by the
# [elvis](https://github.com/gdsfactory/kfactory) LVS engine. Planned
# capabilities include:
#
# - **Error accumulation** — collect all issues into a single result
#   container instead of throwing on first error
# - **KLayout RDB output** — serialize errors with geometric markers for
#   visualization in klayout's marker browser
# - **Error filtering pipeline** — deduplicate and merge transitive errors
#   (e.g. collapse a power-rail short from hundreds of raw overlaps into
#   one error group)
# - **Named nets** — give every net identity so shorts can report which
#   nets are involved
#
# See the
# [contributing docs](https://github.com/gdsfactory/kfnetlist/tree/main/contributing)
# for the full roadmap.

# %% [markdown]
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Open detection details | [Open Detection](open_detection.py) |
# | Short detection details | [Short Detection](../extraction/short_detection.py) |
# | Equivalent ports | [Equivalent Ports](equivalent_ports.py) |
# | Extraction pipeline | [Extraction Overview](../extraction/overview.md) |
# | FAQ | [FAQ](faq.md) |
