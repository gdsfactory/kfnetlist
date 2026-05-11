"""Serialization helper for instance settings.

Lifted from ``kfactory.serialization.serialize_setting`` so the extractor
does not have to import kfactory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeGuard

if TYPE_CHECKING:
    pass


def _is_serializable_shape(value: Any) -> TypeGuard[Any]:
    from klayout import db as kdb, lay

    return isinstance(
        value,
        kdb.Box
        | kdb.DBox
        | kdb.Edge
        | kdb.DEdge
        | kdb.EdgePair
        | kdb.DEdgePair
        | kdb.EdgePairs
        | kdb.Edges
        | lay.LayerProperties
        | kdb.Matrix2d
        | kdb.Matrix3d
        | kdb.Path
        | kdb.DPath
        | kdb.Point
        | kdb.DPoint
        | kdb.Polygon
        | kdb.DPolygon
        | kdb.SimplePolygon
        | kdb.DSimplePolygon
        | kdb.Region
        | kdb.Text
        | kdb.DText
        | kdb.Texts
        | kdb.Trans
        | kdb.DTrans
        | kdb.CplxTrans
        | kdb.ICplxTrans
        | kdb.DCplxTrans
        | kdb.VCplxTrans
        | kdb.Vector
        | kdb.DVector
        | kdb.LayerInfo,
    )


def serialize_setting(setting: Any) -> Any:
    """Serialise a setting value to a JSON-friendly form.

    klayout shape types are encoded as ``"!#ClassName <str(value)>"``; dicts,
    lists, and tuples recurse. Other values pass through unchanged.
    """
    if setting is None:
        return None
    if isinstance(setting, dict):
        return {str(k): serialize_setting(v) for k, v in setting.items()}
    if isinstance(setting, list):
        return [serialize_setting(s) for s in setting]
    if isinstance(setting, tuple):
        return tuple(serialize_setting(s) for s in setting)
    if _is_serializable_shape(setting):
        return f"!#{setting.__class__.__name__} {setting!s}"
    return setting
