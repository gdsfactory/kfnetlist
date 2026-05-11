"""Smoke tests for :mod:`kfnetlist.port_check`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from kfnetlist import PortCheck, check_connection

if TYPE_CHECKING:
    from klayout import db as kdb
else:
    kdb = pytest.importorskip("klayout.db")


@dataclass
class _KCL:
    dbu: float = 0.001


@dataclass
class _XS:
    main_layer: kdb.LayerInfo
    width: int


@dataclass
class _Port:
    trans: kdb.Trans | None
    dcplx_trans: kdb.DCplxTrans | None
    cross_section: _XS
    port_type: str
    kcl: _KCL


def _xs(layer: int = 1, datatype: int = 0, width: int = 500) -> _XS:
    return _XS(main_layer=kdb.LayerInfo(layer, datatype), width=width)


def _trans_port(
    *,
    x: int = 0,
    y: int = 0,
    angle: int = 0,
    mirror: bool = False,
    xs: _XS | None = None,
    port_type: str = "optical",
) -> _Port:
    return _Port(
        trans=kdb.Trans(angle, mirror, x, y),
        dcplx_trans=None,
        cross_section=xs or _xs(),
        port_type=port_type,
        kcl=_KCL(),
    )


def _dcplx_port(
    *,
    x: float = 0.0,
    y: float = 0.0,
    angle: float = 0.0,
    mirror: bool = False,
    xs: _XS | None = None,
    port_type: str = "optical",
) -> _Port:
    return _Port(
        trans=None,
        dcplx_trans=kdb.DCplxTrans(1.0, angle, mirror, x, y),
        cross_section=xs or _xs(),
        port_type=port_type,
        kcl=_KCL(),
    )


def test_opposite_ports_same_position_match_all_opposite() -> None:
    xs = _xs()
    a = _trans_port(x=0, y=0, angle=0, xs=xs)
    b = _trans_port(x=0, y=0, angle=2, xs=xs)  # 180° rotated
    bits = check_connection(a, b)
    assert bits & PortCheck.position
    assert bits & PortCheck.opposite
    assert not (bits & PortCheck.same)
    assert bits & PortCheck.layer
    assert bits & PortCheck.width
    assert bits & PortCheck.cross_section
    assert bits & PortCheck.port_type


def test_aligned_same_direction_sets_same_not_opposite() -> None:
    xs = _xs()
    a = _trans_port(angle=0, xs=xs)
    b = _trans_port(angle=0, xs=xs)
    bits = check_connection(a, b)
    assert bits & PortCheck.same
    assert not (bits & PortCheck.opposite)


def test_different_position_no_position_bit() -> None:
    a = _trans_port(x=0, y=0, angle=0)
    b = _trans_port(x=1000, y=0, angle=2)
    bits = check_connection(a, b)
    assert not (bits & PortCheck.position)
    assert bits & PortCheck.opposite


def test_width_mismatch_clears_width_keeps_layer() -> None:
    xs1 = _xs(width=500)
    xs2 = _xs(width=600)
    a = _trans_port(xs=xs1)
    b = _trans_port(xs=xs2, angle=2)
    bits = check_connection(a, b)
    assert bits & PortCheck.layer
    assert not (bits & PortCheck.width)
    assert not (bits & PortCheck.cross_section)


def test_layer_mismatch_clears_layer() -> None:
    a = _trans_port(xs=_xs(layer=1))
    b = _trans_port(xs=_xs(layer=2), angle=2)
    bits = check_connection(a, b)
    assert not (bits & PortCheck.layer)


def test_port_type_mismatch() -> None:
    a = _trans_port(port_type="optical")
    b = _trans_port(port_type="electrical", angle=2)
    bits = check_connection(a, b)
    assert not (bits & PortCheck.port_type)


def test_equal_cross_section_implies_layer_and_width() -> None:
    xs = _xs()
    a = _trans_port(xs=xs)
    b = _trans_port(xs=xs, angle=2)
    bits = check_connection(a, b)
    assert bits & PortCheck.cross_section
    assert bits & PortCheck.layer
    assert bits & PortCheck.width


def test_dcplx_path_position_within_tolerance() -> None:
    xs = _xs()
    a = _dcplx_port(x=0.0, y=0.0, angle=0.0, xs=xs)
    b = _dcplx_port(x=0.0, y=0.0, angle=180.0, xs=xs)
    bits = check_connection(a, b)
    assert bits & PortCheck.position
    assert bits & PortCheck.opposite


def test_dcplx_path_position_outside_tolerance() -> None:
    xs = _xs()
    # tol_um = dbu * tolerance = 0.001 * 0.1 = 1e-4 um; 0.5 um is well outside
    a = _dcplx_port(x=0.0, y=0.0, angle=0.0, xs=xs)
    b = _dcplx_port(x=0.5, y=0.0, angle=180.0, xs=xs)
    bits = check_connection(a, b)
    assert not (bits & PortCheck.position)


def test_mixed_trans_falls_back_to_dcplx() -> None:
    xs = _xs()
    a = _trans_port(x=0, y=0, angle=0, xs=xs)
    b = _dcplx_port(x=0.0, y=0.0, angle=180.0, xs=xs)
    bits = check_connection(a, b)
    assert bits & PortCheck.position
    assert bits & PortCheck.opposite


def test_snapped_forces_integer_path_even_with_dcplx() -> None:
    xs = _xs()
    a = _dcplx_port(x=0.0, y=0.0, angle=0.0, xs=xs)
    b = _dcplx_port(x=0.0, y=0.0, angle=180.0, xs=xs)
    bits = check_connection(a, b, snapped=True)
    assert bits & PortCheck.position
    assert bits & PortCheck.opposite


def test_portcheck_aliases() -> None:
    assert PortCheck.all_opposite == (
        PortCheck.opposite | PortCheck.width | PortCheck.port_type | PortCheck.layer
    )
    assert PortCheck.all_overlap == (
        PortCheck.width | PortCheck.port_type | PortCheck.layer
    )
