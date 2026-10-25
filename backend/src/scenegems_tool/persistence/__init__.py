"""The master's database: node registry and job store on Postgres.

Postgres only: the job store relies on JSONB and SELECT ... FOR UPDATE SKIP LOCKED.

    database.py      SCENEGEMS_DATABASE_URL, engine, session factory, transaction scope
    clock.py         the UTC clock the stores read, replaceable in tests
    migrate.py       Alembic configuration kept inside the package, upgrade, command line
    schema/          SQLAlchemy tables: node, node_capability, node_fingerprint, job, job_event
    migrations/      Alembic environment and revisions
    stores/          transactional primitives the master's registry and scheduler call
"""
