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
# ## Interpreting results
#
# Each `ShortResult` carries enough data to locate and measure the short:
#
# ```python
# for s in shorts:
#     # Area of the overlapping region (in dbu^2)
#     area = s.overlap.area()
#
#     # Bounding box for quick localization
#     bbox = s.overlap.bbox()
#
#     print(f"{s.net_a} <-> {s.net_b} on {s.layer}: "
#           f"area={area} dbu^2, bbox={bbox}")
# ```
#
# To count distinct shorted net pairs (a single pair can appear on
# multiple layers):
#
# ```python
# pairs = {(s.net_a, s.net_b) for s in shorts}
# print(f"{len(pairs)} distinct net pair(s) shorted")
# ```
#
# In LVS terms, every `ShortResult` is a **short circuit error** — two
# nets that should be electrically isolated have overlapping geometry.
#
# ## Building a short summary
#
# ```python
# def summarize_shorts(shorts):
#     """Build a one-line summary from detect_shorts() output."""
#     if not shorts:
#         return "PASS: no shorts detected"
#     pairs = {(s.net_a, s.net_b) for s in shorts}
#     layers = {s.layer for s in shorts}
#     return (
#         f"FAIL: {len(shorts)} short(s) between "
#         f"{len(pairs)} net pair(s) on {len(layers)} layer(s)"
#     )
# ```
#
# ## Filtering by layer
#
# Use the `short_layers` parameter to restrict detection to specific
# layers. This is useful when only certain metal layers carry routed
# signals:
#
# ```python
# from klayout import db as kdb
#
# # Only check M1 and M2
# shorts = detect_shorts(
#     l2n,
#     short_layers=[kdb.LayerInfo(1, 0), kdb.LayerInfo(2, 0)],
# )
# ```
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | LVS verification workflow | [LVS Verification](../guides/lvs_verification.py) |
# | L2N parsing | [L2N Parsing](l2n_parsing.py) |
# | Open detection | [Open Detection](../guides/open_detection.py) |
# | Extraction overview | [Overview](overview.md) |
