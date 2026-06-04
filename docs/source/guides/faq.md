# FAQ

## General

### What is the relationship between kfnetlist and kfactory?

kfnetlist is the netlist data model that kfactory uses internally for netlist
extraction and connectivity verification. It is published as a separate package
so that tools that only need netlist manipulation do not have to depend on
kfactory or klayout.

### Does kfnetlist require klayout?

The core package (`kfnetlist.Netlist`, `Net`, port types, serialization) has
**no runtime dependencies** at all.

The `kfnetlist.extract` subpackage and `check_connection()` require klayout,
since they work with layout geometry and klayout's `LayoutToNetlist` engine.

### Why is the core written in Rust?

Performance and type safety. Netlist operations (sorting, hashing, equality
checking, union-find for port equivalence) benefit from Rust's speed, and the
strong type system catches errors at compile time rather than runtime.

## Usage

### Why do `instances`, `nets`, and `ports` return new objects each time?

The properties return **fresh snapshots** to prevent accidental mutation of
internal state. If you need to modify the netlist, use the mutation API
(`create_inst`, `create_net`, `add_net`, etc.).

### Why does `sort()` matter?

Net member ordering and net ordering can vary between construction runs. If
you need to compare two netlists for equality, call `sort()` on both first to
get deterministic ordering.

### How do I compare two netlists?

```python
nl_a.sort()
nl_b.sort()
assert nl_a.to_dict() == nl_b.to_dict()
```

### Can I use kfnetlist types in Pydantic models?

Yes. All types implement `__get_pydantic_core_schema__` and work directly as
Pydantic v2 model fields.

## Extraction

### What does `wrap_kdb_instance` do?

The `extract()` function needs to convert raw `kdb.Instance` objects into
something with a `.name` attribute matching the instance names used in the
cell hierarchy. In kfactory, the standard shim is:

```python
lambda i: Instance(kcl=cell.kcl, instance=i)
```

### What are "equivalent ports"?

Ports that are electrically the same (e.g. two pins on the same metal pad).
`normalize()` folds them into a single canonical port so that netlist
comparison works correctly. See the [Equivalent Ports](equivalent_ports.py)
guide.

### Why are some instances flattened during extraction?

Unnamed instances (auto-generated routing, helper cells) and instances with
excluded purposes are flattened into the parent netlist. This keeps the
extracted netlist focused on the functional components that matter for
connectivity verification. See the [Instance Flattening](instance_flattening.py)
guide.
