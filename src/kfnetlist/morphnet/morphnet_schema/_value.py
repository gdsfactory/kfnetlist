# ruff: noqa: RUF012
"""Value types shared by circuits and simulations (``value.proto``)."""

from __future__ import annotations

from enum import IntEnum
from typing import ClassVar

from pydantic import model_validator

from kfnetlist.morphnet.morphnet_schema import value_pb2 as pb
from kfnetlist.morphnet.morphnet_schema._base import ProtoModel

__all__ = [
    "BinaryOp",
    "Call",
    "Expression",
    "ModelReference",
    "Operator",
    "ParameterValue",
    "PrefixedValue",
    "SIPrefix",
    "Ternary",
    "UnaryOp",
]


class SIPrefix(IntEnum):
    UNSPECIFIED = 0
    QUECTO = 1
    RONTO = 2
    YOCTO = 3
    ZEPTO = 4
    ATTO = 5
    FEMTO = 6
    PICO = 7
    NANO = 8
    MICRO = 9
    MILLI = 10
    CENTI = 11
    DECI = 12
    DECA = 13
    HECTO = 14
    KILO = 15
    MEGA = 16
    GIGA = 17
    TERA = 18
    PETA = 19
    EXA = 20
    ZETTA = 21
    YOTTA = 22
    RONNA = 23
    QUETTA = 24


class Operator(IntEnum):
    UNSPECIFIED = 0
    ADD = 1
    SUB = 2
    MUL = 3
    DIV = 4
    POW = 5
    MOD = 6
    NEG = 7
    NOT = 8
    EQ = 9
    NE = 10
    LT = 11
    LE = 12
    GT = 13
    GE = 14
    AND = 15
    OR = 16


class PrefixedValue(ProtoModel):
    _proto_type: ClassVar[type] = pb.PrefixedValue

    double_value: float = 0.0
    prefix: SIPrefix = SIPrefix.UNSPECIFIED


class ModelReference(ProtoModel):
    _proto_type: ClassVar[type] = pb.ModelReference

    model_interface_name: str = ""
    arguments: dict[str, ParameterValue] = {}


def _one_of(model: ProtoModel, fields: tuple[str, ...]) -> None:
    if sum(getattr(model, f) is not None for f in fields) > 1:
        names = ", ".join(repr(f) for f in fields)
        raise ValueError(
            f"{type(model).__name__} is a oneof: set exactly one of {names}"
        )


class UnaryOp(ProtoModel):
    _proto_type: ClassVar[type] = pb.UnaryOp

    op: Operator = Operator.UNSPECIFIED
    operand: Expression | None = None


class BinaryOp(ProtoModel):
    _proto_type: ClassVar[type] = pb.BinaryOp

    op: Operator = Operator.UNSPECIFIED
    lhs: Expression | None = None
    rhs: Expression | None = None


class Call(ProtoModel):
    _proto_type: ClassVar[type] = pb.Call

    name: str = ""
    args: list[Expression] = []


class Ternary(ProtoModel):
    _proto_type: ClassVar[type] = pb.Ternary

    cond: Expression | None = None
    then: Expression | None = None
    otherwise: Expression | None = None


class Expression(ProtoModel):
    """A parameter expression tree; ``raw`` is dialect text no grammar parsed."""

    _proto_type: ClassVar[type] = pb.Expression

    literal: PrefixedValue | None = None
    reference: str | None = None
    unary: UnaryOp | None = None
    binary: BinaryOp | None = None
    call: Call | None = None
    ternary: Ternary | None = None
    raw: str | None = None

    @model_validator(mode="after")
    def _check_oneof(self) -> Expression:
        _one_of(self, tuple(type(self).model_fields))
        return self


class ParameterValue(ProtoModel):
    _proto_type: ClassVar[type] = pb.ParameterValue

    prefixed_value: PrefixedValue | None = None
    model_ref: ModelReference | None = None
    expression: Expression | None = None

    @model_validator(mode="after")
    def _check_oneof(self) -> ParameterValue:
        _one_of(self, ("prefixed_value", "model_ref", "expression"))
        return self


# Resolve forward references (ParameterValue <-> ModelReference, Expression trees)
for _model in (UnaryOp, BinaryOp, Call, Ternary, Expression, ModelReference):
    _model.model_rebuild()
ParameterValue.model_rebuild()
