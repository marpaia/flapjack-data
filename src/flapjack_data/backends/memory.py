"""In-memory storage backend.

The reference Storage implementation: keeps entities in per-type dictionaries with a simple
id counter. Useful for tests, notebooks, and small in-process pipelines, and a worked example
for implementing other backends.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Iterator, TypeVar, cast

from flapjack_data.characterization.types import (
    AggregateValue,
    MeasurementFrameRow,
    Selection,
)
from flapjack_data.model import (
    Assay,
    Characterization,
    CharacterizationDatum,
    Measurement,
    Media,
    Sample,
    Signal,
    Strain,
    Supplement,
    Vector,
)
from flapjack_data.storage import CharacterizationStorage

T = TypeVar("T")


class InMemoryStorage(CharacterizationStorage):
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

    # Characterization -----------------------------------------------------------------

    def _samples_for_selection(self, selection: Selection) -> list[Sample]:
        if selection.is_empty():
            return []
        samples: list[Sample] = list(self._data.get(Sample, {}).values())
        if selection.sample_ids:
            wanted = set(selection.sample_ids)
            samples = [s for s in samples if s.id in wanted]
        if selection.assay_ids:
            wanted = set(selection.assay_ids)
            samples = [s for s in samples if s.assay_id in wanted]
        if selection.study_ids:
            assays: list[Assay] = list(self._data.get(Assay, {}).values())
            study_assay_ids = {a.id for a in assays if a.study_id in set(selection.study_ids)}
            samples = [s for s in samples if s.assay_id in study_assay_ids]
        if selection.vector_ids:
            wanted = set(selection.vector_ids)
            samples = [s for s in samples if s.vector_id in wanted]
        if selection.media_ids:
            wanted = set(selection.media_ids)
            samples = [s for s in samples if s.media_id in wanted]
        if selection.strain_ids:
            wanted = set(selection.strain_ids)
            samples = [s for s in samples if s.strain_id in wanted]
        return samples

    def _name(self, entity_type: type, entity_id: int | None) -> str | None:
        if entity_id is None:
            return None
        entity = self._data.get(entity_type, {}).get(entity_id)
        return getattr(entity, "name", None) if entity is not None else None

    def _concentrations(self, supplement_ids: list[int]) -> dict[int, float]:
        supplements = self._data.get(Supplement, {})
        out: dict[int, float] = {}
        for sid in supplement_ids:
            supp: Supplement | None = supplements.get(sid)
            if supp is not None:
                out[supp.chemical_id] = supp.concentration
        return out

    def measurement_frame(self, selection: Selection) -> Iterator[MeasurementFrameRow]:
        samples = {s.id: s for s in self._samples_for_selection(selection) if s.id is not None}
        if not samples:
            return
        assays: dict[int, Assay] = self._data.get(Assay, {})
        signals: dict[int, Signal] = self._data.get(Signal, {})
        signal_filter = set(selection.signal_ids)
        for meas in self._data.get(Measurement, {}).values():
            if meas.sample_id not in samples:
                continue
            if signal_filter and meas.signal_id not in signal_filter:
                continue
            sample = samples[meas.sample_id]
            assay = assays.get(sample.assay_id)
            signal = signals.get(meas.signal_id)
            yield MeasurementFrameRow(
                sample_id=meas.sample_id,
                signal_id=meas.signal_id,
                signal=signal.name if signal is not None else "",
                color=signal.color if signal is not None else "",
                value=meas.value,
                time=meas.time,
                assay_id=sample.assay_id,
                study_id=assay.study_id if assay is not None else 0,
                media=self._name(Media, sample.media_id),
                strain=self._name(Strain, sample.strain_id),
                vector=self._name(Vector, sample.vector_id),
                row=sample.row,
                col=sample.col,
                concentrations=self._concentrations(sample.supplement_ids),
            )

    def aggregate_measurements(self, *, func: str, selection: Selection) -> list[AggregateValue]:
        if func not in ("mean", "max"):
            raise ValueError(f"unsupported aggregate func: {func!r}")
        sample_ids = {s.id for s in self._samples_for_selection(selection)}
        if not sample_ids:
            return []
        signal_filter = set(selection.signal_ids)
        grouped: dict[tuple[int, int], list[float]] = {}
        for meas in self._data.get(Measurement, {}).values():
            if meas.sample_id not in sample_ids:
                continue
            if signal_filter and meas.signal_id not in signal_filter:
                continue
            grouped.setdefault((meas.sample_id, meas.signal_id), []).append(meas.value)
        out: list[AggregateValue] = []
        for (sample_id, signal_id), values in grouped.items():
            value = sum(values) / len(values) if func == "mean" else max(values)
            out.append(AggregateValue(sample_id=sample_id, signal_id=signal_id, value=value))
        return out

    def save_characterization(
        self, characterization: Characterization, data: list[CharacterizationDatum]
    ) -> Characterization:
        stored = self.add(characterization)
        assert stored.id is not None
        for datum in data:
            self.add(dataclasses.replace(datum, characterization_id=stored.id))
        return stored

    def get_characterization(self, characterization_id: int) -> Characterization | None:
        return self.get(Characterization, characterization_id)

    def query_characterizations(
        self, *, analysis_type: str | None = None, params_hash: str | None = None
    ) -> list[Characterization]:
        runs = self.list_all(Characterization)
        if analysis_type is not None:
            runs = [c for c in runs if c.analysis_type == analysis_type]
        if params_hash is not None:
            runs = [c for c in runs if c.params_hash == params_hash]
        return runs

    def get_characterization_data(self, characterization_id: int) -> list[CharacterizationDatum]:
        return [d for d in self.list_all(CharacterizationDatum) if d.characterization_id == characterization_id]
