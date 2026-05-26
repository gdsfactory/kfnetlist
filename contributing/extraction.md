# Extraction Guideline

This document explains how kfnetlist extracts netlists from layout data: how geometric shapes become nets, how layout cell references become netlist instances, and how ports are identified and connected.

---

## High-Level Pipeline

The extraction is orchestrated by `extract()` in `src/kfnetlist/extract/_algo.py`. It runs five stages for each cell in the hierarchy:

```
Layout cell
  |
  |--[1]--> Gather equivalent ports (from cell metadata / factories)
  |
  |--[2]--> Electrical L2N extraction (klayout engine)
  |
  |--[3]--> Optical net extraction (geometric port adjacency)
  |
  |--[4]--> Build cell netlist (merge instances + ports + both net types)
  |
  |--[5]--> LVS-equivalent folding (collapse equivalent ports, merge nets)
  |
  v
dict[cell_name -> Netlist]
```

---

## Stage 1: Equivalent Port Gathering

**Source**: `_algo.py:102-129` (`_gather_equivalent_ports`)

Before extraction begins, the pipeline collects **port equivalence groups** from cell metadata. These declare sets of ports that are electrically interchangeable (e.g., four pads on a pad cell that all connect to the same internal net).

For each cell in the hierarchy, the function checks:

