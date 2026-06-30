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
