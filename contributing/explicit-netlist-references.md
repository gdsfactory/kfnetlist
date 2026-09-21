# Draft: explicit references between netlists

A plain netlist currently records the factory and settings of each instance but
cannot name another plain netlist in the document. This proposal adds that
relationship without requiring placement, generated layout cell names, UUIDs,
or a separate component registry. It is an alternative to the optional cell
field discussed in https://github.com/gdsfactory/kfnetlist/issues/22.

## Representation

```rust
pub enum NetlistInstance {
    Leaf(LeafNetlistInstance),
    Ref(RefNetlistInstance),
}
```

Both variants carry the existing `kcl`, `component`, `settings`, `info`, `array`,
and runtime `name` fields. `RefNetlistInstance` additionally requires a string
`netlist_id` in Rust, Python, and JSON. A leaf has no `netlist_id` field. Rust composes the
common fields inside `RefNetlistInstance.instance`; the wire format stays flat.
No discriminator field is added: presence of `netlist_id` selects the reference variant.
A present null, non-string reference, or unknown instance field is an error.

The document remains a mapping of identifiers to existing `Netlist` values:

```json
{
  "top": {
    "instances": {
      "arm_left": {"kcl": "pdk", "component": "make_arm", "settings": {"length": 10}, "netlist_id": "arm_10"},
      "arm_right": {"kcl": "pdk", "component": "make_arm", "settings": {"length": 10}, "netlist_id": "arm_10"}
    },
    "nets": [],
    "ports": []
  },
  "arm_10": {
    "instances": {
      "wg": {"kcl": "pdk", "component": "straight", "settings": {"length": 10}}
    },
    "nets": [],
    "ports": []
  }
}
```

Connections are omitted in this structural example. Their format is unchanged.
`netlist_id` is a key in this document, not a promise about a future GDS cell name.
Leaves need not be physically primitive: their internal netlist is simply not
supplied. Multiple references may share a definition. External library loading
and namespacing are separate future work, not implied by these local keys.

## Validation and comparison

`hierarchy_from_json` parses the complete document and validates every reference
and the absence of cycles. `validate_hierarchy` validates an existing mapping;
call it again after editing. A single `Netlist.from_json` cannot validate targets
without the containing document, but does enforce the instance wire format.

A reference identifies the supplied child definition. Traversal and flattening
must not silently reconstruct a different child from `component` and `settings`.
Those fields retain the existing factory-call description; this change introduces
no parent-to-child parameter override or regeneration semantics. Whether a
factory really produces that child cannot be established by schema validation
without executing the factory. That limitation should be explicit, not hidden
in a comparison routine.

Equality includes the variant and reference. A leaf and reference with identical
factory/settings are not equal, and references to different keys are not equal.
No names are silently ignored. Existing leaf comparison behavior is unchanged.
A canonical LVS projection or name-independent graph matching is a separate API
decision; it is not implemented by changing equality in this draft.

### Future idea: compare hierarchy using content hashes

Record for later discussion only; this is not implemented in this PR.
Build a comparison representation from leaves toward the root: canonicalize
each netlist's comparison-relevant contents, replace child references with the
children's content hashes, and hash the resulting parent. Replace document keys
and their references with those hashes in the comparison representation. This
applies to the `netlist_id` field.
Keep the original document and readable identifiers for diagnostics.

This could make equivalent hierarchies compare independently of document-local
IDs while retaining differences in the referenced circuits. Before implementing,
define the included fields, ordering and numeric normalization, and treatment
of instance/port names. Sorting JSON keys alone does not establish graph
isomorphism. Comparing equivalent circuits with different hierarchy boundaries
also needs a separate policy. Hash equality is a candidate equality check;
collision handling or comparison of canonical contents still needs a decision.

## Compatibility and operations

Python retains the callable `NetlistInstance` facade and `isinstance` interface.
Its existing constructor builds a `LeafNetlistInstance`. `from_dict`/`from_json`
return the appropriate concrete variant. Code requiring exact `type(x) is
NetlistInstance` must use `isinstance` or check a concrete variant instead.
Explicit variant loaders reject the
other variant. The two Python variants use the existing PyO3 subclass mechanism
only to preserve this interface; the Rust domain model is an enum.

`RefNetlistInstance(..., netlist_id="arm_10")` requires a reference. Existing
`Netlist.create_inst(...)` calls still create leaves; the new keyword-only `netlist_id`
creates a reference. `PlacedNetlist.create_inst` accepts the same keyword and
keeps its placed return type. Snapshots, normalization, and JSON preserve the variant.
`PlacedInstance` and `PlacedNetlist` retain their existing API and preserve an
explicit reference when converting/serializing a referenced plain netlist.
The physical `cell` name can differ from the logical document reference.

Flattening resolves explicit `netlist_id` values without side maps. Conflicting explicit
maps are errors. Legacy maps and placed-cell lookup remain available for old
instances. Selective flattening preserves references at retained boundaries;
existing flattening limitations, including arrays and empty child definitions,
still apply. A full recursive flatten raises if any explicit references remain;
it never silently returns a reference as a leaf. Selective/nonrecursive flatten
can intentionally retain references. An explicit `instance_cell_map` selects
starting instances by its keys (an empty map selects nothing); their descendants
inherit that selection. Unselected references remain intact. Recursive flattening
without cell filters still rejects selected references that cannot be expanded.

Rust struct-literal construction of the old `NetlistInstance` must change to
`NetlistInstance::Leaf(LeafNetlistInstance { ... })` or `.into()`. This is a Rust
source API change even though old JSON and Python construction remain supported.
The release/versioning decision belongs to review.

The draft does not change extraction defaults, kfactory schematic generation,
PIC YAML/protobuf formats, or simulator model selection. Producers can adopt
explicit references without any of those being redesigned in this PR.

## Verification

Focused checks cover Rust/Python variant construction, strict parsing, legacy
construction, JSON round trips, reference validation, equality, snapshots,
normalization, placed conversion, and flattening without side maps. Results are
recorded in the PR description. CI also runs the downstream kfactory test suite
with this branch installed in place of its normal kfnetlist dependency.