1. `cell.lvs_equivalent_ports` (direct cell metadata)
2. `factory.lvs_equivalent_ports` (from the cell's factory registration in its KCL)
3. `virtual_factory.lvs_equivalent_ports` (for virtual/abstract cells)

The output is a mapping like:

```python
{
    "pad_cell": [["e1", "e2", "e3", "e4"]],
    "gnd_ring": [["gnd_n", "gnd_s", "gnd_e", "gnd_w"]],
}
```

Each inner list is an equivalence group. The **first** name in each group becomes the **canonical** name that all others collapse to.

This mapping is converted into a flat `port_mapping` dict:

```python
{"pad_cell": {"e1": "e1", "e2": "e1", "e3": "e1", "e4": "e1"}}
```

---

## Stage 2: Electrical L2N Extraction

**Source**: `src/kfnetlist/extract/_l2n.py:43-113` (`l2n_elec`)

This stage uses **klayout's built-in `LayoutToNetlist` engine** to extract electrical connectivity from shapes on metal/routing layers. The process:

### 2.1 Layout Duplication

The original layout is duplicated (`cell.kcl.layout.dup()`) so that marker insertion does not modify the user's layout.

>  Diogo: This might be a problem for heavier layouts. TODO

### 2.2 Port Marker Stamping

For each cell in the hierarchy, the function stamps `kdb.Text` labels at port locations on the duplicated layout. These text markers tell klayout which geometric shapes correspond to named ports.

Only ports whose `port_type` is in `mark_port_types` (default: `"electrical"`, `"RF"`, `"DC"`) are stamped. Within each equivalence group, only **one** port is stamped -- the first one with a markable port type -- and it gets the **canonical** name as its label.

```python
# For each port in the cell:
canonical = mapping.get(port.name, port.name)
if preferred_for_canonical.get(canonical) == port.name:
    c.shapes(port.layer_info).insert(
        kdb.Text(string=canonical, trans=port.trans)
    )
```

This ensures that equivalent ports resolve to the same net name in the extracted circuit.

### 2.3 Connectivity Configuration

Connectivity rules come from `cell.kcl.connectivity` -- a list of layer groups. Each group is a chain of layers that connect to each other:

```python
connectivity = [
    [metal1_info, via1_info, metal2_info],
    [metal2_info, via2_info, metal3_info],
]
```

> Diogo: This information is already readily available in the layerstack configuration of each gdsfactory's PDK. TODO

For each layer group, the module:

1. Registers every layer with `l2n.make_layer()` and `l2n.connect()` (intra-layer connectivity)
2. Chains adjacent layers with `l2n.connect(layer_i, layer_i+1)` (inter-layer connectivity)

### 2.4 Extraction

`l2n.extract_netlist()` runs klayout's geometric connectivity engine, which identifies overlapping/touching shapes on connected layers and groups them into circuits with pins and subcircuit references.

The output is a `kdb.LayoutToNetlist` object consumed by Stage 4.

---

## Stage 3: Optical Net Extraction (Geometry)

**Source**: `src/kfnetlist/extract/_geometry.py:101-236` (`get_optical_nets`)

Optical connections are determined purely from **geometric port adjacency** -- two ports connect when they are at the same position, on the same layer, and face each other.

### 3.1 Spatial Bucketing

Ports are bucketed into a spatial hash by their snapped `(x, y)` displacement and layer key:

- **Cell ports** (top-level ports of the current cell):

  ```python
  cell_ports[snapped_xy][layer_key] = [(index, port), ...]
  ```

- **Instance ports** (ports on placed sub-cell instances):

  ```python
  inst_ports[snapped_xy][layer_key] = [(i, j, ia, ib, inst, port), ...]
  ```

For **array instances**, each element `(ia, ib)` is expanded independently. The port's base transform is composed with the specific array element transform (`kdb.InstElement(inst, ia, ib).specific_trans()`), and each resulting position is bucketed separately.

### 3.2 Position Snapping

`_snapped_disp()` (`_geometry.py:77-90`) converts a port's transform to integer grid coordinates:

1. Uses `port.trans` directly if available, otherwise converts `port.dcplx_trans` via `kdb.ICplxTrans`
2. Snaps angle modulo 2 (only 0 and 1 matter for bucketing)
3. Clears the mirror flag
4. Returns `(disp.x, disp.y)` as the bucket key

### 3.3 Port Pair Matching

Three types of pairs are checked, each with different connection rules:

| Pair Type              | Connection Mode  | Snapped | What It Means                       |
|------------------------|------------------|---------|-------------------------------------|
| Cell port <-> Cell port       | **opposite** (180 deg) | no      | Two top-level ports face each other |
| Cell port <-> Instance port   | **same** (0 deg)       | yes     | A top-level port connects into an instance port facing the same direction |
| Instance port <-> Instance port | **opposite** (180 deg) | no      | Two instance ports face each other  |

**Why opposite vs. same?** Two waveguide ports that connect face each other (180 deg apart). But a cell's top-level port is defined pointing *outward*, while the instance port it connects to also points outward from its own cell. From the parent cell's reference frame, after placement, these two ports point in the *same* direction (both toward the cell boundary).

For each pair, `check_connection()` returns a `PortCheck` bitmask. The pair connects only if the result satisfies the required check:

```python
base_check = PortCheck.position | PortCheck.layer | PortCheck.port_type
if not allow_width_mismatch:
    base_check |= PortCheck.width

# Cell-to-cell and instance-to-instance: must face opposite
(check_connection(p1, p2) & check_opposite) == check_opposite

# Cell-to-instance: must face same direction (snapped)
(check_connection(cellport, instport, snapped=True) & check_same) == check_same
```

To handle rounding at bucket boundaries, the matching also searches a **3x3 neighborhood** around each position.

### 3.4 PortCheck Bitmask

`check_connection()` (`port_check.py:71-118`) compares two ports and returns a bitmask with these bits:

| Bit              | Value | Condition                                                   |
|------------------|-------|-------------------------------------------------------------|
| `position`       | 64    | Displacements match (integer) or distance < `dbu * tolerance` (float) |
| `opposite`       | 1     | Orientation differs by 180 deg                                  |
| `same`           | 2     | Orientation differs by 0 deg                                    |
| `width`          | 4     | Cross-section widths match                                  |
| `layer`          | 8     | Main layers are equivalent                                  |
| `cross_section`  | 16    | Full cross-section match (implies layer + width)            |
| `port_type`      | 32    | Port type strings match                                     |

Two code paths exist depending on transform precision:

- **Integer transforms** (`trans` is set, or `snapped=True`): exact displacement comparison, angle computed as `(t1.angle - t2.angle) % 4`
- **Complex transforms** (`dcplx_trans`): tolerance-based distance check, angle computed as `(dt1.angle - dt2.angle) % 360`

### 3.5 Output

Each matched pair produces one `Net` with two members:

```python
# Cell-to-cell
Net([NetlistPort("o1"), NetlistPort("o2")])

# Cell-to-instance
Net([NetlistPort("in"), PortRef(instance="wg1", port="o1")])

# Instance-to-instance
Net([PortRef(instance="wg1", port="o2"), PortRef(instance="mmi1", port="o1")])
```

Array instance ports produce `PortArrayRef(instance=..., port=..., ia=..., ib=...)` instead of `PortRef`.

---

## Stage 4: Building the Cell Netlist

**Source**: `_algo.py:150-234` (`_build_cell_netlist`)

This stage assembles a `Netlist` for each cell by combining instances, ports, and both types of extracted nets.

### 4.1 Instance Creation

For each instance placed in the cell (`cell.insts`), a `NetlistInstance` is added:

```python
def _create_inst_entry(nl, inst):
    component = inst.cell.factory_name if inst.cell.has_factory_name() else inst.cell.name
    kcl_name = inst.cell.library().name() if inst.cell.is_library_cell() else inst.cell.kcl.name
    settings = {k: serialize_setting(v) for k, v in inst.cell.settings.model_dump().items()}
    nl.create_inst(name=inst.name, kcl=kcl_name, component=component, settings=settings, na=inst.na, nb=inst.nb)
```

Key decisions:

- **Component name**: uses the factory name (registered parametric cell name) if available, otherwise falls back to the raw cell name.
- **KCL name**: identifies the library the cell came from. If it's a library cell, uses `library().name()`; otherwise uses the current KCL's name.
- **Settings**: serialized via `serialize_setting()`, which recursively converts klayout geometry objects to JSON-safe `"!#ClassName <str>"` format.
- **Array dimensions**: `na` and `nb` propagated directly for array instances.

### 4.2 Port Registration

Every port on the cell is registered as a top-level `NetlistPort`:

```python
for port in cell.ports:
    nl.create_port(port.name)
```

### 4.3 Optical Nets

The nets from Stage 3 are added directly:

```python
for net in optical_nets:
    nl.add_net(net)
```

### 4.4 Electrical Nets

The klayout L2N circuit for this cell (from Stage 2) is walked to extract electrical connectivity:

1. **Pin references** (top-level pins): each pin on the circuit's net becomes a `NetlistPort`
2. **Subcircuit pin references** (instance ports): each subcircuit pin is matched back to a kfnetlist instance by:
   - Using a `RecursiveInstanceIterator` scoped to a small box around the subcircuit's transform
   - Comparing `inst_el.specific_cplx_trans()` against the subcircuit's transform to find the exact match
   - Wrapping the matched klayout instance via `wrap_kdb_instance` to get the kfnetlist instance name
   - Creating `PortRef` (scalar) or `PortArrayRef` (array element, using `inst_el.ia()` / `inst_el.ib()`)

A net is only created if it has 2 or more members.

### 4.5 Instance Flattening

After nets are built, certain instances are removed ("flattened"):

- **Unnamed instances** (if `ignore_unnamed=True`): instances without user-assigned names
- **Excluded purposes**: instances whose `purpose` string matches `exclude_purposes`

Flattening (`netlist.rs:282-311`) works by:

1. Removing the instance from the netlist's instance map
2. Partitioning nets into:
   - **Surviving**: nets that don't reference the flattened instance (kept as-is)
   - **Touching**: nets that reference it -- their non-instance members are collected and merged into one new net

```
Before:  Net[o1, buffer1.i]  Net[buffer1.o, mmi1.o2]
         (buffer1 is flattened)
After:   Net[o1, mmi1.o2]
```

### 4.6 Sorting

`nl.sort()` normalizes the netlist for deterministic serialization and comparison:

- Instance names sorted lexicographically
- Members within each net sorted (Port < Ref < ArrayRef, then lexicographic on fields)
- Nets sorted lexicographically
- Ports sorted by name

---

## Stage 5: LVS-Equivalent Port Folding

**Source**: `src/netlist.rs:329-481` (`Netlist::lvs_equivalent`)

When a sub-cell declares equivalent ports (e.g., a pad cell with four interchangeable pads), nets touching those ports can be merged. This stage produces a **new** netlist (the original is never mutated).

### 5.1 Port Name Rewriting

For each net member that references a matched instance (one whose component has equivalent ports), the port name is rewritten to its canonical form:

```
PortRef("pad1", "e3") --> PortRef("pad1", "e1")   (because e3 maps to e1)
```

### 5.2 Canonical Grouping

Each rewritten member produces a `CanonicalKey`. Nets that share the same canonical key are grouped together.

### 5.3 Union-Find Merging

A union-find structure (`netlist.rs:557-593`) merges the groups: if two nets share any canonical key, they belong to the same connected component. All nets in a component are merged into a single net, with duplicate members removed.

```
Before:
  Net[top.in, pad1.e1]
  Net[top.vdd, pad1.e3]   (e3 is equivalent to e1)

After rewriting and merging:
  Net[top.in, top.vdd, pad1.e1]
```

### 5.4 Cleanup

Top-level ports are also remapped through the cell-level mapping (if the current cell itself has equivalent ports). The result is sorted and deduplicated.

---

## Connectivity Concepts

### Optical vs. Electrical

kfnetlist treats optical and electrical connectivity as fundamentally different:

| Aspect            | Optical (geometry)                    | Electrical (L2N)                      |
|-------------------|---------------------------------------|---------------------------------------|
| **Detection**     | Port position + orientation matching  | Shape overlap on conductive layers    |
| **Engine**        | Custom Python bucketing algorithm     | klayout's `LayoutToNetlist` engine    |
| **Layers**        | Port's cross-section main layer       | All layers in `kcl.connectivity`      |
| **Inter-layer**   | Not applicable (single-layer ports)   | Via/contact connections between metal layers |
| **Marker**        | None needed                           | `kdb.Text` stamped at port locations  |
| **Port types**    | Filtered by `port_types` param        | Filtered by `mark_port_types` param   |

Both types of nets end up in the same `Netlist` as `Net` objects. The distinction disappears after extraction.

### Layer Roles

Layers serve different roles in extraction:

- **Cross-section main layer**: identifies the routing layer of a port (used for optical matching)
- **Connectivity layers**: metal/via layers registered with klayout's L2N engine for electrical extraction
- **Port layer**: the specific `LayerInfo` where a port's text marker is stamped

### Array Instance Handling

Array instances (regular grids of the same cell) are handled specially:

- In **optical extraction**: each array element `(ia, ib)` is expanded with its own transform and bucketed independently. Port references use `PortArrayRef`.
- In **electrical extraction**: klayout handles arrays natively. The `inst_el.ia()` and `inst_el.ib()` indices are extracted from the `RecursiveInstanceIterator`.
- In **the Rust core**: `PortArrayRef(ia=1, ib=1)` is automatically collapsed to a plain `PortRef` during `create_net()`, since a 1x1 array is just a scalar instance.

---

## Data Flow Summary

```
                     extract(cell, ...)
                           |
            +--------------+--------------+
            |                             |
   _gather_equivalent_ports()      l2n_elec()
   reads: cell.lvs_equivalent_    reads: cell.ports (type filter)
          ports, factory metadata  reads: kcl.connectivity
   output: equivalent_ports dict   writes: Text markers on layout copy
   output: port_mapping dict       output: kdb.LayoutToNetlist
            |                             |
            +--------------+--------------+
                           |
                  For each cell in hierarchy:
                           |
            +--------------+--------------+
            |                             |
   get_optical_nets(cell)     _build_cell_netlist(cell, ...)
   reads: cell.ports              reads: cell.insts
   reads: inst.ports              reads: cell.ports
   uses: check_connection()       merges: optical nets + L2N nets
   output: list[Net]              calls: flatten_instances()
            |                     calls: sort()
            +--------> input ---->output: Netlist
                                          |
                                 lvs_equivalent()
                                 rewrites port names
                                 union-find merge nets
                                 output: Netlist (canonical)
                                          |
                                          v
                              dict[cell_name -> Netlist]
```
