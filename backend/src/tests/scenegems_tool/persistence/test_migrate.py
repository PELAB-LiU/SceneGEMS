import importlib
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.database import DATABASE_URL_ENV, DatabaseNotConfigured
from scenegems_tool.persistence.migrate import MIGRATIONS_FOLDER, alembic_config, main, upgrade_database
from scenegems_tool.persistence.schema import (
    ArtifactHolderKind,
    Base,
    CampaignActualState,
    CampaignClassState,
    CampaignDesiredState,
    CampaignEventKind,
    CaseState,
    JobEventKind,
    MonitorImplementation,
    NodeStatus,
    PipelineStage,
    TrajectoryGeneratorImplementation,
    VerdictState,
)
from tests.scenegems_tool.persistence.schema.test_tables import CAMPAIGN_TABLES, CLUSTER_TABLES

ALL_TABLES = CLUSTER_TABLES | CAMPAIGN_TABLES


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config("postgresql://u:p@db/scenegems"))


def _revision(module: str):
    return importlib.import_module(f"scenegems_tool.persistence.migrations.versions.{module}")


def _values(enum_class) -> set:
    return {member.value for member in enum_class}


def test_migrations_live_in_the_package():
    assert (MIGRATIONS_FOLDER / "env.py").is_file()
    assert _scripts().dir == str(MIGRATIONS_FOLDER)


def test_revisions_form_one_line():
    scripts = _scripts()
    assert scripts.get_heads() == ["0004"]
    revisions = list(scripts.walk_revisions())
    assert [revision.revision for revision in revisions] == ["0004", "0003", "0002", "0001"]
    assert revisions[0].down_revision == "0003"
    assert revisions[1].down_revision == "0002"
    assert revisions[2].down_revision == "0001"
    assert revisions[-1].down_revision is None
    assert all(len(revision.revision) == 4 and revision.revision.isdigit() for revision in revisions)


def test_url_with_percent_encoding_reaches_alembic_unchanged():
    assert alembic_config("postgresql://u:p%40ss@db/scenegems").get_main_option("sqlalchemy.url") == "postgresql+psycopg://u:p%40ss@db/scenegems"


def test_config_needs_a_url(monkeypatch):
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(DatabaseNotConfigured):
        alembic_config()


def test_revision_enum_values_match_the_code():
    # The revisions spell the CHECK constraint values out; a new enum value needs a new revision.
    # Each enum is checked against the latest revision that names its values.
    first, second = _revision("0001_cluster_tables"), _revision("0002_campaigns")
    assert set(first.JOB_TYPES) == set(second.PREVIOUS_JOB_TYPES)
    assert set(second.JOB_TYPES) == _values(JobType)
    assert set(first.JOB_STATES) == _values(JobState)
    assert set(first.NODE_STATUSES) == _values(NodeStatus)
    assert set(first.JOB_EVENT_KINDS) == _values(JobEventKind)
    assert set(second.CAMPAIGN_DESIRED_STATES) == _values(CampaignDesiredState)
    assert set(second.CAMPAIGN_ACTUAL_STATES) == _values(CampaignActualState)
    assert set(second.CAMPAIGN_CLASS_STATES) == _values(CampaignClassState)
    assert set(second.PIPELINE_STAGES) == _values(PipelineStage)
    assert set(second.CASE_STATES) == _values(CaseState)
    assert set(second.TRAJECTORY_GENERATORS) == _values(TrajectoryGeneratorImplementation)
    assert set(second.MONITORS) == _values(MonitorImplementation)
    assert set(second.VERDICT_STATES) == _values(VerdictState)
    assert set(second.CAMPAIGN_EVENT_KINDS) == _values(CampaignEventKind)
    assert set(second.ARTIFACT_HOLDER_KINDS) == _values(ArtifactHolderKind)


def test_offline_upgrade_renders_the_tables(capsys):
    command.upgrade(alembic_config("postgresql://u:p@db/scenegems"), "head", sql=True)
    sql = capsys.readouterr().out
    for table in ALL_TABLES:
        assert f"CREATE TABLE {table} " in sql
    assert "WHERE state = 'queued'" in sql
    assert "ALTER TABLE job ADD COLUMN available_at" in sql
    assert "UPDATE job SET available_at = submitted_at" in sql
    assert "calibration.deviation" in sql
    assert "ALTER TABLE node ADD COLUMN machine VARCHAR(256)" in sql
    assert "ALTER TABLE job ADD COLUMN allowed_nodes JSONB DEFAULT '[]'::jsonb NOT NULL" in sql


