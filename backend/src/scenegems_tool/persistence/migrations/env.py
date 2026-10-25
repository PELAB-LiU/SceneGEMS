"""Alembic environment: migrates the database of the config's URL or of a given connection."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from scenegems_tool.persistence.migrate import CONNECTION_ATTRIBUTE
from scenegems_tool.persistence.schema import Base

TARGET_METADATA = Base.metadata


def _run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=TARGET_METADATA, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(url=context.config.get_main_option("sqlalchemy.url"), target_metadata=TARGET_METADATA, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = context.config.attributes.get(CONNECTION_ATTRIBUTE)
    if connection is not None:
        _run_migrations(connection)
        return
    engine = engine_from_config(context.config.get_section(context.config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
