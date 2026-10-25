import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, func, select

from scenegems_tool.persistence.database import (
    DATABASE_URL_ENV,
    DatabaseNotConfigured,
    create_database_engine,
    create_session_factory,
    database_url_from_env,
    normalize_database_url,
    transaction,
)


def test_url_comes_from_the_environment():
    assert database_url_from_env({DATABASE_URL_ENV: " postgresql://u:p@db/scenegems "}) == "postgresql://u:p@db/scenegems"


@pytest.mark.parametrize("environ", [{}, {DATABASE_URL_ENV: "  "}])
def test_missing_url_names_the_variable(environ):
    with pytest.raises(DatabaseNotConfigured, match=DATABASE_URL_ENV):
        database_url_from_env(environ)


@pytest.mark.parametrize(
    "url",
    ["postgresql://u:p@db:5432/scenegems", "postgresql+psycopg2://u:p@db:5432/scenegems", "postgresql+psycopg://u:p@db:5432/scenegems"],
)
def test_postgres_urls_use_psycopg_3(url):
    assert normalize_database_url(url) == "postgresql+psycopg://u:p@db:5432/scenegems"


def test_password_survives_normalization():
    assert normalize_database_url("postgresql://u:p%40ss@db/scenegems") == "postgresql+psycopg://u:p%40ss@db/scenegems"


def test_other_databases_are_rejected():
    with pytest.raises(ValueError, match="needs Postgres"):
        normalize_database_url("sqlite:///jobs.db")


def test_engine_is_created_without_connecting():
    engine = create_database_engine("postgresql://u:p@unreachable.invalid/scenegems")
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.pool._pre_ping
    engine.dispose()


def test_engine_reads_the_environment(monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql://u:p@db/from_env")
    engine = create_database_engine()
    assert engine.url.database == "from_env"
    engine.dispose()


def _counter_table():
    # transaction() is database independent, so SQLite in memory is enough here
    engine = create_engine("sqlite://")
    table = Table("counter", MetaData(), Column("id", Integer, primary_key=True))
    table.metadata.create_all(engine)
    return engine, table


def test_transaction_commits_on_success():
    engine, table = _counter_table()
    sessions = create_session_factory(engine)
    with transaction(sessions) as session:
        session.execute(table.insert().values(id=1))
    with transaction(sessions) as session:
        assert session.execute(select(func.count()).select_from(table)).scalar_one() == 1


def test_transaction_rolls_back_on_error():
    engine, table = _counter_table()
    sessions = create_session_factory(engine)
    with pytest.raises(RuntimeError):
        with transaction(sessions) as session:
            session.execute(table.insert().values(id=1))
            raise RuntimeError("boom")
    with transaction(sessions) as session:
        assert session.execute(select(func.count()).select_from(table)).scalar_one() == 0
