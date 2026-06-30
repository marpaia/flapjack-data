"""Command-line interface: ``flapjack-data`` (requires the ``[postgres]`` extra)."""

import argparse

from flapjack_data.backends.postgres import migrations


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="flapjack-data", description="flapjack-data schema migrations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate", help="upgrade the schema to a revision (default: head)")
    migrate.add_argument("--database-url", required=True)
    migrate.add_argument("--revision", default="head")

    downgrade = subparsers.add_parser("downgrade", help="downgrade the schema to a revision")
    downgrade.add_argument("--database-url", required=True)
    downgrade.add_argument("--revision", required=True)

    current = subparsers.add_parser("current", help="show the current revision")
    current.add_argument("--database-url", required=True)

    args = parser.parse_args(argv)
    if args.command == "migrate":
        migrations.upgrade(args.database_url, args.revision)
    elif args.command == "downgrade":
        migrations.downgrade(args.database_url, args.revision)
    elif args.command == "current":
        migrations.current(args.database_url)


if __name__ == "__main__":
    main()
