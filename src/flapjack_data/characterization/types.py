"""Characterization contract: the analysis catalog, request spec, and value shapes.

These types are dependency-free — they describe *what* characterization to compute and the
shape of the results, not *how*. The numerical engine that consumes them lives in
:mod:`flapjack_data.characterization.engine` behind the optional ``[analysis]`` extra, so the
contract is importable without numpy/scipy/pandas.

The design mirrors how Flapjack articulates characterization: a measurement selection plus an
analysis ``type`` and its parameters (biomass/reference signal, dose-response analyte, an inner
``function`` for induction/heatmap, smoothing, etc.). Flapjack carries these as a loose dict and
recomputes on every request; here they are typed and the result is addressable by a stable hash
so a backend can cache it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum

from flapjack_data.model import Characterization, CharacterizationDatum


class AnalysisType(str, Enum):
    """The catalog of characterization analyses, with Flapjack's canonical labels as values."""

    VELOCITY = "Velocity"
    MEAN_VELOCITY = "Mean Velocity"
    MAX_VELOCITY = "Max Velocity"
    EXPRESSION_RATE_INDIRECT = "Expression Rate (indirect)"
    EXPRESSION_RATE_DIRECT = "Expression Rate (direct)"
    EXPRESSION_RATE_INVERSE = "Expression Rate (inverse)"
    MEAN_EXPRESSION = "Mean Expression"
    MAX_EXPRESSION = "Max Expression"
    INDUCTION_CURVE = "Induction Curve"
    KYMOGRAPH = "Kymograph"
    HEATMAP = "Heatmap"
    ALPHA = "Alpha"
    RHO = "Rho"
    BACKGROUND_CORRECT = "Background Correct"


#: Analyses that collapse a time series to one value per sample/signal (``time`` is ``None`` in
#: their results). Everything else keeps the time axis.
AGGREGATE_TYPES = frozenset(
    {
        AnalysisType.MEAN_VELOCITY,
        AnalysisType.MAX_VELOCITY,
        AnalysisType.MEAN_EXPRESSION,
        AnalysisType.MAX_EXPRESSION,
        AnalysisType.ALPHA,
        AnalysisType.RHO,
    }
)


@dataclass
class Selection:
    """A set of measurements to characterize, by any combination of relational keys.

    Empty selects nothing (matching Flapjack, where an unfiltered request returns no samples).
    """

    study_ids: list[int] = field(default_factory=list)
    assay_ids: list[int] = field(default_factory=list)
    sample_ids: list[int] = field(default_factory=list)
    vector_ids: list[int] = field(default_factory=list)
    media_ids: list[int] = field(default_factory=list)
    strain_ids: list[int] = field(default_factory=list)
    signal_ids: list[int] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (
                self.study_ids,
                self.assay_ids,
                self.sample_ids,
                self.vector_ids,
                self.media_ids,
                self.strain_ids,
                self.signal_ids,
            )
        )


@dataclass
class AnalysisSpec:
    """A characterization request: which measurements, which analysis, and its parameters.

    Parameter defaults match Flapjack's ``Analysis.set_params``. ``biomass_signal_id`` and
    ``ref_signal_id`` are the per-request signal roles (no signal is intrinsically biomass or
    reference). ``analyte_id`` (or ``analyte1_id``/``analyte2_id``) names the chemical whose
    concentration is the dose-response axis, and ``function`` is the inner aggregate applied per
    concentration for induction/kymograph/heatmap.
    """

    type: AnalysisType
    selection: Selection = field(default_factory=Selection)

    # Signal roles, assigned per request rather than stored on the Signal.
    biomass_signal_id: int | None = None
    ref_signal_id: int | None = None

    # Dose-response analytes (chemical ids) and the inner aggregate for induction/heatmap.
    analyte_id: int | None = None
    analyte1_id: int | None = None
    analyte2_id: int | None = None
    function: AnalysisType | None = None

    # Background correction.
    bg_correction: float = 0.0
    min_biomass: float = 0.0
    remove_data: bool = False

    # Growth-phase window (Alpha/Rho).
    ndt: float = 2.0

    # Smoothing (velocity / indirect rate).
    smoothing_type: str = "savgol"
    pre_smoothing: int = 21
    post_smoothing: int = 21

    # Model-fit parameters (direct / inverse expression rate).
    degr: float = 0.0
    eps_L: float = 1e-7
    n_gaussians: int = 20
    eps: float = 0.01

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain JSON-able dict (enums rendered as their string values)."""

        def encode(value: object) -> object:
            if isinstance(value, AnalysisType):
                return value.value
            if isinstance(value, dict):
                return {k: encode(v) for k, v in value.items()}
            if isinstance(value, list):
                return [encode(v) for v in value]
            return value

        return {k: encode(v) for k, v in asdict(self).items()}

    def params_hash(self) -> str:
        """A stable hash of the full spec, for caching/looking up a computed run."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class MeasurementFrameRow:
    """One flattened measurement, the input row shape the engine assembles into a frame.

    This is Flapjack's canonical measurement frame, denormalized: each row is a single
    measurement with its sample/assay/study context and the sample's dose-response context.
    ``concentrations`` maps chemical id → concentration for the supplements on the sample, which
    is how induction/heatmap pick out the analyte's concentration axis.
    """

    sample_id: int
    signal_id: int
    signal: str
    color: str
    value: float
    time: float
    assay_id: int
    study_id: int
    media: str | None = None
    strain: str | None = None
    vector: str | None = None
    row: int = 0
    col: int = 0
    concentrations: dict[int, float] = field(default_factory=dict)


@dataclass
class AggregateValue:
    """One aggregate measurement value per (sample, signal), produced by SQL pushdown."""

    sample_id: int
    signal_id: int
    value: float


@dataclass
class CharacterizationResult:
    """An engine run: the :class:`~flapjack_data.model.Characterization` plus its result rows."""

    characterization: Characterization
    data: list[CharacterizationDatum]
