"""characterization

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Optional signal role hint (fluorescence / biomass / od / other).
    op.add_column("signal", sa.Column("kind", sa.String(), nullable=True))

    # Persisted characterization runs and their results, so a backend can cache and re-serve
    # what Flapjack recomputes on every request.
    op.create_table(
        "characterization",
        sa.Column("analysis_type", sa.String(), nullable=True),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("params_hash", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_characterization_params_hash", "characterization", ["params_hash"])
    op.create_index("ix_characterization_owner", "characterization", ["owner"])

    op.create_table(
        "characterizationdatum",
        sa.Column("characterization_id", sa.Integer(), nullable=True),
        sa.Column("sample_id", sa.Integer(), nullable=True),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("metric", sa.String(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("time", sa.Float(), nullable=True),
        sa.Column("concentration", sa.Float(), nullable=True),
        sa.Column("concentration2", sa.Float(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_characterizationdatum_characterization",
        "characterizationdatum",
        ["characterization_id"],
    )

    # Composite index for the ordered per-(sample, signal) reads the analysis engine does.
    op.create_index(
        "ix_measurement_sample_signal_time",
        "measurement",
        ["sample_id", "signal_id", "time"],
    )


def downgrade() -> None:
    op.drop_index("ix_measurement_sample_signal_time", table_name="measurement")
    op.drop_index("ix_characterizationdatum_characterization", table_name="characterizationdatum")
    op.drop_table("characterizationdatum")
    op.drop_index("ix_characterization_owner", table_name="characterization")
    op.drop_index("ix_characterization_params_hash", table_name="characterization")
    op.drop_table("characterization")
    op.drop_column("signal", "kind")
