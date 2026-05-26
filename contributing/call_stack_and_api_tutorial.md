# Call Stack & API Interaction Tutorial

This document traces how kfnetlist's internals work, from user-facing Python calls down through the Rust core and back. It serves as a guide for contributors who need to understand the execution flow.

---

## 1. Core Netlist Operations

### 1.1 Creating an Empty Netlist

```python
from kfnetlist import Netlist

nl = Netlist()
```

**Call stack:**

```
Python: Netlist()
  └─ Rust: Netlist::new()          # netlist.rs:104
       └─ Netlist::default()       # derives Default: empty IndexMap, empty Vecs
```

The `Netlist` struct holds three fields, all initially empty:
- `instances: IndexMap<String, NetlistInstance>` (order-preserving)
- `nets: Vec<Net>`
- `ports: Vec<NetlistPort>`

### 1.2 Adding Instances

```python
inst = nl.create_inst(
    name="mmi1",
    kcl="PDK",
    component="mmi1x2",
    settings={"width": 500, "gap": 250},
    na=1, nb=1,
)
```

**Call stack:**

```
Python: nl.create_inst("mmi1", "PDK", "mmi1x2", {"width": 500, "gap": 250})
  └─ Rust: Netlist::create_inst()                 # netlist.rs:165
       ├─ from_py_any::<serde_json::Value>(settings)  # lib.rs:79 — depythonize dict→JSON Value
       ├─ Validate na >= 1, nb >= 1                    # netlist.rs:180
       ├─ Build NetlistArray { na, nb }  (if na,nb != 0)
       ├─ Build NetlistInstance { kcl, component, settings, array, name }
       ├─ self.instances.insert(name, inst.clone())    # IndexMap preserves insertion order
       └─ Return inst clone to Python
```

