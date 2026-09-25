"""Optional kfactory extraction preserves hierarchy in plain netlists."""

import pytest

from kfnetlist import HierarchicalNetlist, PlacedInstance, RefNetlistInstance
from kfnetlist.extract import extract


@pytest.mark.parametrize("include_placement", [False, True])
def test_extracted_instances_reference_child_netlists(include_placement: bool) -> None:
    kf = pytest.importorskip("kfactory")
    kcl = kf.KCLayout(name=f"reference_extraction_{include_placement}")
    child = kcl.kcell("child")
    parent = kcl.kcell("parent")
    instance = parent << child
    instance.name = "first"

    cells = extract(
        parent,
        wrap_kdb_instance=lambda i: kf.Instance(kcl=kcl, instance=i),
        include_placement=include_placement,
    )
    if not include_placement:
        HierarchicalNetlist(cells).validate()
    extracted = cells[parent.name].instances["first"]
    assert isinstance(
        extracted, PlacedInstance if include_placement else RefNetlistInstance
    )
    assert extracted.netlist_id == child.name
