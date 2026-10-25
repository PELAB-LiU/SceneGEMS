import importlib

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.database import DATABASE_URL_ENV, DatabaseNotConfigured
from scenegems_tool.persistence.migrate import MIGRATIONS_FOLDER, alembic_config, main, upgrade_database
from scenegems_tool.persistence.schema import Base, JobEventKind, NodeStatus

CLUSTER_TABLES = {"node", "node_capability", "node_fingerprint", "job", "job_event"}


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config("postgresql://u:p@db/scenegems"))


def test_migrations_live_in_the_package():
    assert (MIGRATIONS_FOLDER / "env.py").is_file()
    assert _scripts().dir == str(MIGRATIONS_FOLDER)


def test_revisions_form_one_line():
    scripts = _scripts()
    assert scripts.get_heads() == ["0001"]
    revisions = list(scripts.walk_revisions())
    assert revisions[-1].down_revision is None
    assert all(len(revision.revision) == 4 and revision.revision.isdigit() for revision in revisions)


def test_url_with_percent_encoding_reaches_alembic_unchanged():
    assert alembic_config("postgresql://u:p%40ss@db/scenegems").get_main_option("sqlalchemy.url") == "postgresql+psycopg://u:p%40ss@db/scenegems"


def test_config_needs_a_url(monkeypatch):
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(DatabaseNotConfigured):
        alembic_config()


def test_first_revision_enum_values_match_the_code():
    # The revision spells the CHECK constraint values out; a new enum value needs a new revision
    first = importlib.import_module("scenegems_tool.persistence.migrations.versions.0001_cluster_tables")
    assert set(first.JOB_TYPES) == {job_type.value for job_type in JobType}
    assert set(first.JOB_STATES) == {state.value for state in JobState}
    assert set(first.NODE_STATUSES) == {status.value for status in NodeStatus}
    assert set(first.JOB_EVENT_KINDS) == {kind.value for kind in JobEventKind}


def test_offline_upgrade_renders_the_tables(capsys):
    command.upgrade(alembic_config("postgresql://u:p@db/scenegems"), "head", sql=True)
    sql = capsys.readouterr().out
    for table in CLUSTER_TABLES:
        assert f"CREATE TABLE {table} " in sql
    assert "WHERE state = 'queued'" in sql


@pytest.mark.postgres
def test_upgrade_on_an_empty_database(empty_database_url):
    upgrade_database(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        assert set(inspect(engine).get_table_names()) == CLUSTER_TABLES | {"alembic_version"}
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "0001"
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_upgraded_database_matches_the_tables(empty_database_url):
    upgrade_database(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
        assert differences == []
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_downgrade_to_base_and_upgrade_again(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_engine(empty_database_url)
    try:
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert CLUSTER_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_command_line_reads_the_environment(empty_database_url, monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, empty_database_url)
    main(["upgrade", "head"])
    engine = create_engine(empty_database_url)
    try:
        assert CLUSTER_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
