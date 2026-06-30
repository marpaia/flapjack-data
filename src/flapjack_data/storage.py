"""Storage protocol.

A backend persists the domain model and answers measurement queries. The protocol is
deliberately small so backends can range from an in-memory dict to a TimescaleDB-backed
implementation or a remote Flapjack API. `add` assigns an id and returns the stored entity;
`query_measurements` is the one read path that spans the relational graph.
"""

from __future__ import annotations

from typing import Iterator, Protocol, TypeVar, runtime_checkable

from flapjack_data.characterization.types import (
    AggregateValue,
    MeasurementFrameRow,
    Selection,
)
from flapjack_data.model import Characterization, CharacterizationDatum, Measurement

T = TypeVar("T")


@runtime_checkable
class Storage(Protocol):
    def add(self, entity: T) -> T:
        """Persist a new entity, assigning its id, and return it."""
        ...

    def get(self, entity_type: type[T], entity_id: int) -> T | None:
        """Fetch an entity by type and id, or None if absent."""
        ...

    def list_all(self, entity_type: type[T]) -> list[T]:
        """List all entities of a type."""
        ...

    def query_measurements(
        self,
        *,
        study_id: int | None = None,
        assay_id: int | None = None,
        sample_id: int | None = None,
        signal_id: int | None = None,
    ) -> list[Measurement]:
        """Return measurements filtered by any combination of the relational keys."""
        ...


@runtime_checkable
class CharacterizationStorage(Storage, Protocol):
    """A :class:`Storage` that also feeds and persists characterization.

    Split out from the minimal :class:`Storage` so a backend can opt in. The analysis engine
    reads through :meth:`measurement_frame` (and :meth:`aggregate_measurements` for the metrics
    that reduce to a SQL aggregate), and persists results through :meth:`save_characterization`.
    """

    def measurement_frame(self, selection: Selection) -> Iterator[MeasurementFrameRow]:
        """Stream the flattened measurement frame for ``selection``.

        Yields one row per measurement, denormalized with sample/assay/study context and the
        sample's per-chemical concentrations. Streamed (not materialized) so the measurement
        table, the large one, never has to be loaded whole.
        """
        ...

    def aggregate_measurements(self, *, func: str, selection: Selection) -> list[AggregateValue]:
        """Aggregate raw measurement values per (sample, signal) using ``func`` (``"mean"``/``"max"``).

        The scaling path for Mean/Max Expression: pushed down to the database as ``GROUP BY``
        rather than streaming every measurement into the engine.
        """
        ...

    def save_characterization(
        self, characterization: Characterization, data: list[CharacterizationDatum]
    ) -> Characterization:
        """Persist a run and its result rows, stamping ids; return the stored run."""
        ...

    def get_characterization(self, characterization_id: int) -> Characterization | None:
        """Fetch a characterization run by id, or None if absent."""
        ...

    def query_characterizations(
        self, *, analysis_type: str | None = None, params_hash: str | None = None
    ) -> list[Characterization]:
        """List characterization runs, optionally filtered by analysis type and/or params hash."""
        ...

    def get_characterization_data(self, characterization_id: int) -> list[CharacterizationDatum]:
        """Fetch all result rows of a characterization run."""
        ...
