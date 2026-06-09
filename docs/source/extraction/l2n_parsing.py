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
# # L2N Parsing
#
# After running klayout's `LayoutToNetlist` extraction, `parse_l2n()` converts
# the result into a clean, JSON-serializable Python dictionary.  This makes it
# easy to inspect, store, or post-process extraction results without working
# directly with klayout's internal objects.
#
# ## Functions
#
# | Function | Returns | Purpose |
# |----------|---------|---------|
# | `parse_l2n(l2n, ...)` | `dict` | Convert L2N to a structured dict |
# | `l2n_to_json(l2n, ...)` | `str` | Convenience wrapper returning a JSON string |
#
# Both accept the same keyword arguments.

# %% [markdown]
# ## Basic usage
#
# ```python
# from klayout import db as kdb
# from kfnetlist.extract import parse_l2n, l2n_to_json
#
# # After extraction:
# result = parse_l2n(l2n)
#
# print(result["top_circuit"])    # name of the top cell
# print(result["dbu"])            # database unit in microns
# print(result["layers"])         # list of layer dicts
# print(result["circuits"])       # dict of circuit name -> circuit data
# ```
#
# Each circuit entry contains:
#
# - **`pins`** — top-level port names on the circuit
# - **`subcircuits`** — child instances with `name`, `circuit_ref`, and `transform`
# - **`nets`** — connectivity, with `name`, `pins`, `subcircuit_pins`, and
#   optionally `layer_to_polygons` / `layer_to_holes` for per-net shape data
#
# ## Parameters
#
# | Parameter | Type | Default | Description |
# |-----------|------|---------|-------------|
# | `l2n` | `kdb.LayoutToNetlist` | *(required)* | Completed L2N extraction |
# | `flatten` | `bool` | `False` | Collapse hierarchy into the top cell |
# | `include_layers` | `Sequence[LayerInfo] \| None` | `None` | Keep only nets on these layers |
# | `exclude_layers` | `Sequence[LayerInfo] \| None` | `None` | Drop nets only on these layers |
# | `include_instances` | `Sequence[str] \| None` | `None` | Keep only these subcircuit refs |
# | `exclude_instances` | `Sequence[str] \| None` | `None` | Remove these subcircuit refs |
#
# !!! note
#     Layer and instance filtering are ignored when `flatten=True`, since the
#     flattened netlist is detached from the L2N shape data.
#
# ## Flattening
#
# When `flatten=True`, all sub-circuits are collapsed into the top cell.  The
# resulting dict has a single entry in `circuits` and no per-net layer geometry:
#
# ```python
# flat = parse_l2n(l2n, flatten=True)
# assert list(flat["circuits"].keys()) == ["TOP"]
# ```
#
# ## JSON output
#
# `l2n_to_json()` is a thin wrapper that calls `parse_l2n()` and serializes
# the result with `json.dumps()`:
#
# ```python
# json_str = l2n_to_json(l2n, indent=2)
# ```
#
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Electrical extraction | [Electrical L2N](electrical_l2n.md) |
# | Short detection on L2N results | [Short Detection](short_detection.py) |
# | Extraction pipeline overview | [Overview](overview.md) |
