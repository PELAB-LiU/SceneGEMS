"""The session a store method works in: the caller's, or a transaction of its own.

The campaign, case, pipeline, result, artifact and calibration stores take an optional
session on every method. Without one the method runs in its own transaction. With one it
runs in the caller's transaction, so the pipeline engine can move cases, write results and
advance its event cursor in one commit:

    with stores.transaction() as session:
        batch = stores.pipeline.events_after(position, session=session)
        stores.cases.move_case(..., session=session)
        stores.pipeline.advance_cursor(ENGINE_CURSOR, position, batch.position, session=session)
"""

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.database import transaction


@contextmanager
def session_scope(session_factory: sessionmaker[Session], session: Optional[Session]) -> Iterator[Session]:
    if session is not None:
        yield session
        return
    with transaction(session_factory) as own:
        yield own
