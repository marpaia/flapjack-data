"""Flapjack-compatible measurement domain model.

These are storage-agnostic dataclasses mirroring the Flapjack data model
(study → assay → sample → measurement, with the surrounding registry entities).
Relationships are expressed by id so any storage backend can persist them. Ids are
assigned by the storage layer when an entity is added.
"""

from dataclasses import dataclass, field


@dataclass
class Study:
    name: str
    description: str = ""
    public: bool = False
    id: int | None = None


@dataclass
class Assay:
    study_id: int
    name: str
    machine: str = ""
    description: str = ""
    temperature: float = 0.0
    id: int | None = None


@dataclass
class Media:
    name: str
    description: str = ""
    id: int | None = None


@dataclass
class Strain:
    name: str
    description: str = ""
    id: int | None = None


@dataclass
class Chemical:
    name: str
    description: str = ""
    pubchemid: int | None = None
    id: int | None = None


@dataclass
class Supplement:
    name: str
    chemical_id: int
    concentration: float
    id: int | None = None


@dataclass
class Dna:
    name: str
    id: int | None = None


@dataclass
class Vector:
    name: str
    dna_ids: list[int] = field(default_factory=list)
    id: int | None = None


@dataclass
class Signal:
    name: str
    description: str = ""
    color: str = ""
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
    id: int | None = None


@dataclass
class Measurement:
    sample_id: int
    signal_id: int
    value: float
    time: float
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
)
