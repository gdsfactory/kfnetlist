# Port-Adjacency Extraction Call Stack

This document traces the full execution flow of geometric port-adjacency extraction in `_geometry.py`, from entry point down to individual comparison operations.

---

## Entry Point

```python
get_optical_nets(cell, port_types=("optical",), allow_width_mismatch=False)
```

Called from `_algo.py:294` inside the per-cell loop of `extract()`.

---

## Phase 1: Port Collection & Spatial Bucketing

### 1.1 Cell Port Collection (`_geometry.py:129-141`)

```
get_optical_nets(cell, ...)
  │
  ├─ for port in cell.ports:                         # iterate top-level ports
  │     ├─ skip if port.port_type not in port_types
  │     ├─ reject duplicate port.name (ValueError)
  │     │
  │     ├─ _snapped_disp(port.base)                  # → (x: int, y: int)
  │     │     ├─ if base.trans is set:
  │     │     │     t = base.trans
  │     │     ├─ else (dcplx_trans):
  │     │     │     t = ICplxTrans(dcplx_trans, dbu).s_trans()
  │     │     ├─ t.angle %= 2    # collapse 0/180 → 0, 90/270 → 1
  │     │     ├─ t.mirror = False
  │     │     └─ return (t.disp.x, t.disp.y)
  │     │
  │     ├─ _layer_key(port.base)                     # → "layer_datatype"
  │     │     └─ f"{cross_section.main_layer.layer}_{...datatype}"
  │     │
  │     └─ cell_ports[(x,y)][layer_key].append((index, port))
```

**Data structure produced:**

```
cell_ports: dict[
    (int, int),            # snapped (x, y) bucket key
    dict[
        str,               # layer key "layer_datatype"
        list[
            (int, _PortLike)   # (enumeration index, port)
        ]
    ]
]
```

### 1.2 Instance Port Collection (`_geometry.py:143-168`)

```
  ├─ for inst in cell.insts:
  │     │
  │     ├─ [ARRAY PATH] if inst.na > 1 or inst.nb > 1:
  │     │     for ia in range(inst.na):
  │     │       for ib in range(inst.nb):
  │     │         ├─ st = InstElement(inst.instance, ia, ib).specific_trans()
  │     │         ├─ for port in inst.ports:
  │     │         │     ├─ skip if port.port_type not in port_types
  │     │         │     ├─ tbase = port.base.transformed(st)     # compose transforms
  │     │         │     ├─ h = _snapped_disp(tbase)
  │     │         │     ├─ layer = _layer_key(tbase)
  │     │         │     ├─ tport = _TransformedPort(base=tbase, name=..., port_type=...)
  │     │         │     └─ inst_ports[h][layer].append((i, j, ia, ib, inst, tport))
  │     │
  │     └─ [SCALAR PATH] else:
  │           for port in inst.ports:
  │             ├─ skip if port.port_type not in port_types
  │             ├─ h = _snapped_disp(port.base)      # use base transform directly
  │             ├─ layer = _layer_key(port.base)
  │             └─ inst_ports[h][layer].append((i, j, 0, 0, inst, port))
```

**Data structure produced:**

```
inst_ports: dict[
    (int, int),
    dict[
        str,
        list[
            (int, int, int, int, _InstanceLike, _PortLike)
            #  i    j   ia   ib    instance      port
        ]
    ]
]
```

The array path creates a `_TransformedPort` wrapper that carries the composed transform (instance placement + array element offset). The scalar path reuses the port's own base transform.

---

## Phase 2: Check Configuration (`_geometry.py:170-174`)

```
  ├─ base_check = PortCheck.position + PortCheck.layer + PortCheck.port_type
  ├─ if not allow_width_mismatch:
  │     base_check += PortCheck.width
  ├─ check_same     = base_check + PortCheck.same       # for cell↔instance
  └─ check_opposite = base_check + PortCheck.opposite   # for cell↔cell, inst↔inst
```

These bitmasks define the minimum bits that `check_connection()` must return for a pair to be considered connected.

---

## Phase 3: Cell Port Pairing (`_geometry.py:176-213`)

