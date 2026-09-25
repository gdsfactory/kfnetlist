"""Optional integration checks against kfactory with Instance.info support."""

import pytest

from kfnetlist import HierarchicalNetlist
from kfnetlist.extract import extract


@pytest.mark.parametrize("include_placement", [False, True])
@pytest.mark.parametrize("dtype", [False, True])
def test_kfactory_instance_info_extraction(include_placement, dtype) -> None:
    kf = pytest.importorskip("kfactory")
    if not hasattr(kf.Instance, "info"):
        pytest.skip("Requires kfactory with Instance.info")
    kcl = kf.KCLayout(name=f"info_extraction_{include_placement}_{dtype}")
    child = kcl.kcell("child")
    child.shapes(kf.kdb.LayerInfo(1, 0)).insert(kf.kdb.Box(0, 0, 1000, 1000))
    parent = kcl.dkcell("parent") if dtype else kcl.kcell("parent")
    first = parent << child
    first.name = "first"
    first.info["measure"] = "power"
    first.info["nested"] = {"values": [1, 2.0]}
    second = parent << child
    second.name = "second"
    second.info["measure"] = "spectrum"
    unnamed = parent << child

    cells = extract(
        parent,
        wrap_kdb_instance=lambda i: kf.Instance(kcl=kcl, instance=i),
        include_placement=include_placement,
    )
    result = cells[parent.name]
    if not include_placement:
        HierarchicalNetlist(cells).validate()
    expected = first.info.model_dump()
    first.info["measure"] = "changed"
    assert result.instances["first"].info == expected
    assert result.instances["second"].info == {"measure": "spectrum"}
    assert result.instances[unnamed.name].info == {}
    assert all(inst.netlist_id == child.name for inst in result.instances.values())
    assert type(result).from_json(result.to_json()) == result
    if not include_placement:
        assert (
            parent.netlist()[parent.name].instances["first"].info["measure"]
            == "changed"
        )
