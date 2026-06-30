"""Characterization: the analysis contract and (optionally) the engine that computes it.

The contract types here are dependency-free. The numerical engine that turns an
:class:`AnalysisSpec` into results lives in :mod:`flapjack_data.characterization.engine` and
requires the ``[analysis]`` extra (numpy/scipy/pandas); import it explicitly::

    from flapjack_data.characterization.engine import run
"""

from flapjack_data.characterization.types import (
    AGGREGATE_TYPES,
    AggregateValue,
    AnalysisSpec,
    AnalysisType,
    CharacterizationResult,
    MeasurementFrameRow,
    Selection,
)

__all__ = [
    "AnalysisType",
    "AnalysisSpec",
    "Selection",
    "MeasurementFrameRow",
    "AggregateValue",
    "CharacterizationResult",
    "AGGREGATE_TYPES",
]