```
  ├─ for h, cellport_layer_dict in cell_ports.items():
  │     for layer, cellports in cellport_layer_dict.items():
  │
  │       ┌─── 3.1 Gather additional cell ports at adjacent buckets ───┐
  │       │  additional = cell_ports[(hx+1, hy)][layer]                │
  │       │             + cell_ports[(hx, hy+1)][layer]                │
  │       │  (handles bucket-boundary rounding for cell↔cell pairs)    │
  │       └────────────────────────────────────────────────────────────┘
  │
  │       ┌─── 3.2 Gather instance ports in 3×3 neighborhood ─────────┐
  │       │  ports_near = []                                           │
  │       │  for x in (hx-1, hx, hx+1):                               │
  │       │    for y in (hy-1, hy, hy+1):                              │
  │       │      ports_near.extend(inst_ports[(x,y)][layer])           │
  │       └────────────────────────────────────────────────────────────┘
  │
  │       ┌─── 3.3 Cell↔Cell pairing (opposite, not snapped) ─────────┐
  │       │  for n, (_, cellport) in enumerate(cellports):             │
  │       │    for (_, cellport2) in cellports[n+1:] + additional:     │
  │       │      │                                                     │
  │       │      └─ check_connection(cellport.base, cellport2.base)    │
  │       │           ├─ port_check.py:71-118                          │
  │       │           ├─ compare displacements (integer or float)      │
  │       │           ├─ compare orientation → needs OPPOSITE (180°)   │
  │       │           ├─ compare layer, width, port_type               │
  │       │           └─ if (result & check_opposite) == check_opposite│
  │       │                → Net([NetlistPort(p1), NetlistPort(p2)])    │
  │       └────────────────────────────────────────────────────────────┘
  │
  │       ┌─── 3.4 Cell↔Instance pairing (same, snapped) ─────────────┐
  │       │  for (_, cellport) in cellports:                           │
  │       │    for (_, _, ia2, ib2, inst2, port2) in ports_near:       │
  │       │      │                                                     │
  │       │      └─ check_connection(cellport.base, port2.base,        │
  │       │                          snapped=True)                     │
  │       │           ├─ forces integer transform path                 │
  │       │           ├─ compare displacements → exact match           │
  │       │           ├─ compare orientation → needs SAME (0°)         │
  │       │           ├─ compare layer, width, port_type               │
  │       │           └─ if (result & check_same) == check_same        │
  │       │                → Net([NetlistPort(p1),                     │
  │       │                       _net_ref(inst2, port2.name, ia2, ib2)│
  │       │                      ])                                    │
  │       └────────────────────────────────────────────────────────────┘
```

**Why opposite vs. same?** Two waveguide ports that physically connect face each other (180° apart). But a cell's top-level port points *outward*, while the instance port it connects to also points outward from its own cell. After placement, both point the *same* direction from the parent cell's frame.

---

## Phase 4: Instance↔Instance Pairing (`_geometry.py:215-234`)

```
  └─ for h, inst_layer_dict in inst_ports.items():
        for layer, ports in inst_layer_dict.items():
  
          ┌─── 4.1 Adjacent bucket ports ─────────────────────────────┐
          │  additional = inst_ports[(hx+1, hy)][layer]               │
          │             + inst_ports[(hx, hy+1)][layer]               │
          └───────────────────────────────────────────────────────────┘
  
          ┌─── 4.2 Instance↔Instance pairing (opposite, not snapped) ┐
          │  for n, (_, _, ia, ib, inst, port) in enumerate(ports):   │
          │    for (_, _, ia2, ib2, inst2, port2) in                  │
          │        ports[n+1:] + additional:                          │
          │      │                                                    │
          │      └─ check_connection(port.base, port2.base)           │
          │           ├─ uses integer or float path (auto-detected)   │
          │           ├─ compare orientation → needs OPPOSITE (180°)  │
          │           └─ if (result & check_opposite) == check_opposite│
          │                → Net([_net_ref(inst, port, ia, ib),       │
          │                       _net_ref(inst2, port2, ia2, ib2)])  │
          └───────────────────────────────────────────────────────────┘
```

---

## Helper: `_net_ref` (`_geometry.py:93-98`)

