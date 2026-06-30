"""Flapjack-compatible measurement domain model.

These are storage-agnostic dataclasses mirroring the Flapjack data model
(study → assay → sample → measurement, with the surrounding registry entities).
Relationships are expressed by id so any storage backend can persist them. Ids are
assigned by the storage layer when an entity is added.

Every entity carries an optional ``owner``: an opaque key (username, user id, organization
id, ...) for multi-tenant deployments. Single-tenant users leave it ``None``; a storage
backend can scope reads and writes to one owner.
"""

from dataclasses import dataclass, field


@dataclass
class Study:
    name: str
    description: str = ""
    public: bool = False
    owner: str | None = None
    id: int | None = None


@dataclass
class Assay:
    study_id: int
    name: str
    machine: str = ""
    description: str = ""
    temperature: float = 0.0
    owner: str | None = None
    id: int | None = None


@dataclass
class Media:
    name: str
    description: str = ""
    owner: str | None = None
    id: int | None = None


@dataclass
class Strain:
    name: str
    description: str = ""
    owner: str | None = None
    id: int | None = None


@dataclass
class Chemical:
    name: str
    description: str = ""
    pubchemid: int | None = None
    owner: str | None = None
    id: int | None = None


@dataclass
class Supplement:
    name: str
    chemical_id: int
    concentration: float
    owner: str | None = None
    id: int | None = None


@dataclass
class Dna:
    name: str
    owner: str | None = None
    id: int | None = None


@dataclass
class Vector:
    name: str
    dna_ids: list[int] = field(default_factory=list)
    owner: str | None = None
    id: int | None = None


@dataclass
class Signal:
    name: str
    description: str = ""
    color: str = ""
    #: Optional role hint: ``"fluorescence"``, ``"biomass"``, ``"od"``, ``"other"`` (or ``None``).
    #: A default that analyses fall back to; the biomass/reference role can still be chosen
    #: per request via :class:`~flapjack_data.characterization.AnalysisSpec`.
    kind: str | None = None
    owner: str | None = None
    id: int | None = None


@dataclass
class Sample:
    assay_id: int
    row: int
    col: int
    media_id: int | None = None
    strain_id: int | None = None
    vector_id: int | None = None
    supplement_ids: list[int] = field(default_factory=list)
    owner: str | None = None
    id: int | None = None


@dataclass
class Measurement:
    sample_id: int
    signal_id: int
    value: float
    time: float
    owner: str | None = None
    id: int | None = None


@dataclass
class Characterization:
    """A persisted characterization run: an analysis applied to a selection of measurements.

    Flapjack itself recomputes every metric on the fly and stores nothing; here a run and its
    results are first-class so a backend can cache and re-serve them. ``spec`` is the serialized
    :class:`~flapjack_data.characterization.AnalysisSpec` and ``params_hash`` is its stable hash,
    used to look up a previously computed run instead of recomputing it.
    """

    analysis_type: str
    spec: dict[str, object] = field(default_factory=dict)
    params_hash: str = ""
    name: str = ""
    owner: str | None = None
    id: int | None = None


@dataclass
class CharacterizationDatum:
    """One result row of a :class:`Characterization`.

    Holds both shapes the analyses produce: time-series rows carry ``time`` (one row per
    timepoint); aggregate rows leave ``time`` ``None`` (one row per sample/signal). ``metric``
    names the produced quantity (e.g. ``"Rate"``, ``"Velocity"``, ``"Expression"``, ``"Alpha"``,
    ``"Rho"``). ``concentration``/``concentration2`` carry the dose-response axes for
    induction/heatmap results.
    """

    characterization_id: int
    sample_id: int
    signal_id: int
    metric: str
    value: float
    time: float | None = None
    concentration: float | None = None
    concentration2: float | None = None
    owner: str | None = None
    id: int | None = None


#: Every entity type the model defines, for generic storage handling.
ENTITY_TYPES = (
    Study,
    Assay,
    Media,
    Strain,
    Chemical,
    Supplement,
    Dna,
    Vector,
    Signal,
    Sample,
    Measurement,
    Characterization,
    CharacterizationDatum,
)
