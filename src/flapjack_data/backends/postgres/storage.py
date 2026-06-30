"""SQLAlchemy storage backend.

A `Storage` implementation backed by SQLAlchemy, intended for Postgres/TimescaleDB but usable
with any SQLAlchemy-supported database. Tables are derived from the domain dataclasses, so the
schema stays in sync with the model automatically.

Multi-tenant use: construct with ``owner=<key>`` and the backend stamps that owner on every
write and filters every read by it. Deployments that also want database-enforced isolation
(e.g. Postgres row-level security on the ``owner`` column) can layer that on top.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Iterator, TypeVar, cast, get_args, get_origin, get_type_hints

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    create_engine,
)
from sqlalchemy import func as sa_func
from sqlalchemy import (
    insert,
    select,
)
from sqlalchemy.engine import Engine

from flapjack_data.characterization.types import (
    AggregateValue,
    MeasurementFrameRow,
    Selection,
)
from flapjack_data.model import (
    ENTITY_TYPES,
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

metadata = MetaData()


def _column_type(annotation: Any) -> Any:
    """Map a dataclass field annotation to a SQLAlchemy column type."""
    if get_origin(annotation) is list or get_origin(annotation) is dict or annotation is dict:
        return JSON
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if args:
        return _column_type(args[0])
    if annotation is bool:
        return Boolean
    if annotation is int:
        return Integer
    if annotation is float:
        return Float
    return String


def _build_tables() -> dict[type, Table]:
    tables: dict[type, Table] = {}
    for entity_type in ENTITY_TYPES:
        hints = get_type_hints(entity_type)
        columns = []
        for field_name, annotation in hints.items():
            if field_name == "id":
                columns.append(Column("id", Integer, primary_key=True, autoincrement=True))
            else:
                columns.append(Column(field_name, _column_type(annotation), nullable=True))
        tables[entity_type] = Table(entity_type.__name__.lower(), metadata, *columns)
    return tables


_TABLES = _build_tables()


class PostgresStorage(CharacterizationStorage):
    def __init__(self, engine: Engine | str, *, owner: str | None = None, create: bool = False) -> None:
        self._engine = create_engine(engine) if isinstance(engine, str) else engine
        self._owner = owner
        if create:
            metadata.create_all(self._engine)

    def add(self, entity: T) -> T:
        table = _TABLES[type(entity)]
        fields = dataclasses.fields(cast(Any, entity))
        data = {f.name: getattr(entity, f.name) for f in fields if f.name != "id"}
        if self._owner is not None:
            data["owner"] = self._owner
        with self._engine.begin() as conn:
            result = conn.execute(insert(table).values(**data))
            inserted = result.inserted_primary_key
            assert inserted is not None
            new_id = inserted[0]
        replacements: dict[str, Any] = {"id": new_id}
        if self._owner is not None:
            replacements["owner"] = self._owner
        return cast(T, dataclasses.replace(cast(Any, entity), **replacements))

    def get(self, entity_type: type[T], entity_id: int) -> T | None:
        table = _TABLES[entity_type]
        conditions = [table.c.id == entity_id]
        if self._owner is not None:
            conditions.append(table.c.owner == self._owner)
        with self._engine.begin() as conn:
            row = conn.execute(select(table).where(and_(*conditions))).mappings().first()
        return entity_type(**row) if row is not None else None

    def list_all(self, entity_type: type[T]) -> list[T]:
        table = _TABLES[entity_type]
        statement = select(table)
        if self._owner is not None:
            statement = statement.where(table.c.owner == self._owner)
        with self._engine.begin() as conn:
            rows = conn.execute(statement).mappings().all()
        return [entity_type(**row) for row in rows]

    def query_measurements(
        self,
        *,
        study_id: int | None = None,
        assay_id: int | None = None,
        sample_id: int | None = None,
        signal_id: int | None = None,
    ) -> list[Measurement]:
        measurements = _TABLES[Measurement]
        samples = _TABLES[Sample]
        assays = _TABLES[Assay]

        statement = select(measurements)
        conditions = []
        if self._owner is not None:
            conditions.append(measurements.c.owner == self._owner)
        if signal_id is not None:
            conditions.append(measurements.c.signal_id == signal_id)
        if sample_id is not None:
            conditions.append(measurements.c.sample_id == sample_id)

        if assay_id is not None or study_id is not None:
            joined = measurements.join(samples, measurements.c.sample_id == samples.c.id)
            if study_id is not None:
                joined = joined.join(assays, samples.c.assay_id == assays.c.id)
                conditions.append(assays.c.study_id == study_id)
            if assay_id is not None:
                conditions.append(samples.c.assay_id == assay_id)
            statement = statement.select_from(joined)

        if conditions:
            statement = statement.where(and_(*conditions))
        with self._engine.begin() as conn:
            rows = conn.execute(statement).mappings().all()
        return [Measurement(**row) for row in rows]

    # Characterization -----------------------------------------------------------------

    def _selection_conditions(
        self, selection: Selection, measurements: Table, samples: Table, assays: Table
    ) -> list[Any]:
        conditions: list[Any] = []
        if self._owner is not None:
            conditions.append(measurements.c.owner == self._owner)
        if selection.study_ids:
            conditions.append(assays.c.study_id.in_(selection.study_ids))
        if selection.assay_ids:
            conditions.append(samples.c.assay_id.in_(selection.assay_ids))
        if selection.sample_ids:
            conditions.append(samples.c.id.in_(selection.sample_ids))
        if selection.vector_ids:
            conditions.append(samples.c.vector_id.in_(selection.vector_ids))
        if selection.media_ids:
            conditions.append(samples.c.media_id.in_(selection.media_ids))
        if selection.strain_ids:
            conditions.append(samples.c.strain_id.in_(selection.strain_ids))
        if selection.signal_ids:
            conditions.append(measurements.c.signal_id.in_(selection.signal_ids))
        return conditions

    def _load_supplements(self) -> dict[int, tuple[int, float]]:
        supplements = _TABLES[Supplement]
        statement = select(supplements.c.id, supplements.c.chemical_id, supplements.c.concentration)
        if self._owner is not None:
            statement = statement.where(supplements.c.owner == self._owner)
        with self._engine.begin() as conn:
            rows = conn.execute(statement).mappings().all()
        return {row["id"]: (row["chemical_id"], row["concentration"]) for row in rows}

    def measurement_frame(self, selection: Selection) -> Iterator[MeasurementFrameRow]:
        if selection.is_empty():
            return
        measurements = _TABLES[Measurement]
        samples = _TABLES[Sample]
        assays = _TABLES[Assay]
        signals = _TABLES[Signal]
        media = _TABLES[Media]
        strains = _TABLES[Strain]
        vectors = _TABLES[Vector]

        statement = select(
            measurements.c.sample_id,
            measurements.c.signal_id,
            signals.c.name.label("signal"),
            signals.c.color.label("color"),
            measurements.c.value,
            measurements.c.time,
            samples.c.assay_id,
            assays.c.study_id,
            media.c.name.label("media"),
            strains.c.name.label("strain"),
            vectors.c.name.label("vector"),
            samples.c.row,
            samples.c.col,
            samples.c.supplement_ids,
        )
        joined = (
            measurements.join(samples, measurements.c.sample_id == samples.c.id)
            .join(assays, samples.c.assay_id == assays.c.id)
            .outerjoin(signals, measurements.c.signal_id == signals.c.id)
            .outerjoin(media, samples.c.media_id == media.c.id)
            .outerjoin(strains, samples.c.strain_id == strains.c.id)
            .outerjoin(vectors, samples.c.vector_id == vectors.c.id)
        )
        statement = statement.select_from(joined)
        conditions = self._selection_conditions(selection, measurements, samples, assays)
        if conditions:
            statement = statement.where(and_(*conditions))
        # Ordered to match the engine's per-(sample, signal) sorted processing and the
        # ix_measurement_sample_signal_time index.
        statement = statement.order_by(measurements.c.sample_id, measurements.c.signal_id, measurements.c.time)

        supplement_map = self._load_supplements()
        # A streaming connection so the (large) measurement table is never materialized whole.
        with self._engine.connect() as conn:
            result = conn.execution_options(stream_results=True).execute(statement)
            for row in result.mappings():
                concentrations: dict[int, float] = {}
                for supplement_id in row["supplement_ids"] or []:
                    entry = supplement_map.get(supplement_id)
                    if entry is not None:
                        concentrations[entry[0]] = entry[1]
                yield MeasurementFrameRow(
                    sample_id=row["sample_id"],
                    signal_id=row["signal_id"],
                    signal=row["signal"] or "",
                    color=row["color"] or "",
                    value=row["value"],
                    time=row["time"],
                    assay_id=row["assay_id"],
                    study_id=row["study_id"] if row["study_id"] is not None else 0,
                    media=row["media"],
                    strain=row["strain"],
                    vector=row["vector"],
                    row=row["row"] if row["row"] is not None else 0,
                    col=row["col"] if row["col"] is not None else 0,
                    concentrations=concentrations,
                )

    def aggregate_measurements(self, *, func: str, selection: Selection) -> list[AggregateValue]:
        if func not in ("mean", "max"):
            raise ValueError(f"unsupported aggregate func: {func!r}")
        if selection.is_empty():
            return []
        measurements = _TABLES[Measurement]
        samples = _TABLES[Sample]
        assays = _TABLES[Assay]

        reducer = sa_func.avg if func == "mean" else sa_func.max
        statement = select(
            measurements.c.sample_id,
            measurements.c.signal_id,
            reducer(measurements.c.value).label("value"),
        )
        joined = measurements.join(samples, measurements.c.sample_id == samples.c.id).join(
            assays, samples.c.assay_id == assays.c.id
        )
        statement = statement.select_from(joined).group_by(measurements.c.sample_id, measurements.c.signal_id)
        conditions = self._selection_conditions(selection, measurements, samples, assays)
        if conditions:
            statement = statement.where(and_(*conditions))
        with self._engine.begin() as conn:
            rows = conn.execute(statement).mappings().all()
        return [
            AggregateValue(sample_id=row["sample_id"], signal_id=row["signal_id"], value=row["value"]) for row in rows
        ]

    def save_characterization(
        self, characterization: Characterization, data: list[CharacterizationDatum]
    ) -> Characterization:
        stored = self.add(characterization)
        assert stored.id is not None
        if data:
            table = _TABLES[CharacterizationDatum]
            rows = []
            for datum in data:
                values = {f.name: getattr(datum, f.name) for f in dataclasses.fields(datum) if f.name != "id"}
                values["characterization_id"] = stored.id
                if self._owner is not None:
                    values["owner"] = self._owner
                rows.append(values)
            with self._engine.begin() as conn:
                conn.execute(insert(table), rows)
        return stored

    def get_characterization(self, characterization_id: int) -> Characterization | None:
        return self.get(Characterization, characterization_id)

    def query_characterizations(
        self, *, analysis_type: str | None = None, params_hash: str | None = None
    ) -> list[Characterization]:
        table = _TABLES[Characterization]
        statement = select(table)
        conditions = []
        if self._owner is not None:
            conditions.append(table.c.owner == self._owner)
        if analysis_type is not None:
            conditions.append(table.c.analysis_type == analysis_type)
        if params_hash is not None:
            conditions.append(table.c.params_hash == params_hash)
        if conditions:
            statement = statement.where(and_(*conditions))
        with self._engine.begin() as conn:
            rows = conn.execute(statement).mappings().all()
        return [Characterization(**row) for row in rows]

    def get_characterization_data(self, characterization_id: int) -> list[CharacterizationDatum]:
        table = _TABLES[CharacterizationDatum]
        conditions = [table.c.characterization_id == characterization_id]
        if self._owner is not None:
            conditions.append(table.c.owner == self._owner)
        with self._engine.begin() as conn:
            rows = conn.execute(select(table).where(and_(*conditions))).mappings().all()
        return [CharacterizationDatum(**row) for row in rows]