```
_net_ref(inst, port_name, ia, ib)
  ├─ if inst.na > 0 and inst.nb > 0:
  │     └─ PortArrayRef(instance=inst.name, port=port_name, ia=ia, ib=ib)
  └─ else:
        └─ PortRef(instance=inst.name, port=port_name)
```

---

## Helper: `check_connection` (`port_check.py:71-118`)

This is the core comparison function called for every candidate pair:

```
check_connection(p1, p2, tolerance=0.1, angle_tolerance=0.01, snapped=False)
  │
  ├─ tol_um = p1.kcl.dbu * tolerance
  │
  ├─ [INTEGER PATH] if snapped or (p1.trans AND p2.trans are set):
  │     t1 = _get_trans(p1)    # snap dcplx_trans → Trans if needed
  │     t2 = _get_trans(p2)
  │     ├─ t1.disp == t2.disp         → +PortCheck.position
  │     └─ orientation = (t1.angle - t2.angle) % 4
  │         ├─ == 2  → +PortCheck.opposite
  │         └─ == 0  → +PortCheck.same
  │
  ├─ [FLOAT PATH] else (complex transforms):
  │     dt1 = _get_dcplx_trans(p1)
  │     dt2 = _get_dcplx_trans(p2)
  │     ├─ (dt1.disp - dt2.disp).length() < tol_um  → +PortCheck.position
  │     └─ angle_diff = (dt1.angle - dt2.angle) % 360
  │         ├─ |diff - 180| < angle_tolerance  → +PortCheck.opposite
  │         └─ |diff| < angle_tolerance        → +PortCheck.same
  │
  ├─ p1.cross_section == p2.cross_section   → +cross_section + layer + width
  │   ├─ else: main_layer equivalent?       → +layer
  │   └─ else: width equal?                 → +width
  │
  └─ p1.port_type == p2.port_type           → +port_type
```

---

## Spatial Bucketing Strategy

The algorithm uses a **spatial hash** on snapped integer coordinates:

```
             ┌─────────┬─────────┬─────────┐
             │(hx-1,   │(hx,     │(hx+1,   │
             │ hy+1)   │ hy+1)   │ hy+1)   │
             ├─────────┼─────────┼─────────┤
             │(hx-1,   │  (hx,   │(hx+1,   │   ← 3×3 neighborhood
             │  hy)    │   hy)   │  hy)    │     searched for
             ├─────────┼─────────┼─────────┤     cell↔instance
             │(hx-1,   │(hx,     │(hx+1,   │     pairs
             │ hy-1)   │ hy-1)   │ hy-1)   │
             └─────────┴─────────┴─────────┘
```

- **Cell↔Cell** and **Inst↔Inst** search only `(hx+1, hy)` and `(hx, hy+1)` — the upper-right neighbors — because the triangular iteration (`ports[n+1:]`) already covers same-bucket pairs and avoids double-counting.
- **Cell↔Instance** searches the full 3×3 neighborhood because the two collections are disjoint — no double-counting risk.

### Bucket Key Resolution

The bucket key is `(disp.x, disp.y)` in **database units** (integers). Since klayout's `Trans.disp` returns a `Vector` with integer components, ports at the exact same position always land in the same bucket. The ±1 neighborhood handles off-by-one from transform rounding (e.g. when a `DCplxTrans` is snapped to integer via `ICplxTrans.s_trans()`).

---

## Complexity

| Phase | Time | Space |
|-------|------|-------|
| Port collection | O(P) where P = total ports across all instances | O(P) |
| Bucketing | O(P) amortized hash insertions | O(P) |
| Pair matching | O(B × k²) where B = buckets, k = max ports per bucket | O(1) per pair |
| Total | O(P + B × k²) | O(P) |

In typical photonic circuits, k is very small (1-3 ports per bucket), making the pair matching effectively O(P). Pathological cases with many co-located ports degrade to O(P²).

---

## Why Not Use RTree Spatial Indexing?

An RTree (e.g. via the `rtree` or `shapely` packages) is the textbook answer for "find all objects whose bounding boxes overlap." It's worth explaining why the current spatial hash is a better fit here.

### Speed: Spatial Hash Wins for Point Data

Photonic ports are **point-like** — they have a position and orientation but no area. The spatial hash gives **O(1) amortized** bucket lookup on integer `(x, y)` keys. An RTree gives **O(log n)** per query with higher constant overhead (node splitting, tree balancing, bounding-box overlap tests at each tree level).

