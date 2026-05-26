# `_build_cell_netlist` Deep Dive

This document provides a detailed walkthrough of `_build_cell_netlist` (`_algo.py:150-234`), the function that assembles a `Netlist` for a single cell by merging instances, ports, optical nets, and electrical nets extracted from klayout's L2N engine.

---

## Purpose

`_build_cell_netlist` is the **central assembly point** in the extraction pipeline. It takes four pre-computed inputs and produces a single `Netlist` object that captures all connectivity (both optical and electrical) within one cell of the hierarchy.

It is called once per cell inside the `extract()` loop (`_algo.py:290-310`).

---

## Signature

```python
def _build_cell_netlist(
    cell: _CellLike,
    optical_nets: list[Net],
    l2n_elec_obj: kdb.LayoutToNetlist,
    wrap_kdb_instance: Callable[[kdb.Instance], _InstanceLike],
    *,
    ignore_unnamed: bool = False,
    exclude_purposes: list[str] | None = None,
) -> Netlist:
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `cell` | `_CellLike` | The cell being processed. Provides `.insts` (child instances), `.ports` (top-level ports), `.name`, and `.kcl` (the parent KCL with layout and dbu). |
| `optical_nets` | `list[Net]` | Pre-computed optical nets from geometric port adjacency (`get_optical_nets`). Each `Net` contains 2+ members connecting cell ports and/or instance ports. |
| `l2n_elec_obj` | `kdb.LayoutToNetlist` | The klayout L2N extraction result (from `l2n_elec`). Contains the extracted netlist with circuits, nets, pins, and subcircuit references. Shared across all cells in the hierarchy -- each cell looks up its own circuit by name. |
| `wrap_kdb_instance` | `Callable` | Converts a raw `kdb.Instance` (klayout's internal object) into a `_InstanceLike` with a `.name` matching the names used in kfnetlist. In kfactory, this is typically `lambda i: Instance(kcl=cell.kcl, instance=i)`. |
| `ignore_unnamed` | `bool` | If `True`, instances without user-assigned names are flattened out of the netlist. |
| `exclude_purposes` | `list[str] \| None` | Instance purpose strings to exclude (e.g., `"routing"`). Instances whose `.purpose` matches any entry are flattened. |

### Return Value

A fully assembled `Netlist` containing:
- All child instances as `NetlistInstance` entries
- All cell ports as `NetlistPort` entries
- All optical nets (passed through)
- All electrical nets (extracted from the L2N circuit)
- Minus any flattened instances and their absorbed nets

---

## Caller Context

```
extract(cell, ...)                              # _algo.py:237
  |
  |-- [per cell] get_optical_nets(cell, ...)    # produces optical_nets
  |-- [shared]   l2n_elec(cell, ...)            # produces l2n_elec_obj
  |
  +-- _build_cell_netlist(                      # _algo.py:291
  |       cell,
  |       optical_nets=...,
  |       l2n_elec_obj=l2n,
  |       wrap_kdb_instance=...,
  |   )
  |
  +-- nl.lvs_equivalent(...)                    # post-processing (Stage 5)
```

The `l2n_elec_obj` is computed **once** for the entire hierarchy and reused for every cell. Each cell looks up its own electrical circuit via `l2n_elec_obj.netlist().circuit_by_name(cell.name)`.

---

## Algorithm Walkthrough

The function executes five sequential phases:

```
Phase 1: Populate instances          (lines 166-167)
Phase 2: Register ports              (lines 168-169)
Phase 3: Add optical nets            (lines 170-171)
Phase 4: Walk electrical circuit     (lines 173-221)
Phase 5: Flatten & cleanup           (lines 223-234)
```

### Phase 1: Populate Instances

```python
for inst in cell.insts:
    _create_inst_entry(nl, inst)
```

Every child instance placed in the cell is added to the netlist. The helper `_create_inst_entry` (`_algo.py:132-147`) resolves the instance metadata:

```
_create_inst_entry(nl, inst)
  |
  +-- component = inst.cell.factory_name     # parametric cell name (preferred)
  |              or inst.cell.name           # raw cell name (fallback)
  |
  +-- kcl_name = inst.cell.library().name()  # if it's from an external library
  |              or inst.cell.kcl.name       # if it's local to this KCL
  |
  +-- settings = serialize each value via serialize_setting()
  |              (converts klayout geometry objects to "!#ClassName <str>" format)
  |
  +-- nl.create_inst(name, kcl, component, settings, na, nb)
