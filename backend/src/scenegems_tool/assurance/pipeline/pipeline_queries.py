"""Queries the engine needs beyond the store API, on the session of the engine's transaction.

They read jobs by id or key, retire an intent whose case ended before it was submitted, pin
a campaign's fingerprints, and find the jobs of final cases that still run. Each takes the
caller's session, so it joins the engine's transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Collection, Dict, List, Mapping, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.schema import CampaignRow, CaseState, JobRow, PipelineJobRow, ScenarioCaseRow

UNFINISHED_JOB_STATES = (JobState.QUEUED, JobState.LEASED, JobState.RUNNING)


@dataclass(frozen=True)
class JobFacts:
    """What a run record needs of its job: who ran it, on which fingerprints, and when."""

    job_id: str
    state: JobState
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    lease_owner: Optional[str]
    required_fingerprints: Dict[str, str]
    submitted_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    def durations_s(self) -> Dict[str, float]:
        """Seconds queued (submission to first accept), running (first accept to the end) and in total."""
        durations: Dict[str, float] = {}
        if self.started_at is not None:
            durations["queued_s"] = (self.started_at - self.submitted_at).total_seconds()
        if self.finished_at is not None:
            durations["total_s"] = (self.finished_at - self.submitted_at).total_seconds()
            if self.started_at is not None:
                durations["running_s"] = (self.finished_at - self.started_at).total_seconds()
        return durations


def job_facts(session: Session, job_ids: Collection[str]) -> Dict[str, JobFacts]:
    if not job_ids:
        return {}
    rows = session.execute(select(JobRow).where(JobRow.id.in_(sorted(set(job_ids)))).execution_options(populate_existing=True)).scalars()
    return {
        row.id: JobFacts(
            job_id=row.id,
            state=row.state,
            result=None if row.result is None else dict(row.result),
            error=row.error,
            lease_owner=row.lease_owner,
            required_fingerprints=dict(row.required_fingerprints),
            submitted_at=row.submitted_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
        for row in rows
    }


def job_id_by_key(session: Session, idempotency_key: str) -> Optional[str]:
    return session.execute(select(JobRow.id).where(JobRow.idempotency_key == idempotency_key)).scalar_one_or_none()


def delete_intent(session: Session, idempotency_key: str) -> bool:
    """Removes an intent that was never submitted; False when it is linked to a job (or gone)."""
    statement = delete(PipelineJobRow).where(PipelineJobRow.idempotency_key == idempotency_key, PipelineJobRow.job_id.is_(None)).execution_options(synchronize_session=False)
    return session.execute(statement).rowcount > 0


def pin_fingerprints(session: Session, campaign_id: str, fingerprints: Mapping[str, str], now: datetime) -> bool:
    """Sets the campaign's pinned fingerprints if it has none; False when it had some already."""
    statement = (
        update(CampaignRow)
        .where(CampaignRow.id == campaign_id, CampaignRow.pinned_fingerprints == {})
        .values(pinned_fingerprints=dict(fingerprints), updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return session.execute(statement).rowcount > 0


def unfinished_jobs_of_cases(session: Session, case_ids: Collection[int]) -> List[str]:
    if not case_ids:
        return []
    query = select(PipelineJobRow.job_id).join(JobRow, JobRow.id == PipelineJobRow.job_id).where(PipelineJobRow.case_id.in_(sorted(set(case_ids))), JobRow.state.in_(list(UNFINISHED_JOB_STATES)))
    return sorted(session.execute(query).scalars())


def unfinished_jobs_of_final_cases(session: Session, campaign_id: str) -> List[str]:
    """Jobs still queued or running for cases that ended: left over when a cancel did not happen before a crash."""
    query = (
        select(PipelineJobRow.job_id)
        .join(JobRow, JobRow.id == PipelineJobRow.job_id)
        .join(ScenarioCaseRow, ScenarioCaseRow.id == PipelineJobRow.case_id)
        .where(PipelineJobRow.campaign_id == campaign_id, ScenarioCaseRow.state != CaseState.ACTIVE, JobRow.state.in_(list(UNFINISHED_JOB_STATES)))
    )
    return sorted(session.execute(query).scalars())


def next_case_indexes(session: Session, campaign_id: str) -> Dict[str, int]:
    """Per class with cases, one past its highest case index."""
    query = select(ScenarioCaseRow.class_id, func.max(ScenarioCaseRow.case_index)).where(ScenarioCaseRow.campaign_id == campaign_id).group_by(ScenarioCaseRow.class_id)
    return {class_id: highest + 1 for class_id, highest in session.execute(query)}


def case_states(session: Session, case_ids: Collection[int]) -> Dict[int, CaseState]:
    if not case_ids:
        return {}
    query = select(ScenarioCaseRow.id, ScenarioCaseRow.state).where(ScenarioCaseRow.id.in_(sorted(set(case_ids))))
    return {case_id: state for case_id, state in session.execute(query)}
