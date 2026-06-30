from pathlib import Path

from sqlalchemy import create_engine, inspect

from flapjack_data.backends.postgres import migrations


def test_migrations_create_schema_and_version_table(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'flapjack.db'}"
    migrations.upgrade(url)

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {"study", "assay", "sample", "signal", "measurement"} <= tables
    # The dedicated version table keeps this chain independent of a host app's Alembic.
    assert "flapjack_data_version" in tables


def test_migrations_downgrade_to_base(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'flapjack.db'}"
    migrations.upgrade(url)
    migrations.downgrade(url, "base")

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "measurement" not in tables