```

At this point the netlist has all instances but no connectivity.

### Phase 2: Register Ports

```python
for port in cell.ports:
    nl.create_port(port.name)
```

Every top-level port on the cell becomes a `NetlistPort`. These are the external pins visible to the cell's parent.

Note: duplicate port names are allowed at this stage. The L2N circuit walking (Phase 4) may also call `nl.create_port()` for electrical pins, which can create additional ports.

### Phase 3: Add Optical Nets

```python
for net in optical_nets:
    nl.add_net(net)
```

The pre-computed optical nets from `get_optical_nets` are added directly. These were computed by geometric port adjacency (position + orientation matching on optical layers). See `port_adjacency_extraction.md` for the full algorithm.

`add_net()` delegates to `create_net()` internally, which validates that all referenced instances and ports exist in the netlist.

### Phase 4: Walk the Electrical Circuit

This is the most complex phase. It maps klayout's L2N circuit representation back to kfnetlist instances and ports.

#### 4.1 Circuit Lookup

```python
elec_circ = l2n_elec_obj.netlist().circuit_by_name(cell.name)
```

The L2N object contains a netlist with one `Circuit` per cell in the layout hierarchy. Each circuit is named after its originating cell. If this cell has no electrical connectivity (no conductive layers, or no text markers), `circuit_by_name` returns `None` and Phase 4 is skipped entirely.

#### 4.2 Net Iteration

```python
if elec_circ:
    for net in elec_circ.each_net():
        net_refs: list[NetlistPort | PortRef | PortArrayRef] = []
```

Each klayout net represents a connected group of shapes on conductive layers. For every net, the function collects kfnetlist-compatible references from two sources: **pins** (top-level) and **subcircuit pins** (instance-level).

#### 4.3 Pin References (Top-Level Ports)

```python
for pinref in net.each_pin():
    p = nl.create_port(pinref.pin().name())
    net_refs.append(p)
```

Each pin on the circuit's net corresponds to a text marker that was stamped during `l2n_elec` (Stage 2). The pin's name comes from the canonical port name (after equivalence resolution). A new `NetlistPort` is created and added to both the netlist's port list and the current net's references.

#### 4.4 Subcircuit Pin References (Instance Ports)

This is the trickiest part of the function. Klayout's L2N represents instance connections as **subcircuit pins** -- references to pins on child circuits. The challenge is mapping these back to kfnetlist instances, because:

1. Klayout's subcircuit uses its own `trans` (transform) and `circuit_ref` (circuit reference) to identify which instance it corresponds to
2. The internal layout may have different cell indices than the user-facing layout
3. Array instances require matching the specific array element `(ia, ib)`

The matching algorithm uses a `RecursiveInstanceIterator` as a spatial lookup:

```
for subc_pin in net.each_subcircuit_pin():
  |
  +-- subc = subc_pin.subcircuit()        # the L2N subcircuit object
  +-- circ_ref = subc.circuit_ref()       # what circuit type it refers to
  +-- circ = subc.circuit()               # parent circuit
  +-- pin = subc_pin.pin()                # which pin on the subcircuit
  |
  +-- Build a RecursiveInstanceIterator:
  |     scope:    cell.kcl.layout (the user-facing layout)
  |     start:    the cell matching circ.name
  |     box:      a tiny 2x2 dbu box centered at the subcircuit's transform origin
  |     targets:  [cell index of circ_ref in user layout]
  |     depth:    0 (only direct children, no recursion)
  |     mode:     overlapping
  |
  +-- For each matching instance element:
        |
        +-- Compare inst_el.specific_cplx_trans() == subcircuit's trans
        +-- Verify pin.name() != ""  (skip unnamed pins)
        |
        +-- If match found:
              +-- wrapped = wrap_kdb_instance(inst_el.inst())
              +-- If inst_el.ia() < 0:  (scalar instance)
              |     -> PortRef(instance=wrapped.name, port=pin.name())
              +-- Else:  (array element)
              |     -> PortArrayRef(instance=wrapped.name, port=pin.name(),
              |                     ia=inst_el.ia(), ib=inst_el.ib())
              +-- break  (first match wins)