**Key behaviors:**
- Settings are deserialized from Python dict to `serde_json::Value` via `pythonize`
- Array dimensions are validated: both must be >= 1
- If `na=0` and `nb=0`, the instance has no array (it's a scalar instance)
- The instance is stored in an `IndexMap` which preserves insertion order

### 1.3 Adding Top-Level Ports

```python
port_in = nl.create_port("o1")
port_out = nl.create_port("o2")
```

**Call stack:**

```
Python: nl.create_port("o1")
  └─ Rust: Netlist::create_port()      # netlist.rs:158
       ├─ Build NetlistPort { name: "o1" }
       ├─ self.ports.push(port.clone())
       └─ Return port clone to Python
```

Ports are appended to a `Vec` in insertion order. There is no uniqueness check — duplicate port names are valid (the extraction pipeline may create them from different sources before merging).

### 1.4 Creating Nets (Wiring)

```python
from kfnetlist import NetlistPort, PortRef

nl.create_net(
    NetlistPort(name="o1"),
    PortRef(instance="mmi1", port="o1"),
)
```

**Call stack:**

```
Python: nl.create_net(NetlistPort("o1"), PortRef("mmi1", "o1"))
  └─ Rust: Netlist::create_net(*ports)             # netlist.rs:201
       ├─ Iterate over Python args (PyAny)
       │   ├─ Try downcast to PortArrayRef         # checked FIRST (subclass of PortRef)
       │   │   ├─ Validate instance exists in self.instances
       │   │   ├─ If ia=1, ib=1 → collapse to PortRef (NetMember::Ref)
       │   │   ├─ Else validate array bounds (ia <= na, ib <= nb)
       │   │   └─ Push NetMember::ArrayRef
       │   ├─ Try downcast to PortRef
       │   │   ├─ Validate instance exists
       │   │   └─ Push NetMember::Ref
       │   └─ Try downcast to NetlistPort
       │       ├─ Validate port name exists in self.ports
       │       └─ Push NetMember::Port
       ├─ Net::from_members(members)               # net.rs
       │   └─ Sorts members on construction
       └─ self.nets.push(net)
```

**Key behaviors:**
- `PortArrayRef` is checked before `PortRef` because it's a Python subclass
- `PortArrayRef(ia=1, ib=1)` is automatically collapsed to a `PortRef` — this normalization prevents duplicate representations
- All references are validated against existing instances/ports
- Members are sorted inside the `Net` on construction

### 1.5 Adding Pre-Constructed Nets

```python
from kfnetlist import Net

net = Net([NetlistPort(name="o1"), PortRef(instance="mmi1", port="o1")])
nl.add_net(net)
```

**Call stack:**

```
Python: nl.add_net(net)
  └─ Rust: Netlist::add_net(&self, net)            # netlist.rs:269
       ├─ Extract members from net as PyList
       └─ self.create_net(list)                    # delegates to the same validation path
```

`add_net` is a convenience wrapper — it unpacks the `Net`'s members and feeds them through `create_net` for full validation.

---

## 2. Sorting & Normalization

```python
nl.sort()
```

**Call stack:**

```
Python: nl.sort()
  └─ Rust: Netlist::sort()                         # netlist.rs:316
       ├─ self.instances.sort_keys()               # lexicographic on instance names
       ├─ For each net:
       │   └─ net.sort_in_place()                  # sort members by derived Ord
       ├─ self.nets.sort()                         # sort nets lexicographically
       └─ self.ports.sort()                        # sort ports by name
```

**Member ordering** (from `Ord` derive on `NetMember` enum):

```
NetMember::Port < NetMember::Ref < NetMember::ArrayRef
```

Within each variant, sorting is lexicographic on fields (name, then instance, then port, then ia/ib).

Sorting is essential before serialization or comparison to ensure deterministic output.

---

## 3. Serialization

### 3.1 To JSON

```python
json_str = nl.to_json()
```

**Call stack:**

```
Python: nl.to_json()
  └─ Rust: Netlist::to_json()                      # netlist.rs:512
       ├─ self.to_wire() → NetlistWire             # netlist.rs:50
       │   ├─ Map instances → (name, NetlistInstanceWire)
       │   │   └─ NetlistInstanceWire omits the `name` field (it's the dict key)
       │   ├─ Clone nets
       │   └─ Clone ports
       └─ json_string(&wire)                       # lib.rs:61
            └─ serde_json::to_string()
```

### 3.2 From JSON

```python
nl2 = Netlist.from_json(json_str)
```

**Call stack:**

```
Python: Netlist.from_json(json_str)
  └─ Rust: Netlist::from_json(data)                # netlist.rs:517
       ├─ json_parse::<NetlistWire>(data)          # lib.rs:66
       │   └─ serde_json::from_str()
       └─ Netlist::from_wire(wire)                 # netlist.rs:62
            ├─ Map (name, wire) → (name, NetlistInstance::from_wire(name, wire))
            ├─ Move nets
            └─ Move ports
```

### 3.3 To/From Dict

The dict path uses `pythonize`/`depythonize` instead of `serde_json`:

```
to_dict()  → self.to_wire() → pythonize(py, &wire)    # lib.rs:72
from_dict() → depythonize(obj) → Netlist::from_wire()  # lib.rs:80
```

This produces native Python dicts/lists instead of JSON strings.

---

## 4. Instance Flattening

```python
nl.flatten_instances(["buffer1"])
```

**Call stack:**

```
Python: nl.flatten_instances(["buffer1"])
  └─ Rust: Netlist::flatten_instances(names)       # netlist.rs:282
       └─ For each inst_name in names:
            ├─ self.instances.shift_remove(&inst_name)   # remove from IndexMap
            ├─ Partition nets into:
            │   ├─ surviving: nets NOT touching inst_name → kept as-is
            │   └─ merged: collect non-instance members from touching nets
            ├─ self.nets = surviving
            └─ self.nets.push(Net::from_members(merged)) # one merged net
```

**Example:** If `buffer1` connects port `o1` to `mmi1.o2` and port `o2` to `mmi2.o1`:

```
Before:  Net[o1, buffer1.i]  Net[buffer1.o, mmi1.o2]
After:   Net[o1, mmi1.o2]  (buffer1 references removed, remaining members merged)
```

---

## 5. LVS-Equivalent Port Folding

```python
out = nl.lvs_equivalent(
    cell_name="top",
    equivalent_ports={"pad_cell": [["e1", "e2", "e3", "e4"]]},
)
```

**Call stack:**

```
Python: nl.lvs_equivalent("top", {"pad_cell": [["e1","e2","e3","e4"]]})
  └─ Rust: Netlist::lvs_equivalent()               # netlist.rs:329
       ├─ Parse equivalent_ports: HashMap<String, Vec<Vec<String>>>
       ├─ Build port_mapping (if not supplied):
       │   port_mapping["pad_cell"] = {"e1":"e1", "e2":"e1", "e3":"e1", "e4":"e1"}
       │   (first in each list is the canonical name)
       │
       ├─ nl = self.deep_clone()                   # never mutates original
       │
       ├─ Find matched instances (whose component is in equivalent_ports)
       │
       ├─ For each net, for each member touching a matched instance:
       │   ├─ Look up component → mapping → canonical port name
       │   ├─ Rewrite member's port name to canonical
       │   ├─ Build CanonicalKey from the rewritten member
       │   └─ Track: canonical_groups[key] → [net_indices...]
       │
       ├─ Union-Find over net indices:             # netlist.rs:557
       │   └─ Nets sharing the same CanonicalKey get unioned
       │
       ├─ Group nets by UF root → merge members (dedup via HashSet)
       │   ├─ Top-level ports are also remapped through cell_name's mapping
       │   └─ Each group → one new Net
       │
       ├─ Replace deleted nets with merged nets
       ├─ Deduplicate ports
       ├─ nl.sort()
       └─ Return new Netlist
```

**Example:**

```
Before:
  Net[top.in, pad1.e1]
  Net[top.vdd, pad1.e3]

equivalent_ports = {"pad_cell": [["e1", "e2", "e3", "e4"]]}
→ e2,e3,e4 all map to canonical "e1"

After:
  Net[top.in, top.vdd, pad1.e1]   # merged because e1 and e3 → same canonical
```

---

## 6. Port Checking

```python
from kfnetlist import PortCheck, check_connection

result = check_connection(port1, port2, tolerance=0.1, snapped=False)

if result & PortCheck.all_opposite == PortCheck.all_opposite:
    print("Ports face each other with matching width, layer, and type")
```

**Call stack:**

```
Python: check_connection(p1, p2, tolerance=0.1, angle_tolerance=0.01, snapped=False)
  └─ port_check.py:71
       ├─ Compute tol_um = p1.kcl.dbu * tolerance
       │
       ├─ Branch: snapped=True OR both ports have .trans (integer transforms)
       │   ├─ _get_trans(p1), _get_trans(p2)       # snap to integer transform
       │   ├─ Position: t1.disp == t2.disp → PortCheck.position
       │   └─ Orientation: (t1.angle - t2.angle) % 4
       │       ├─ == 2 → PortCheck.opposite (180°)
       │       └─ == 0 → PortCheck.same (0°)
       │
       ├─ Branch: complex transforms (DCplxTrans)
       │   ├─ _get_dcplx_trans(p1), _get_dcplx_trans(p2)
       │   ├─ Position: displacement distance < tol_um → PortCheck.position
       │   └─ Angle: (dt1.angle - dt2.angle) % 360
       │       ├─ |diff - 180| < angle_tolerance → PortCheck.opposite
       │       └─ |diff| < angle_tolerance → PortCheck.same
       │
       ├─ Cross-section comparison:
       │   ├─ p1.cross_section == p2.cross_section → cross_section + layer + width
       │   ├─ Else: compare main_layer → layer
       │   └─ Else: compare width → width
       │
       └─ p1.port_type == p2.port_type → PortCheck.port_type
```

The `PortLike` protocol requires: `trans`, `dcplx_trans`, `cross_section`, `port_type`, `kcl`. Any object implementing these attributes works (duck typing).

---

## 7. Full Extraction Pipeline

### 7.1 Entry Point

```python
from kfnetlist.extract import extract

netlists = extract(
    cell,
    wrap_kdb_instance=lambda i: Instance(kcl=cell.kcl, instance=i),
    port_types=("optical",),
    mark_port_types=("electrical", "RF", "DC"),
    equivalent_ports=None,  # auto-gathered from cell metadata
)
```

### 7.2 Complete Call Stack

```
extract(cell, wrap_kdb_instance, ...)                    # _algo.py:237
  │
  ├─[1] _gather_equivalent_ports(cell)                   # _algo.py:102
  │     └─ For cell + each called_cells():
  │         ├─ Check cell.lvs_equivalent_ports
  │         ├─ Check factory.lvs_equivalent_ports (library vs local, virtual vs normal)
  │         └─ Collect as dict[cell_name] → list[list[port_names]]
  │
  ├─[2] Build port_mapping from equivalent_ports
  │     └─ {"cell_name": {"port_x": "canonical_port", ...}, ...}
  │
  ├─[3] l2n_elec(cell, mark_port_types, connectivity, port_mapping)    # _l2n.py:43
  │     ├─ ly_elec = cell.kcl.layout.dup()               # duplicate layout
  │     ├─ For each cell in hierarchy:
  │     │   ├─ Determine preferred port per canonical group
  │     │   │   (pick first port with markable port_type)
  │     │   └─ Insert kdb.Text markers on port layers
  │     ├─ Build kdb.LayoutToNetlist with RecursiveShapeIterator
  │     ├─ Register layers, set up connectivity
  │     ├─ l2n.extract_netlist()
  │     ├─ l2n.check_extraction_errors()
  │     └─ Return l2n object
  │
  ├─[4] For each cell in [root, *called_cells]:
  │     │
  │     ├─[4a] get_optical_nets(cell, port_types, ...)   # _geometry.py:101
  │     │       ├─ Bucket cell ports by (snapped_x, snapped_y) + layer_key
  │     │       ├─ Bucket instance ports (with array expansion) the same way
  │     │       ├─ Cell-to-cell pairs: check_connection() with opposite mode
  │     │       ├─ Cell-to-instance pairs: check_connection() with same mode (snapped)
  │     │       ├─ Instance-to-instance pairs: check_connection() with opposite mode
  │     │       └─ Return list[Net]
  │     │
  │     ├─[4b] _build_cell_netlist(cell, optical_nets, l2n, ...)   # _algo.py:150
  │     │       ├─ nl = Netlist()
  │     │       ├─ Add instances: _create_inst_entry(nl, inst)
  │     │       │   └─ Resolve component name (factory_name or cell.name)
  │     │       │   └─ Serialize settings via serialize_setting()
  │     │       │   └─ nl.create_inst(name, kcl, component, settings, na, nb)
  │     │       ├─ Add ports: nl.create_port(port.name)
  │     │       ├─ Add optical nets: nl.add_net(net)
  │     │       ├─ Walk electrical circuit from L2N:
  │     │       │   └─ For each net in elec_circ.each_net():
  │     │       │       ├─ Pins → nl.create_port(pin.name()) → top-level port refs
  │     │       │       ├─ Subcircuit pins → match via RecursiveInstanceIterator
  │     │       │       │   └─ Compare specific_cplx_trans to find the right instance
  │     │       │       │   └─ Build PortRef or PortArrayRef
  │     │       │       └─ nl.create_net(*net_refs) if 2+ members
  │     │       ├─ Flatten unnamed / excluded-purpose instances
  │     │       ├─ nl.sort()
  │     │       └─ Return nl
  │     │
  │     └─[4c] If cell has equivalent_ports:
  │             └─ nl = nl.lvs_equivalent(cell_name, equivalent_ports, port_mapping)
  │
  └─ Return dict[cell_name → Netlist]
```

### 7.3 Optical Net Extraction Detail

The geometry module (`_geometry.py`) uses spatial bucketing to efficiently find port pairs:

```
                    Bucketing
                    ─────────
Cell ports:     {(x, y): {layer: [(index, port), ...]}}
Instance ports: {(x, y): {layer: [(i, j, ia, ib, inst, port), ...]}}

                    Pairing Rules
                    ─────────────
┌──────────────────┬────────────────┬─────────────────┐
│ Pair Type        │ Connection Mode│ Snapped?         │
├──────────────────┼────────────────┼─────────────────┤
│ cell ↔ cell      │ opposite (180°)│ no               │
│ cell ↔ instance  │ same (0°)      │ yes              │
│ instance ↔ inst  │ opposite (180°)│ no               │
└──────────────────┴────────────────┴─────────────────┘
```

The base check includes `position + layer + port_type` (and `width` unless `allow_width_mismatch=True`).

For array instances, each element `(ia, ib)` is expanded independently with its own specific transform.

### 7.4 Electrical L2N Detail

The L2N module (`_l2n.py`) works by:

1. **Duplicating the layout** to avoid modifying the original
2. **Stamping text markers** on port locations — only one port per equivalence group gets stamped (the first with a markable `port_type`)
3. **Configuring klayout connectivity** from the `kcl.connectivity` table (layer-to-layer connections)
4. **Running klayout's built-in extractor** which produces circuits with pins and subcircuit references
5. The resulting `kdb.LayoutToNetlist` object is consumed by `_build_cell_netlist` to map subcircuit pins back to kfnetlist instances

---

## 8. How Modules Interact

### Data Flow Diagram

```
User code
  │
  ▼
extract()  ──────────────────────────────────┐
  │                                          │
  ├─→ _gather_equivalent_ports()             │
  │     reads cell.lvs_equivalent_ports      │
  │     reads factory.lvs_equivalent_ports   │
  │                                          │
  ├─→ l2n_elec()                             │
  │     reads cell.ports (port_type filter)  │
  │     reads kcl.connectivity               │
  │     writes text markers to layout copy   │
  │     ↓                                    │
  │     kdb.LayoutToNetlist ─────────────────┤
  │                                          │
  ├─→ get_optical_nets()                     │
  │     reads cell.ports + inst.ports        │
  │     calls check_connection()             │
  │     ↓                                    │
  │     list[Net] ───────────────────────────┤
  │                                          │
  ├─→ _build_cell_netlist()  ◄───────────────┤
  │     calls serialize_setting()            │
  │     builds Netlist from:                 │
  │       - instances (from cell.insts)      │
  │       - ports (from cell.ports)          │
  │       - optical nets (from geometry)     │
  │       - electrical nets (from L2N)       │
  │     calls flatten_instances()            │
  │                                          │
  └─→ nl.lvs_equivalent()                   │
        rewrites port names                  │
        merges nets (union-find)             │
        returns new Netlist                  │
```

### Cross-Module Dependencies

```
_algo.py ─────→ _geometry.py (get_optical_nets)
    │  ─────→ _l2n.py (l2n_elec)
    │  ─────→ _settings.py (serialize_setting)
    │  ─────→ kfnetlist core (Netlist, Net, PortRef, etc.)
    │
_geometry.py ─→ port_check.py (PortCheck, check_connection)
    │  ─────→ kfnetlist core (Net, NetlistPort, PortRef, PortArrayRef)
    │
_l2n.py ──────→ klayout only (no kfnetlist imports)
    │
_settings.py ─→ klayout only (no kfnetlist imports)
```

---

## 9. Common Patterns for Contributors

### Adding a New Core Type

1. Define the Rust struct in `src/port.rs` or a new module
2. Add `#[pyclass]` and `#[pymethods]` for Python exposure
3. Register in `lib.rs` via `m.add_class::<YourType>()?`
4. Add type stub in `_native.pyi`
5. Re-export from `__init__.py`

### Adding a New Netlist Operation

1. Implement in `Netlist::your_method()` in `src/netlist.rs`
2. Add the `#[pymethods]` attribute
3. Add the type stub in `_native.pyi`
4. Add tests in `tests/test_netlist_model.py`

### Adding a New Extraction Feature

1. Decide if it's optical (geometry-based) or electrical (L2N-based)
2. For optical: modify `_geometry.py` and the bucketing/pairing logic
3. For electrical: modify `_l2n.py` (marker insertion) or `_algo.py` (circuit walking)
4. Thread new parameters through `extract()` in `_algo.py` and re-export from `extract/__init__.py`

### Understanding Snapshot Properties

The `instances`, `nets`, and `ports` properties on `Netlist` return **fresh copies** each time they're accessed. Mutating the returned dict/list does not affect the netlist. To modify the netlist, use the mutation methods (`create_inst`, `create_net`, `create_port`, `flatten_instances`, etc.).

```python
# This does NOT modify the netlist:
nl.instances["foo"] = some_instance  # mutates a temporary dict

# This DOES modify the netlist:
nl.create_inst("foo", kcl="PDK", component="straight")
```
