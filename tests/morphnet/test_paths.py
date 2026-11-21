"""One OS-agnostic path resolver, the same answers as Rust's (shared case table)."""

import json
from pathlib import Path, PureWindowsPath

import pytest

from kfnetlist.morphnet.netlist.paths import is_absolute, posix_file, resolve_file

CASES = json.loads((Path(__file__).parents[1] / "data" / "path_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_the_shared_path_cases(case):
    assert posix_file(case["file"]) == case["posix"]
    assert is_absolute(case["file"]) is case["absolute"]
    resolved = resolve_file(case["file"], case["base"])
    assert isinstance(resolved, Path)
    assert posix_file(resolved) == case["resolved"]


def test_a_pathlib_path_is_accepted():
    assert posix_file(PureWindowsPath("data", "w.txt")) == "data/w.txt"
    assert posix_file(resolve_file(Path("w.txt"), Path("proj"))) == "proj/w.txt"