```

##### Why a RecursiveInstanceIterator?

The L2N engine works on a **duplicated layout** (`_l2n.py` calls `cell.kcl.layout.dup()`), so its internal cell indices don't match the user-facing layout. The iterator bridges this gap:

1. It searches the **user-facing layout** (`cell.kcl.layout`)
2. Starts from the cell named `circ.name` (the parent circuit's cell)
3. Uses a tiny bounding box at the subcircuit's origin as a spatial filter
4. Targets the cell index that corresponds to `circ_ref` in the user layout (resolved via `l2n_elec_obj.internal_layout().cell(circ_ref.cell_index).name`)

##### The Transform Comparison

```python
inst_el.specific_cplx_trans()
    == kdb.ICplxTrans(trans=subc.trans, dbu=cell.kcl.dbu)
```

This is the definitive match criterion. Even if multiple instances of the same cell exist at nearby positions, only the one whose specific complex transform exactly matches the subcircuit's transform is the correct match.

The `ICplxTrans` constructor converts the subcircuit's `Trans` (integer transform) into a complex transform using the cell's database unit (`dbu`) for comparison with `specific_cplx_trans()`, which always returns an `ICplxTrans`.

##### Scalar vs. Array Detection

```python
if inst_el.ia() < 0:
    # Scalar instance: ia < 0 means "not an array element"
    net_refs.append(PortRef(instance=wrapped.name, port=pin.name()))
else:
    # Array element: ia >= 0, ib >= 0 give the element indices
    net_refs.append(PortArrayRef(
        instance=wrapped.name, port=pin.name(),
        ia=inst_el.ia(), ib=inst_el.ib(),
    ))
```

Klayout's `InstElement.ia()` returns `-1` for non-array instances. For array elements, `ia()` and `ib()` return the 2D indices within the array.

Note: `PortArrayRef(ia=1, ib=1)` is automatically collapsed to a plain `PortRef` by the Rust core's `create_net()`, since a 1x1 array is semantically a scalar instance.

#### 4.5 Net Creation

```python
if len(net_refs) > 1:
    nl.create_net(*net_refs)
```

A net is only created if it connects **two or more** members. Single-member nets are dropped -- they represent unconnected pins or dangling stubs in the L2N circuit.

### Phase 5: Flatten and Cleanup

After all nets are built, certain instances are removed from the netlist:

```python
inst_names: set[str] = set()
if ignore_unnamed:
    inst_names |= {inst.name for inst in cell.insts if not inst.is_named()}
if exclude_purposes:
    inst_names |= {
        inst.name for inst in cell.insts if inst.purpose in exclude_purposes
    }
nl.flatten_instances(list(inst_names))
for inst_name in inst_names:
    nl.instances.pop(inst_name, None)
nl.sort()
return nl
```

#### 5.1 Identifying Instances to Flatten

Two criteria select instances for removal:

| Criterion | When Active | What It Catches |
|-----------|-------------|-----------------|
| `ignore_unnamed` | `ignore_unnamed=True` | Instances without user-assigned names (`inst.is_named()` returns `False`). These are typically auto-placed routing or filler cells. |
| `exclude_purposes` | `exclude_purposes` is non-empty | Instances whose `.purpose` string matches an entry. Common uses: filtering out `"routing"` or `"padding"` instances. |

#### 5.2 Flattening Mechanics

`nl.flatten_instances(list(inst_names))` (Rust: `netlist.rs:282-311`) works by:

1. **Removing** each named instance from the `IndexMap`
2. **Partitioning** nets into:
   - **Surviving**: nets that don't reference any flattened instance (kept as-is)
   - **Touching**: nets that reference a flattened instance -- their non-instance members are collected
3. **Merging** all collected non-instance members from touching nets into a single new net

```
Before:  Net[o1, buffer1.i]  Net[buffer1.o, mmi1.o2]
         (buffer1 is being flattened)

