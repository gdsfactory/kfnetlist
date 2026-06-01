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
# from kfnetlist.extract import detect_shorts
#
# shorts = detect_shorts(l2n)
#
# for s in shorts:
#     print(f"Short: {s.net_a} <-> {s.net_b} on {s.layer}")
# ```
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | L2N parsing | [L2N Parsing](l2n_parsing.py) |
# | Open detection | [Open Detection](../guides/open_detection.py) |
# | Extraction overview | [Overview](overview.md) |
