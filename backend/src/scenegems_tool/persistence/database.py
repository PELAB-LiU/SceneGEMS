"""Engine and sessions for the database named by SCENEGEMS_DATABASE_URL."""

import os
from contextlib import contextmanager
from typing import Iterator, Mapping, Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL_ENV = "SCENEGEMS_DATABASE_URL"
DRIVER = "psycopg"  # psycopg 3


class DatabaseNotConfigured(RuntimeError):
    pass


def database_url_from_env(environ: Optional[Mapping[str, str]] = None) -> str:
    environ = os.environ if environ is None else environ
    url = environ.get(DATABASE_URL_ENV, "").strip()
    if not url:
        raise DatabaseNotConfigured(f"{DATABASE_URL_ENV} is not set; expected a Postgres URL such as postgresql+psycopg://user:password@host:5432/scenegems")
    return url


def normalize_database_url(url: str) -> str:
    """Selects the psycopg 3 driver for plain postgresql:// URLs and rejects other databases."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError(f"the job store needs Postgres, got a {parsed.get_backend_name()} URL")
    if parsed.get_driver_name() != DRIVER:
        parsed = parsed.set(drivername=f"postgresql+{DRIVER}")
    return parsed.render_as_string(hide_password=False)


def create_database_engine(url: Optional[str] = None, **engine_options) -> Engine:
    """An engine for the given URL, or for SCENEGEMS_DATABASE_URL when none is given."""
    url = normalize_database_url(url or database_url_from_env())
    engine_options.setdefault("pool_pre_ping", True)
    return create_engine(url, **engine_options)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    # Store results are detached snapshots, so objects need not reload after commit.
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """One session and one transaction: committed on success, rolled back on error."""
    with session_factory() as session:
        with session.begin():
            yield session
