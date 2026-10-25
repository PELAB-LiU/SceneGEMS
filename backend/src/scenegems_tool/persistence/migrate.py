"""Alembic configuration kept inside the package, and the migration command line.

No alembic.ini is needed: the script location is this package's migrations folder and
the database URL comes from the caller or from SCENEGEMS_DATABASE_URL. From backend/:

    PYTHONPATH=src python -m scenegems_tool.persistence.migrate upgrade head
    PYTHONPATH=src python -m scenegems_tool.persistence.migrate revision --autogenerate -m "add campaign"

Every Alembic command works this way (current, history, downgrade, ...).
"""

import logging
import sys
from pathlib import Path
from typing import List, Optional

from alembic import command
from alembic.config import CommandLine, Config
from sqlalchemy import Connection

from scenegems_tool.persistence.database import database_url_from_env, normalize_database_url

MIGRATIONS_FOLDER = Path(__file__).resolve().parent / "migrations"
CONNECTION_ATTRIBUTE = "connection"  # an open connection handed to env.py instead of a URL


def alembic_config(url: Optional[str] = None, connection: Optional[Connection] = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_FOLDER))
    config.set_main_option("file_template", "%%(rev)s_%%(slug)s")
    if connection is not None:
        config.attributes[CONNECTION_ATTRIBUTE] = connection
    else:
        # ConfigParser interpolates "%", which a URL-encoded password may contain
        config.set_main_option("sqlalchemy.url", normalize_database_url(url or database_url_from_env()).replace("%", "%%"))
    return config


def upgrade_database(url: Optional[str] = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")  # Alembic reports each step
    command_line = CommandLine(prog="python -m scenegems_tool.persistence.migrate")
    options = command_line.parser.parse_args(argv)
    if not hasattr(options, "cmd"):
        command_line.parser.error("too few arguments")
    command_line.run_cmd(alembic_config(), options)


if __name__ == "__main__":
    main(sys.argv[1:])