@pytest.mark.postgres
def test_upgrade_on_an_empty_database(empty_database_url):
    upgrade_database(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        assert set(inspect(engine).get_table_names()) == ALL_TABLES | {"alembic_version"}
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "0004"
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
def test_upgrade_keeps_existing_jobs_available_since_their_submission(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0001")
    submitted = datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc)
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job (id, job_type, payload, required_labels, required_fingerprints, min_memory_mb, min_cpus, priority, max_attempts,"
                    " idempotency_key, state, attempt, failed_attempts, submitted_at, updated_at)"
                    " VALUES ('job-1', 'scene_generation', '{}', '{}', '{}', 0, 0, 0, 3, 'key-1', 'queued', 0, 0, :at, :at)"
                ),
                {"at": submitted},
            )
            connection.execute(text("INSERT INTO job_event (job_id, at, kind, to_state, attempt, detail) VALUES ('job-1', :at, 'submitted', 'queued', 0, '{}')"), {"at": submitted})
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT available_at FROM job WHERE id = 'job-1'")).scalar_one() == submitted
            assert connection.execute(text("SELECT tx_id FROM job_event WHERE job_id = 'job-1'")).scalar_one() > 0
            # the new job type is accepted now
            connection.execute(text("UPDATE job SET job_type = 'calibration.deviation' WHERE id = 'job-1'"))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_the_machine_column_comes_and_goes_with_revision_0003(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0002")
    engine = create_engine(empty_database_url)
    registered = datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc)
    try:
        assert "machine" not in {column["name"] for column in inspect(engine).get_columns("node")}
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO node (id, name, status, labels, software_revision, cpus, memory_mb, free_memory_mb, free_disk_mb, load_average, registered_at, last_seen_at)"
                    " VALUES ('node-1', 'worker-1', 'online', '{}', 'abc', 4, 1000, 500, 5000, 0.1, :at, :at)"
                ),
                {"at": registered},
            )
        command.upgrade(config, "0003")
        columns = {column["name"]: column for column in inspect(engine).get_columns("node")}
        assert columns["machine"]["nullable"] and str(columns["machine"]["type"]) == "VARCHAR(256)"
        with engine.begin() as connection:
            assert connection.execute(text("SELECT machine FROM node WHERE id = 'node-1'")).scalar_one() is None  # nodes of before say hello again
            connection.execute(text("UPDATE node SET machine = 'lab-pc-3' WHERE id = 'node-1'"))
        command.downgrade(config, "0002")
        assert "machine" not in {column["name"] for column in inspect(engine).get_columns("node")}
        with engine.connect() as connection:
            assert connection.execute(text("SELECT name FROM node WHERE id = 'node-1'")).scalar_one() == "worker-1"  # the node stays
        command.upgrade(config, "head")
        assert "machine" in {column["name"] for column in inspect(engine).get_columns("node")}
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_jobs_of_before_revision_0004_may_run_on_any_node(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0003")
    submitted = datetime(2026, 10, 27, 9, 30, tzinfo=timezone.utc)
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job (id, job_type, payload, required_labels, required_fingerprints, min_memory_mb, min_cpus, priority, max_attempts,"
                    " idempotency_key, state, attempt, failed_attempts, submitted_at, available_at, updated_at)"
                    " VALUES ('job-1', 'scene_generation', '{}', '{}', '{}', 0, 0, 0, 3, 'key-1', 'queued', 0, 0, :at, :at, :at)"
                ),
                {"at": submitted},
            )
        command.upgrade(config, "0004")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT allowed_nodes FROM job WHERE id = 'job-1'")).scalar_one() == []
        command.downgrade(config, "0003")
        assert "allowed_nodes" not in {column["name"] for column in inspect(engine).get_columns("job")}
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_downgrade_to_the_cluster_tables_and_upgrade_again(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "0001")
    engine = create_engine(empty_database_url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == CLUSTER_TABLES | {"alembic_version"}
        assert "available_at" not in {column["name"] for column in inspector.get_columns("job")}
        assert "tx_id" not in {column["name"] for column in inspector.get_columns("job_event")}
        command.upgrade(config, "head")
        assert ALL_TABLES <= set(inspect(engine).get_table_names())
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
        assert ALL_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_command_line_reads_the_environment(empty_database_url, monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, empty_database_url)
    main(["upgrade", "head"])
    engine = create_engine(empty_database_url)
    try:
        assert ALL_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
