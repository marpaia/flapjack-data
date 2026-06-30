"""Schema migrations for the Postgres backend.

`flapjack-data` ships its own Alembic migration chain so the schema can evolve reliably. It
uses a dedicated version table (``flapjack_data_version``) and manages only its own tables, so
it coexists with the migration chain of any application that embeds it — two independent
chains against one database, no collision.

Run programmatically:

    from flapjack_data.backends.postgres import migrations
    migrations.upgrade("postgresql+psycopg://user:pass@host/db")

or from the command line: ``flapjack-data migrate --database-url ...``.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

_MIGRATIONS_DIR = Path(__file__).resolve().parent


def _config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    return config


def upgrade(url: str, revision: str = "head") -> None:
    """Upgrade the database at ``url`` to ``revision`` (default: latest)."""
    command.upgrade(_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    """Downgrade the database at ``url`` to ``revision``."""
    command.downgrade(_config(url), revision)


def current(url: str) -> None:
    """Print the current revision of the database at ``url``."""
    command.current(_config(url))
