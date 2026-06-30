"""Storage protocol.

A backend persists the domain model and answers measurement queries. The protocol is
deliberately small so backends can range from an in-memory dict to a TimescaleDB-backed
implementation or a remote Flapjack API. `add` assigns an id and returns the stored entity;
`query_measurements` is the one read path that spans the relational graph.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from flapjack_data.model import Measurement

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
