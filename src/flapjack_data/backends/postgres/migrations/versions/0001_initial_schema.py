"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("public", sa.Boolean(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "assay",
        sa.Column("study_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("machine", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "media",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "strain",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chemical",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("pubchemid", sa.Integer(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "supplement",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("chemical_id", sa.Integer(), nullable=True),
        sa.Column("concentration", sa.Float(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "dna",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vector",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("dna_ids", sa.JSON(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "signal",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sample",
        sa.Column("assay_id", sa.Integer(), nullable=True),
        sa.Column("row", sa.Integer(), nullable=True),
        sa.Column("col", sa.Integer(), nullable=True),
        sa.Column("media_id", sa.Integer(), nullable=True),
        sa.Column("strain_id", sa.Integer(), nullable=True),
        sa.Column("vector_id", sa.Integer(), nullable=True),
        sa.Column("supplement_ids", sa.JSON(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "measurement",
        sa.Column("sample_id", sa.Integer(), nullable=True),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("time", sa.Float(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_measurement_sample", "measurement", ["sample_id"])
    op.create_index("ix_measurement_signal", "measurement", ["signal_id"])
    op.create_index("ix_measurement_owner", "measurement", ["owner"])


def downgrade() -> None:
    op.drop_index("ix_measurement_owner", table_name="measurement")
    op.drop_index("ix_measurement_signal", table_name="measurement")
    op.drop_index("ix_measurement_sample", table_name="measurement")
    op.drop_table("measurement")
    op.drop_table("sample")
    op.drop_table("signal")
    op.drop_table("vector")
    op.drop_table("dna")
    op.drop_table("supplement")
    op.drop_table("chemical")
    op.drop_table("strain")
    op.drop_table("media")
    op.drop_table("assay")
    op.drop_table("study")
