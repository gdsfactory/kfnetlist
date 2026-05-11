"""Port-pair connection check used by :mod:`kfnetlist.extract`."""

from __future__ import annotations

from enum import IntFlag, auto
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from klayout import db as kdb


class PortCheck(IntFlag):
    """Bitmask of pairwise port-port comparison results."""

    opposite = auto()
    same = auto()
    width = auto()
    layer = auto()
    cross_section = auto()
    port_type = auto()
    position = auto()
    all_opposite = opposite | width | port_type | layer
    all_overlap = width | port_type | layer


class _CrossSectionLike(Protocol):
    main_layer: kdb.LayerInfo
    width: int


class _KCLLike(Protocol):
    dbu: float


class PortLike(Protocol):
    """Duck-typed shape consumed by :func:`check_connection`.

    Exactly one of ``trans`` / ``dcplx_trans`` must be set.
    """

    @property
    def trans(self) -> kdb.Trans | None: ...
    @property
    def dcplx_trans(self) -> kdb.DCplxTrans | None: ...
    @property
    def cross_section(self) -> _CrossSectionLike: ...
    @property
    def port_type(self) -> str: ...
    @property
    def kcl(self) -> _KCLLike: ...


def _get_trans(port: PortLike) -> kdb.Trans:
    from klayout import db as kdb

    if port.trans is not None:
        return port.trans
    assert port.dcplx_trans is not None, "port has neither trans nor dcplx_trans"
    return kdb.ICplxTrans(trans=port.dcplx_trans, dbu=port.kcl.dbu).s_trans()


def _get_dcplx_trans(port: PortLike) -> kdb.DCplxTrans:
    from klayout import db as kdb

    if port.dcplx_trans is not None:
        return port.dcplx_trans
    assert port.trans is not None, "port has neither trans nor dcplx_trans"
    return kdb.DCplxTrans(port.trans.to_dtype(port.kcl.dbu))


def check_connection(
    p1: PortLike,
    p2: PortLike,
    *,
    tolerance: float = 0.1,
    angle_tolerance: float = 0.01,
    snapped: bool = False,
) -> int:
    """Compare two ports, returning a :class:`PortCheck` bitmask.

    Integer transforms are used when both ports expose ``trans`` (or when
    ``snapped=True``); otherwise the complex transforms are used with the
    supplied tolerances. ``cross_section`` implies ``layer`` and ``width``.
    """
    tol_um = p1.kcl.dbu * tolerance
    check = 0
    if snapped or (p1.trans is not None and p2.trans is not None):
        t1 = _get_trans(p1)
        t2 = _get_trans(p2)
        if t1.disp == t2.disp:
            check += PortCheck.position
        orientation = (t1.angle - t2.angle) % 4
        if orientation == 2:
            check += PortCheck.opposite
        elif orientation == 0:
            check += PortCheck.same
    else:
        dt1 = _get_dcplx_trans(p1)
        dt2 = _get_dcplx_trans(p2)
        if (dt1.disp - dt2.disp).length() < tol_um:
            check += PortCheck.position
        angle_diff = (dt1.angle - dt2.angle) % 360
        if abs(angle_diff - 180) < angle_tolerance:
            check += PortCheck.opposite
        elif abs(angle_diff) < angle_tolerance:
            check += PortCheck.same
    if p1.cross_section == p2.cross_section:
        check += PortCheck.cross_section
        check += PortCheck.layer
        check += PortCheck.width
    else:
        if p1.cross_section.main_layer.is_equivalent(p2.cross_section.main_layer):
            check += PortCheck.layer
        if p1.cross_section.width == p2.cross_section.width:
            check += PortCheck.width
    if p1.port_type == p2.port_type:
        check += PortCheck.port_type
    return check
