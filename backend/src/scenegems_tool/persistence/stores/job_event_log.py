"""The append-only history of each job: one row per state change, never updated or deleted."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.schema import JobEventKind, JobEventRow, JobRow
from scenegems_tool.persistence.stores.job_records import JobEventRecord


def append_job_event(session: Session, job: JobRow, kind: JobEventKind, from_state: Optional[JobState], at: datetime, detail: Optional[Dict[str, Any]] = None) -> None:
    """Records the job's change from from_state to its current state, with its current lease."""
    session.add(
        JobEventRow(
            job_id=job.id,
            at=at,
            kind=kind,
            from_state=from_state,
            to_state=job.state,
            attempt=job.attempt,
            lease_id=job.lease_id,
            node_id=job.lease_owner,
            detail=detail or {},
        )
    )


def job_events(session: Session, job_id: str) -> List[JobEventRecord]:
    rows = session.execute(select(JobEventRow).where(JobEventRow.job_id == job_id).order_by(JobEventRow.id)).scalars()
    return [JobEventRecord.from_row(row) for row in rows]