| Operation | Spatial Hash (current) | RTree |
|-----------|----------------------|-------|
| Build index | O(P) | O(P log P) |
| Query one port's neighbors | O(1) amortized + 9 bucket lookups | O(log P + k) |
| Total pair matching | O(P) typical (k ≈ 1–3) | O(P log P) typical |

For the typical photonic circuit (tens to hundreds of ports, 1–3 per co-located group), the hash is faster by a constant factor. RTree would only start to pay off with thousands of variable-size bounding boxes — that's not this problem.

### Precision: No Real Gain

The ±1 neighborhood scan in the current code is a workaround for integer snapping rounding at bucket boundaries (when a `DCplxTrans` is snapped to `Trans` via `ICplxTrans.s_trans()`, the resulting integer displacement can land ±1 database unit from the "true" position). An RTree with tolerance-inflated bounding boxes would eliminate this hack.

However, the neighborhood scan is a **coarse filter** — it only selects *candidates*. Every candidate pair still goes through `check_connection()`, which performs the precise tolerance-based comparison (displacement distance < `dbu * tolerance`, angle within `angle_tolerance`). The 3×3 scan may produce a few extra candidates, but it **never causes false positives or false negatives**. The precision lives in the bitmask check, not the spatial index.

### Dependency Cost

The core `kfnetlist` package has **zero runtime dependencies** (Rust-backed types only). Adding `rtree` (which depends on `libspatialindex`, a C library) or `shapely` (which depends on GEOS) would break this property for a marginal code-cleanliness improvement. Reimplementing an RTree from scratch would add substantial complexity for no measurable benefit.

### When RTree *Would* Make Sense

An RTree would be the right choice if:

- Ports had **variable-size bounding boxes** (e.g. wide polygonal ports where overlap area matters)
- The query was **range-based** ("find all ports within 10 µm") rather than exact-match
- Port density was **highly non-uniform** (dense clusters in some areas, sparse in others) at a scale where the fixed ±1 neighborhood is insufficient
- The layout had **millions of ports**, where O(P log P) with good cache locality beats O(P) with hash collisions

None of these conditions hold for photonic port adjacency. Ports are points, connections require exact co-location, density is uniform (1–3 per bucket), and port counts are moderate.

### A Better Improvement Path

If the ±1 neighborhood hack bothers you, a cleaner fix is to make `_snapped_disp` deterministic by always rounding in the same direction (e.g. `floor` instead of `round`). That guarantees co-located ports land in the same bucket, eliminating neighbor scanning entirely — without adding any dependency or algorithmic complexity.

---

## Complete Call Graph

```
extract()                                    # _algo.py:237
  └─ get_optical_nets(cell, ...)             # _geometry.py:101
       │
       ├─ [COLLECT]
       │   ├─ cell.ports iteration
       │   │   ├─ _snapped_disp(port.base)  # _geometry.py:77
       │   │   └─ _layer_key(port.base)     # _geometry.py:72
       │   │
       │   └─ cell.insts iteration
       │       ├─ [array] InstElement(...).specific_trans()
       │       │          port.base.transformed(st)
       │       │          _TransformedPort(...)
       │       ├─ _snapped_disp(...)
       │       └─ _layer_key(...)
       │
       ├─ [CONFIGURE CHECKS]
       │   └─ PortCheck bitmask assembly
       │
       ├─ [CELL↔CELL + CELL↔INSTANCE]
       │   ├─ neighborhood lookup (adjacent buckets + 3×3)
       │   ├─ check_connection(p1, p2)       # port_check.py:71
       │   │   ├─ _get_trans() or _get_dcplx_trans()
       │   │   └─ bitmask comparison
       │   └─ Net([NetlistPort, NetlistPort | PortRef])
       │
       ├─ [INSTANCE↔INSTANCE]
       │   ├─ adjacent bucket lookup
       │   ├─ check_connection(p1, p2)
       │   └─ Net([PortRef|PortArrayRef, PortRef|PortArrayRef])
       │       └─ _net_ref(inst, port, ia, ib)  # _geometry.py:93
       │
       └─ return list[Net]
```
