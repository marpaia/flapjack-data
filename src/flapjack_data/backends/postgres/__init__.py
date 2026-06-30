"""Postgres/SQLAlchemy backend (optional extra: ``flapjack-data[postgres]``).

Contains everything Postgres-specific: the `PostgresStorage` implementation, the SQLAlchemy
table `metadata`, and the schema `migrations` subpackage.
"""

from flapjack_data.backends.postgres.storage import PostgresStorage, metadata

__all__ = ["PostgresStorage", "metadata"]
