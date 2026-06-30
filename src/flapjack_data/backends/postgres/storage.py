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
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

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
    insert,
    select,
)
from sqlalchemy.engine import Engine

from flapjack_data.model import ENTITY_TYPES, Assay, Measurement, Sample
from flapjack_data.storage import Storage

T = TypeVar("T")

metadata = MetaData()


def _column_type(annotation: Any) -> Any:
    """Map a dataclass field annotation to a SQLAlchemy column type."""
    if get_origin(annotation) is list:
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


class PostgresStorage(Storage):
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
