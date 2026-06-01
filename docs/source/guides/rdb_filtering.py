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
# # RDB Filtering & Error Handling
#
# kfnetlist provides tools for filtering KLayout Report Databases (RDB) and
# working with LVS error categories.  These are useful for post-processing
# verification results — keeping only the errors you care about, generating
# summaries, or splitting a combined report by error type.
#
# ## LvsError
#
# The `LvsError` enum provides typed constants for all standard LVS error
# category paths.  Since it inherits from `StrEnum`, each value can be used
# directly as a string wherever a category path is expected.

# %%
from kfnetlist import LvsError

print(LvsError.SHORT)
print(LvsError.OPEN)
print(LvsError.NET_MISSING_IN_LAYOUT)

# All values are plain strings:
assert isinstance(LvsError.SHORT, str)
assert LvsError.SHORT == "LVS.short"

# %% [markdown]
# ### All error categories
#
# | Constant | Path string |
# |----------|-------------|
# | `INSTANCE_MISSING_IN_LAYOUT` | `LVS.instance.missing_in_layout` |
# | `INSTANCE_MISSING_IN_SCHEMATIC` | `LVS.instance.missing_in_schematic` |
# | `INSTANCE_COMPONENT_MISMATCH` | `LVS.instance.component_mismatch` |
# | `NET_MISSING_IN_LAYOUT` | `LVS.net.missing_in_layout` |
# | `NET_MISSING_IN_SCHEMATIC` | `LVS.net.missing_in_schematic` |
# | `PORT_MISSING_IN_LAYOUT` | `LVS.port.missing_in_layout` |
# | `PORT_MISSING_IN_SCHEMATIC` | `LVS.port.missing_in_schematic` |
# | `PORT_MISMATCH` | `LVS.port.mismatch` |
# | `OPEN` | `LVS.open` |
# | `SHORT` | `LVS.short` |

# %% [markdown]
# ## RDB filtering functions
#
# Three functions filter `ReportDatabase` objects by category path.  All
# return a **new** database — the original is not modified.
#
# | Function | Behaviour |
# |----------|-----------|
# | `include_from_rdb(rdb, paths)` | Keep only items matching any path |
# | `exclude_from_rdb(rdb, paths)` | Remove items matching any path |
# | `filter_rdb(rdb, predicate)` | Keep items where `predicate(path)` is `True` |
#
# Paths use **dot-boundary prefix semantics**: `"LVS.net"` matches
# `"LVS.net.missing_in_layout"` and `"LVS.net.missing_in_schematic"`,
# but does *not* match `"LVS.network"`.
#
# ### Example: keep only shorts
#
# ```python
# from kfnetlist import include_from_rdb, LvsError
#
# shorts_only = include_from_rdb(full_rdb, [LvsError.SHORT])
# ```
#
# ### Example: remove shorts and opens
#
# ```python
# from kfnetlist import exclude_from_rdb, LvsError
#
# structural_errors = exclude_from_rdb(full_rdb, [LvsError.SHORT, LvsError.OPEN])
# ```
#
# ### Example: custom predicate
#
# ```python
# from kfnetlist import filter_rdb
#
# net_errors = filter_rdb(full_rdb, lambda path: path.startswith("LVS.net"))
# ```
#
# ## XML variants
#
# The `_xml` suffixed functions operate on raw lyrdb XML strings instead of
# `ReportDatabase` objects.  These are backed directly by the Rust core
# and avoid klayout object round-trips:
#
# ```python
# from kfnetlist import include_from_rdb_xml, exclude_from_rdb_xml, filter_rdb_xml
#
# filtered_xml = include_from_rdb_xml(xml_string, ["LVS.short"])
# ```
#
# ## Error summary
#
# `error_summary()` produces a Markdown table from a `ReportDatabase`:
#
# ```python
# from kfnetlist import error_summary
#
# print(error_summary(rdb))
# ```
#
# Output:
#
# ```
# | cell | error type | description               |
# | ---- | ---------- | ------------------------- |
# | TOP  | LVS.short  | Short between VDD and VSS |
# ```
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Short detection (generates RDB) | [Short Detection](../extraction/short_detection.py) |
# | Open detection | [Open Detection](open_detection.py) |
# | Equivalent ports (LVS normalization) | [Equivalent Ports](equivalent_ports.py) |
