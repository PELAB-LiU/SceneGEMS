"""What a node can take, and the query that finds the next queued job for it.

The node's facts (free slots per job type, labels, fingerprints, resources) are read under
a lock on the node row, so concurrent claims for one node never exceed its slots. The job
itself is picked in SQL with SELECT ... FOR UPDATE SKIP LOCKED: concurrent claims for
different nodes skip the rows another claim holds instead of waiting for it, and no job is
claimed twice.
"""

from typing import Collection, Dict, List, Mapping, Optional

from sqlalchemy import Select, select

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.schema import JobRow


def free_job_types(slots: Mapping[JobType, int], active_leases: Mapping[JobType, int], only: Optional[Collection[JobType]] = None) -> List[JobType]:
    """Job types the node offers and has a free slot for, optionally limited to `only`."""
    return [job_type for job_type, count in slots.items() if active_leases.get(job_type, 0) < count and (only is None or job_type in only)]


def next_queued_job_query(job_types: Collection[JobType], labels: Dict[str, str], fingerprints: Dict[str, str], free_memory_mb: int, cpus: float) -> Select:
    """The highest-priority, oldest queued job a node with these facts may run, locked.

    A job matches when its type is among job_types, its required labels and fingerprints
    are contained in the node's (JSONB containment) and its memory and CPU minimums fit the
    node's free memory and CPUs.
    """
    return (
        select(JobRow)
        .where(
            JobRow.state == JobState.QUEUED,
            JobRow.job_type.in_(list(job_types)),
            JobRow.required_labels.contained_by(labels),
            JobRow.required_fingerprints.contained_by(fingerprints),
            JobRow.min_memory_mb <= free_memory_mb,
            JobRow.min_cpus <= cpus,
        )
        .order_by(JobRow.priority.desc(), JobRow.submitted_at, JobRow.seq)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
