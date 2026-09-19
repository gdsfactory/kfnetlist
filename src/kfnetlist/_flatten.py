"""Flattening a whole ``{cell name: netlist}`` mapping at once."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast

from ._native import Netlist

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

NetlistT = TypeVar("NetlistT", bound=Netlist)


def flatten_netlists(
    netlists: Mapping[str, NetlistT],
    cells: Sequence[str] | None = None,
    *,
    exclude: Sequence[str] | None = None,
    instance_cell_maps: Mapping[str, Mapping[str, str]] | None = None,
    recursive: bool = True,
    allow_unconnected_ports: bool = False,
    warn_skipped: bool = False,
    separator: str = ".",
) -> dict[str, NetlistT]:
    """Flatten every netlist of a hierarchy against the hierarchy itself.

    ``netlists`` is a ``{cell name: netlist}`` mapping — what
    :func:`kfnetlist.extract.extract` returns. Each netlist gets the selected
    instances replaced by the contents of their own cell's netlist; see
    :meth:`kfnetlist.Netlist.flatten` for the per-netlist semantics and for
    every keyword argument.

    Every netlist is flattened against the *original* mapping, so the result
    does not depend on iteration order. Cells that were inlined keep their own
    entry in the returned mapping — flattening a parent does not invalidate the
    child's netlist.

    ``instance_cell_maps`` maps a cell name to that cell's
    ``{instance name -> cell name}``. For each starting netlist, an explicit
    map selects only its listed instances; an empty map selects nothing. A
    missing cell entry considers all its instances, resolving their cells from
    :class:`~kfnetlist.PlacedNetlist` metadata when available. Plain
    :class:`~kfnetlist.Netlist` objects need maps to resolve their cell names.
    During recursive expansion, the same maps supply descendant cell names;
    descendants inherit selection from the instance being expanded.
    """
    netlists = dict(netlists)
    maps: Mapping[str, Mapping[str, str]] = instance_cell_maps or {}
    return {
        cell_name: cast(
            "NetlistT",
            netlist.flatten(
                netlists,
                cells,
                exclude=exclude,
                instance_cell_map=maps.get(cell_name),
                sub_instance_cell_maps=maps,
                recursive=recursive,
                allow_unconnected_ports=allow_unconnected_ports,
                warn_skipped=warn_skipped,
                separator=separator,
            ),
        )
        for cell_name, netlist in netlists.items()
    }