Step 1:  Remove buffer1 from instances
Step 2:  Net[o1, buffer1.i] → touching (collect: o1)
         Net[buffer1.o, mmi1.o2] → touching (collect: mmi1.o2)
Step 3:  Merged net: Net[o1, mmi1.o2]

After:   Net[o1, mmi1.o2]
```

#### 5.3 Cleanup

After flattening, `nl.instances.pop(inst_name, None)` removes any remaining instance entries. This handles edge cases where `flatten_instances` might not fully remove all traces.

Finally, `nl.sort()` normalizes the netlist for deterministic serialization:
- Instance names sorted lexicographically
- Net members sorted (Port < Ref < ArrayRef, then by fields)
- Nets sorted lexicographically
- Ports sorted by name

---

## Data Flow Diagram

```
                cell.insts                    cell.ports
                    |                             |
            [Phase 1: create instances]   [Phase 2: create ports]
                    |                             |
                    v                             v
              +-------------------------------------------+
              |              Netlist (nl)                  |
              |  instances: {name -> NetlistInstance}      |
              |  ports:     [NetlistPort, ...]             |
              |  nets:      []  (empty so far)             |
              +-------------------------------------------+
                    |                  |
    [Phase 3: optical nets]    [Phase 4: electrical nets]
            |                          |
    optical_nets (input)       l2n_elec_obj.netlist()
            |                    .circuit_by_name(cell.name)
            |                          |
            |                   +------+------+
            |                   |             |
            |              each_pin()    each_subcircuit_pin()
            |                   |             |
            |              NetlistPort   RecursiveInstanceIterator
            |                   |         -> transform match
            |                   |         -> wrap_kdb_instance
            |                   |         -> PortRef / PortArrayRef
            |                   |             |
            |                   +------+------+
            |                          |
            v                          v
              +-------------------------------------------+
              |           Netlist (nl) -- populated        |
              |  nets: [optical..., electrical...]         |
              +-------------------------------------------+
                              |
                    [Phase 5: flatten & cleanup]
                              |
                    remove unnamed / excluded
                    merge touching nets
                    sort()
                              |
                              v
              +-------------------------------------------+
              |         Netlist (nl) -- final              |
              +-------------------------------------------+
```

---

## Edge Cases and Gotchas

### No Electrical Circuit

If `circuit_by_name(cell.name)` returns `None`, Phase 4 is skipped entirely. This happens for cells with no conductive layers or no text markers (e.g., purely optical cells). The netlist will contain only optical nets.

### Empty Pin Names

```python
if pin.name() != "":
```

Subcircuit pins with empty names are skipped. These arise when klayout's L2N engine creates internal pins that don't correspond to any stamped text marker. Including them would create meaningless connections.

### Internal vs. User Layout Cell Indices

The L2N object maintains an **internal layout** that is separate from the user-facing layout (because `l2n_elec` duplicates the layout before marker insertion). Cell indices differ between the two. The bridge expression:

```python
cell.kcl[
    l2n_elec_obj.internal_layout().cell(circ_ref.cell_index).name
].cell_index()
```

Translates: "take the circuit reference's cell index in the internal layout, look up the cell by name, then find that cell's index in the user layout."

### Multiple Instances at the Same Position

The `RecursiveInstanceIterator` may return multiple hits for the tiny bounding box. The transform comparison ensures only the correct instance is matched:

```python
if inst_el.specific_cplx_trans() == kdb.ICplxTrans(trans=subc.trans, dbu=cell.kcl.dbu):
```

The `break` after a successful match prevents duplicate references.

### Flattening After Net Creation

Flattening happens **after** all nets are created, not during. This means the instance must exist in the netlist when nets reference it (validated by `create_net`), and is only removed afterward. The Rust `flatten_instances` method handles the net surgery.

### Double Cleanup

The code calls both `nl.flatten_instances(list(inst_names))` and then `nl.instances.pop(inst_name, None)`. The `flatten_instances` call handles net merging and removes the instance, while the `pop` call is a safety net ensuring the instance is definitely removed from the `instances` dict even if `flatten_instances` didn't process it (e.g., if the instance had no touching nets).
