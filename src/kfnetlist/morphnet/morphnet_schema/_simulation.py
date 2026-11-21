# ruff: noqa: RUF012
from __future__ import annotations

from enum import IntEnum
from operator import not_
from pathlib import Path
from typing import ClassVar

from pydantic import Field, field_serializer, field_validator, model_validator

from kfnetlist.morphnet.morphnet_schema import simulation_pb2 as pb
from kfnetlist.morphnet.morphnet_schema._base import ProtoModel
from kfnetlist.morphnet.morphnet_schema._value import ParameterValue

__all__ = [
    "Analysis",
    "AnalysisKind",
    "InitialCondition",
    "Measurement",
    "OutputRequest",
    "OutputRequestKind",
    "Simulation",
    "Stimulus",
    "Waveform",
    "WaveformKind",
]


# ======================================================================
# Enums
# ======================================================================


class AnalysisKind(IntEnum):
    UNSPECIFIED = 0
    OP = 1
    DC = 2
    AC = 3
    TRAN = 4
    NOISE = 5
    TF = 6
    SENS = 7
    PZ = 8
    DISTO = 9
    FOUR = 10
    FFT = 11


class OutputRequestKind(IntEnum):
    UNSPECIFIED = 0
    PRINT = 1
    PLOT = 2
    PROBE = 3
    SAVE = 4


class WaveformKind(IntEnum):
    UNSPECIFIED = 0
    PULSE = 1
    SIN = 2
    EXP = 3
    SFFM = 4
    PWL = 5


# ======================================================================
# Simulation models
# ======================================================================


class Analysis(ProtoModel):
    _proto_type: ClassVar[type] = pb.Analysis

    kind: AnalysisKind = AnalysisKind.UNSPECIFIED
    name: str = ""
    arguments: list[str] = []
    options: dict[str, str] = {}


class OutputRequest(ProtoModel):
    _proto_type: ClassVar[type] = pb.OutputRequest

    kind: OutputRequestKind = OutputRequestKind.UNSPECIFIED
    analysis_type: str = ""
    variables: list[str] = []


class Measurement(ProtoModel):
    _proto_type: ClassVar[type] = pb.Measurement

    name: str = ""
    analysis_type: str = ""
    body: str = ""


class InitialCondition(ProtoModel):
    _proto_type: ClassVar[type] = pb.InitialCondition

    conditions: dict[str, str] = {}


class Waveform(ProtoModel):
    """A transient source shape; ``args`` use SPICE semantics with Spectre names."""

    _proto_type: ClassVar[type] = pb.Waveform

    kind: WaveformKind = WaveformKind.UNSPECIFIED
    args: dict[str, ParameterValue] = {}
    points: list[ParameterValue] = []  # PWL: t0 v0 t1 v1 ...
    file: Path | None = None  # PWL from a file; stored POSIX (see netlist.paths)

    @field_validator("file", mode="after")
    @classmethod
    def _file(cls, value: Path | None) -> Path | None:
        from kfnetlist.morphnet.netlist.paths import resolve_file  # (import cycle)

        if value is None or value == Path():  # proto's unset string is ""
            return None
        return resolve_file(value)

    @field_serializer("file")
    def _posix(self, value: Path | None) -> str | None:
        from kfnetlist.morphnet.netlist.paths import posix_file  # (import cycle)

        return None if value is None else posix_file(value)

    @model_validator(mode="after")
    def _points_or_file(self) -> Waveform:
        if self.points and self.file is not None:
            raise ValueError("a PWL waveform has points or a file, not both")
        if self.file is not None and self.kind != WaveformKind.PWL:
            raise ValueError(f"a file belongs to a PWL waveform, not {self.kind.name}")
        return self


class Stimulus(ProtoModel):
    """What drives one V/I source, named ``"<circuit>/<instance>"``."""

    _proto_type: ClassVar[type] = pb.Stimulus

    name: str = ""
    dc: ParameterValue | None = None
    ac_magnitude: ParameterValue | None = None
    ac_phase: ParameterValue | None = None
    waveform: Waveform | None = None


class Simulation(ProtoModel):
    _proto_type: ClassVar[type] = pb.Simulation

    analyses: list[Analysis] = []
    output_requests: list[OutputRequest] = []
    measurements: list[Measurement] = []
    initial_conditions: InitialCondition | None = None
    node_sets: InitialCondition | None = None
    temperatures: list[float] = []
    stimuli: list[Stimulus] = Field(default=[], exclude_if=not_)  # as Rust skips it
    options: dict[str, str] = {}
