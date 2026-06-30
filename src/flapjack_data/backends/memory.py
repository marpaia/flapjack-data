"""In-memory storage backend.

The reference Storage implementation: keeps entities in per-type dictionaries with a simple
id counter. Useful for tests, notebooks, and small in-process pipelines, and a worked example
for implementing other backends.
"""

from __future__ import annotations

import dataclasses
from typing import Any, TypeVar, cast

from flapjack_data.model import Assay, Measurement, Sample
from flapjack_data.storage import Storage

T = TypeVar("T")


class InMemoryStorage(Storage):
    def __init__(self) -> None:
        self._data: dict[type, dict[int, Any]] = {}
        self._next_id: dict[type, int] = {}

    def add(self, entity: T) -> T:
        entity_type = type(entity)
        store = self._data.setdefault(entity_type, {})
        counter = self._next_id.get(entity_type, 0) + 1
        self._next_id[entity_type] = counter
        stored = dataclasses.replace(cast(Any, entity), id=counter)
        store[counter] = stored
        return cast(T, stored)

    def get(self, entity_type: type[T], entity_id: int) -> T | None:
        return cast("T | None", self._data.get(entity_type, {}).get(entity_id))

    def list_all(self, entity_type: type[T]) -> list[T]:
        return list(self._data.get(entity_type, {}).values())

    def query_measurements(
        self,
        *,
        study_id: int | None = None,
        assay_id: int | None = None,
        sample_id: int | None = None,
        signal_id: int | None = None,
    ) -> list[Measurement]:
        measurements: list[Measurement] = list(self._data.get(Measurement, {}).values())

        if signal_id is not None:
            measurements = [m for m in measurements if m.signal_id == signal_id]
        if sample_id is not None:
            measurements = [m for m in measurements if m.sample_id == sample_id]

        if assay_id is not None or study_id is not None:
            sample_ids = self._sample_ids_for(study_id=study_id, assay_id=assay_id)
            measurements = [m for m in measurements if m.sample_id in sample_ids]

        return measurements

    def _sample_ids_for(self, *, study_id: int | None, assay_id: int | None) -> set[int]:
        samples: list[Sample] = list(self._data.get(Sample, {}).values())
        if assay_id is not None:
            samples = [s for s in samples if s.assay_id == assay_id]
        if study_id is not None:
            assays: list[Assay] = list(self._data.get(Assay, {}).values())
            study_assay_ids = {a.id for a in assays if a.study_id == study_id}
            samples = [s for s in samples if s.assay_id in study_assay_ids]
        return {s.id for s in samples if s.id is not None}
