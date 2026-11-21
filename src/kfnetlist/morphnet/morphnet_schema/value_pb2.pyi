from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SIPrefix(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SI_PREFIX_UNSPECIFIED: _ClassVar[SIPrefix]
    SI_PREFIX_QUECTO: _ClassVar[SIPrefix]
    SI_PREFIX_RONTO: _ClassVar[SIPrefix]
    SI_PREFIX_YOCTO: _ClassVar[SIPrefix]
    SI_PREFIX_ZEPTO: _ClassVar[SIPrefix]
    SI_PREFIX_ATTO: _ClassVar[SIPrefix]
    SI_PREFIX_FEMTO: _ClassVar[SIPrefix]
    SI_PREFIX_PICO: _ClassVar[SIPrefix]
    SI_PREFIX_NANO: _ClassVar[SIPrefix]
    SI_PREFIX_MICRO: _ClassVar[SIPrefix]
    SI_PREFIX_MILLI: _ClassVar[SIPrefix]
    SI_PREFIX_CENTI: _ClassVar[SIPrefix]
    SI_PREFIX_DECI: _ClassVar[SIPrefix]
    SI_PREFIX_DECA: _ClassVar[SIPrefix]
    SI_PREFIX_HECTO: _ClassVar[SIPrefix]
    SI_PREFIX_KILO: _ClassVar[SIPrefix]
    SI_PREFIX_MEGA: _ClassVar[SIPrefix]
    SI_PREFIX_GIGA: _ClassVar[SIPrefix]
    SI_PREFIX_TERA: _ClassVar[SIPrefix]
    SI_PREFIX_PETA: _ClassVar[SIPrefix]
    SI_PREFIX_EXA: _ClassVar[SIPrefix]
    SI_PREFIX_ZETTA: _ClassVar[SIPrefix]
    SI_PREFIX_YOTTA: _ClassVar[SIPrefix]
    SI_PREFIX_RONNA: _ClassVar[SIPrefix]
    SI_PREFIX_QUETTA: _ClassVar[SIPrefix]

class Operator(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OPERATOR_UNSPECIFIED: _ClassVar[Operator]
    OPERATOR_ADD: _ClassVar[Operator]
    OPERATOR_SUB: _ClassVar[Operator]
    OPERATOR_MUL: _ClassVar[Operator]
    OPERATOR_DIV: _ClassVar[Operator]
    OPERATOR_POW: _ClassVar[Operator]
    OPERATOR_MOD: _ClassVar[Operator]
    OPERATOR_NEG: _ClassVar[Operator]
    OPERATOR_NOT: _ClassVar[Operator]
    OPERATOR_EQ: _ClassVar[Operator]
    OPERATOR_NE: _ClassVar[Operator]
    OPERATOR_LT: _ClassVar[Operator]
    OPERATOR_LE: _ClassVar[Operator]
    OPERATOR_GT: _ClassVar[Operator]
    OPERATOR_GE: _ClassVar[Operator]
    OPERATOR_AND: _ClassVar[Operator]
    OPERATOR_OR: _ClassVar[Operator]
SI_PREFIX_UNSPECIFIED: SIPrefix
SI_PREFIX_QUECTO: SIPrefix
SI_PREFIX_RONTO: SIPrefix
SI_PREFIX_YOCTO: SIPrefix
SI_PREFIX_ZEPTO: SIPrefix
SI_PREFIX_ATTO: SIPrefix
SI_PREFIX_FEMTO: SIPrefix
SI_PREFIX_PICO: SIPrefix
SI_PREFIX_NANO: SIPrefix
SI_PREFIX_MICRO: SIPrefix
SI_PREFIX_MILLI: SIPrefix
SI_PREFIX_CENTI: SIPrefix
SI_PREFIX_DECI: SIPrefix
SI_PREFIX_DECA: SIPrefix
SI_PREFIX_HECTO: SIPrefix
SI_PREFIX_KILO: SIPrefix
SI_PREFIX_MEGA: SIPrefix
SI_PREFIX_GIGA: SIPrefix
SI_PREFIX_TERA: SIPrefix
SI_PREFIX_PETA: SIPrefix
SI_PREFIX_EXA: SIPrefix
SI_PREFIX_ZETTA: SIPrefix
SI_PREFIX_YOTTA: SIPrefix
SI_PREFIX_RONNA: SIPrefix
SI_PREFIX_QUETTA: SIPrefix
OPERATOR_UNSPECIFIED: Operator
OPERATOR_ADD: Operator
OPERATOR_SUB: Operator
OPERATOR_MUL: Operator
OPERATOR_DIV: Operator
OPERATOR_POW: Operator
OPERATOR_MOD: Operator
OPERATOR_NEG: Operator
OPERATOR_NOT: Operator
OPERATOR_EQ: Operator
OPERATOR_NE: Operator
OPERATOR_LT: Operator
OPERATOR_LE: Operator
OPERATOR_GT: Operator
OPERATOR_GE: Operator
OPERATOR_AND: Operator
OPERATOR_OR: Operator

class PrefixedValue(_message.Message):
    __slots__ = ("double_value", "prefix")
    DOUBLE_VALUE_FIELD_NUMBER: _ClassVar[int]
    PREFIX_FIELD_NUMBER: _ClassVar[int]
    double_value: float
    prefix: SIPrefix
    def __init__(self, double_value: _Optional[float] = ..., prefix: _Optional[_Union[SIPrefix, str]] = ...) -> None: ...

class UnaryOp(_message.Message):
    __slots__ = ("op", "operand")
    OP_FIELD_NUMBER: _ClassVar[int]
    OPERAND_FIELD_NUMBER: _ClassVar[int]
    op: Operator
    operand: Expression
    def __init__(self, op: _Optional[_Union[Operator, str]] = ..., operand: _Optional[_Union[Expression, _Mapping]] = ...) -> None: ...

class BinaryOp(_message.Message):
    __slots__ = ("op", "lhs", "rhs")
    OP_FIELD_NUMBER: _ClassVar[int]
    LHS_FIELD_NUMBER: _ClassVar[int]
    RHS_FIELD_NUMBER: _ClassVar[int]
    op: Operator
    lhs: Expression
    rhs: Expression
    def __init__(self, op: _Optional[_Union[Operator, str]] = ..., lhs: _Optional[_Union[Expression, _Mapping]] = ..., rhs: _Optional[_Union[Expression, _Mapping]] = ...) -> None: ...

class Call(_message.Message):
    __slots__ = ("name", "args")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    name: str
    args: _containers.RepeatedCompositeFieldContainer[Expression]
    def __init__(self, name: _Optional[str] = ..., args: _Optional[_Iterable[_Union[Expression, _Mapping]]] = ...) -> None: ...

class Ternary(_message.Message):
    __slots__ = ("cond", "then", "otherwise")
    COND_FIELD_NUMBER: _ClassVar[int]
    THEN_FIELD_NUMBER: _ClassVar[int]
    OTHERWISE_FIELD_NUMBER: _ClassVar[int]
    cond: Expression
    then: Expression
    otherwise: Expression
    def __init__(self, cond: _Optional[_Union[Expression, _Mapping]] = ..., then: _Optional[_Union[Expression, _Mapping]] = ..., otherwise: _Optional[_Union[Expression, _Mapping]] = ...) -> None: ...

class Expression(_message.Message):
    __slots__ = ("literal", "reference", "unary", "binary", "call", "ternary", "raw")
    LITERAL_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_FIELD_NUMBER: _ClassVar[int]
    UNARY_FIELD_NUMBER: _ClassVar[int]
    BINARY_FIELD_NUMBER: _ClassVar[int]
    CALL_FIELD_NUMBER: _ClassVar[int]
    TERNARY_FIELD_NUMBER: _ClassVar[int]
    RAW_FIELD_NUMBER: _ClassVar[int]
    literal: PrefixedValue
    reference: str
    unary: UnaryOp
    binary: BinaryOp
    call: Call
    ternary: Ternary
    raw: str
    def __init__(self, literal: _Optional[_Union[PrefixedValue, _Mapping]] = ..., reference: _Optional[str] = ..., unary: _Optional[_Union[UnaryOp, _Mapping]] = ..., binary: _Optional[_Union[BinaryOp, _Mapping]] = ..., call: _Optional[_Union[Call, _Mapping]] = ..., ternary: _Optional[_Union[Ternary, _Mapping]] = ..., raw: _Optional[str] = ...) -> None: ...

class ParameterValue(_message.Message):
    __slots__ = ("prefixed_value", "model_ref", "expression")
    PREFIXED_VALUE_FIELD_NUMBER: _ClassVar[int]
    MODEL_REF_FIELD_NUMBER: _ClassVar[int]
    EXPRESSION_FIELD_NUMBER: _ClassVar[int]
    prefixed_value: PrefixedValue
    model_ref: ModelReference
    expression: Expression
    def __init__(self, prefixed_value: _Optional[_Union[PrefixedValue, _Mapping]] = ..., model_ref: _Optional[_Union[ModelReference, _Mapping]] = ..., expression: _Optional[_Union[Expression, _Mapping]] = ...) -> None: ...

class ModelReference(_message.Message):
    __slots__ = ("model_interface_name", "arguments")
    class ArgumentsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: ParameterValue
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[ParameterValue, _Mapping]] = ...) -> None: ...
    MODEL_INTERFACE_NAME_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_FIELD_NUMBER: _ClassVar[int]
    model_interface_name: str
    arguments: _containers.MessageMap[str, ParameterValue]
    def __init__(self, model_interface_name: _Optional[str] = ..., arguments: _Optional[_Mapping[str, ParameterValue]] = ...) -> None: ...
