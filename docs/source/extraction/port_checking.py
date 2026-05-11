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
# # Port Checking
#
# `PortCheck` is an `IntFlag` bitmask for comparing two ports. The
# `check_connection()` function compares position, orientation, width, layer,
# cross-section, and port type — returning a bitmask that callers test against
# their required flags.
#
# ## PortCheck flags
#
# | Flag | Meaning |
# |------|---------|
# | `opposite` | Ports face opposite directions (180°) |
# | `same` | Ports face the same direction |
# | `width` | Port widths match |
# | `layer` | Ports are on the same layer |
# | `cross_section` | Cross-sections are identical (implies `layer` + `width`) |
# | `port_type` | Port types match (e.g. both "optical") |
# | `position` | Positions match (within tolerance) |
#
# ### Composite flags
#
# | Flag | Composition |
# |------|-------------|
# | `all_opposite` | `opposite \| width \| port_type \| layer` |
# | `all_overlap` | `width \| port_type \| layer` |

# %%
from kfnetlist import PortCheck

# %%
print("Individual flags:")
for flag in [
    PortCheck.opposite,
    PortCheck.same,
    PortCheck.width,
    PortCheck.layer,
    PortCheck.cross_section,
    PortCheck.port_type,
    PortCheck.position,
]:
    print(f"  {flag.name:>15s} = {flag.value}")

print("\nComposite flags:")
print(f"  all_opposite = {PortCheck.all_opposite.value} = {PortCheck.all_opposite}")
print(f"  all_overlap  = {PortCheck.all_overlap.value} = {PortCheck.all_overlap}")

# %% [markdown]
# ## Using the bitmask
#
# `check_connection()` returns an `int` bitmask. Test it with bitwise AND:
#
# ```python
# result = check_connection(port_a, port_b)
# if (result & PortCheck.all_opposite) == PortCheck.all_opposite:
#     # ports are a valid opposite-facing connection
#     ...
# ```
#
# ## Integer vs complex transforms
#
# `check_connection()` uses integer transforms (`kdb.Trans`) when both ports
# expose `trans`, giving exact comparison. When either port uses a complex
# transform (`kdb.DCplxTrans`), it falls back to floating-point comparison with
# configurable tolerances.
#
# | Parameter | Default | Purpose |
# |-----------|---------|---------|
# | `tolerance` | `0.1` | Position tolerance in dbu units |
# | `angle_tolerance` | `0.01` | Angle tolerance in degrees |
# | `snapped` | `False` | Force integer-transform comparison |
#
# ## Bitmask algebra
#
# Since `PortCheck` is an `IntFlag`, standard bitwise operations work:

# %%
# Build a custom required check
required = PortCheck.position | PortCheck.opposite | PortCheck.layer
print(f"Required: {required}")
print(f"Value: {required.value}")

# Test if a result satisfies requirements
simulated_result = (
    PortCheck.position | PortCheck.opposite | PortCheck.layer | PortCheck.width
)
passes = (simulated_result & required) == required
print(f"Passes: {passes}")

# %% [markdown]
# ## See Also
#
# | Topic | Where |
# |-------|-------|
# | Optical net extraction | [Optical Nets](optical_nets.md) |
# | Extraction pipeline | [Extraction Overview](overview.md) |
