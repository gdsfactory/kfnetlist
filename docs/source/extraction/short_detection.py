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
# # Short Detection
#
# The `kfnetlist.extract` module provides geometric short detection using
# boolean polygon intersection on `LayoutToNetlist` shape data.  After
# running klayout's L2N extraction, `detect_shorts()` finds unexpected
# overlaps between electrically distinct nets on the same layer.
#
# ## Functions
#
# | Function | Returns | Purpose |
# |----------|---------|---------|
# | `detect_shorts(l2n, ...)` | `list[ShortResult]` | Find polygon overlaps between different nets |
# | `shorts_to_rdb(shorts, ...)` | `rdb.ReportDatabase` | Convert to KLayout marker browser format |
# | `shorts_to_lyrdb(shorts, ...)` | `str` | Convert to lyrdb XML string |
#
# ## How it works
#
# For each layer (or a restricted set via `short_layers`), `detect_shorts()`
# collects every net's shapes and checks all pairwise intersections using
# `Region.__and__` (boolean AND).  Any non-empty intersection means the two
# nets overlap geometrically — a potential short.
#
# ```
# detect_shorts(l2n)
#     │
#     ├── discover layer regions from L2N
#     ├── for each layer:
#     │   ├── collect shapes per net
#     │   └── for each (net_a, net_b) pair:
#     │       └── overlap = shapes_a & shapes_b
#     │           └── if non-empty → ShortResult
#     └── return list[ShortResult]
# ```
#
# ## `ShortResult`
#
# Each detected short is returned as a dataclass:
#
# ```python
# @dataclass
# class ShortResult:
#     net_a: str        # first net name
#     net_b: str        # second net name
#     layer: str        # layer display name
#     overlap: Region   # the overlapping polygon region
# ```
#
# ## Parameters
#
# | Parameter | Type | Default | Description |
# |-----------|------|---------|-------------|
# | `l2n` | `kdb.LayoutToNetlist` | *(required)* | Completed extraction |
# | `short_layers` | `Sequence[LayerInfo] \| None` | `None` | Restrict to these layers (`None` = all) |
# | `circuit_name` | `str \| None` | `None` | Circuit to inspect (defaults to top cell) |
#
# ## Example
#
# ```python
# from kfnetlist.extract import detect_shorts, shorts_to_rdb
#
# shorts = detect_shorts(l2n)
#
# for s in shorts:
#     print(f"Short: {s.net_a} <-> {s.net_b} on {s.layer}")
#
# # Convert to KLayout report database for marker browser
# rdb = shorts_to_rdb(shorts, cell_name="TOP", dbu=0.001)
# rdb.save("shorts.lyrdb")
# ```
#
# ## Report output
#
# `shorts_to_rdb()` creates a `ReportDatabase` with items under the
# category `LVS.short`.  Each item includes a text description and the
# overlap polygon geometry, viewable in KLayout's marker browser.
#
# `shorts_to_lyrdb()` is a convenience wrapper that serializes to an
# lyrdb XML string.  This XML can be passed directly to the RDB filtering
# functions (`include_from_rdb_xml`, `exclude_from_rdb_xml`).
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | L2N parsing | [L2N Parsing](l2n_parsing.py) |
# | RDB filtering | [RDB Filtering](../guides/rdb_filtering.py) |
# | Open detection | [Open Detection](../guides/open_detection.py) |
# | Extraction overview | [Overview](overview.md) |
