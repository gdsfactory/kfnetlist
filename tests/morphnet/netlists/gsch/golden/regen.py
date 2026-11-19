"""Regenerate the nyancad golden netlists for ``test_gsch_export.py``.

Runs nyancad's netlister (``inspice_netlist_from_api`` over a ``FileAPI`` project
holding the ``.gsch`` fixtures and ``models.nyanlib``) for every fixture and
simulator, and writes ``<fixture>.<sim>.cir`` (ngspice, xyce) or ``.scs`` (vacask).
Fixtures nyancad cannot netlist are listed in ``SKIPPED.txt`` with the error.

InSpice makes relative library paths absolute against the working directory; that
prefix is stripped so the goldens hold the ``models.nyanlib`` paths verbatim.

Run from the repository root:

    uv run --no-project --python 3.12 --with 'InSpice==1.7.0.7' \
        --with httpx --with ../gdsfactoryplus/frontend/mosaic/python/nyancad \
        python tests/morphnet/netlists/gsch/golden/regen.py
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from InSpice.Spice.Simulator import Simulator  # ty: ignore[import-not-found]
from nyancad.api import FileAPI  # ty: ignore[import-not-found]
from nyancad.netlist import inspice_netlist_from_api  # ty: ignore[import-not-found]

GOLDEN = Path(__file__).parent
FIXTURES = GOLDEN.parent
SIMS = {
    "ngspice": ("NgSpice", "cir"),
    "xyce": ("Xyce", "cir"),
    "vacask": ("VACASK", "scs"),
}
CORNERS = {"ihp_hier_top": ["mos_ff"]}  # every other fixture: sections[0]


def render(circuit, sim: str) -> str:
    if sim == "vacask":  # as nyancad's tests do: the real VACASK backend, no run
        simulation = Simulator.factory(simulator="vacask").simulation(circuit)
        simulation.operating_point(run=False)
        return str(simulation)
    return circuit.str(simulator=sim)


async def main() -> None:
    skipped = []
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        shutil.copy(FIXTURES / "models.nyanlib", project)
        for path in sorted(FIXTURES.glob("*.gsch")):
            shutil.copy(path, project)
        api = FileAPI(project)
        for path in sorted(FIXTURES.glob("*.gsch")):
            for sim, (name, ext) in SIMS.items():
                try:
                    circuit = await inspice_netlist_from_api(
                        api, path.name, corners=CORNERS.get(path.stem), sim=name
                    )
                    text = render(circuit, sim)
                except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                    skipped.append(f"{path.stem}.{sim}: {type(exc).__name__}: {exc}")
                    continue
                text = text.replace(f"{Path.cwd()}/", "")
                (GOLDEN / f"{path.stem}.{sim}.{ext}").write_text(text)
    (GOLDEN / "SKIPPED.txt").write_text("".join(f"{s}\n" for s in skipped))


if __name__ == "__main__":
    asyncio.run(main())
