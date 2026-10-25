"""Builders for node and job messages, and a clock the tests move by hand."""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import Hello
from scenegems_tool.cluster.protocol.node_description import CapabilityOffer, NodeResources

START = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


class ManualClock:
    """A clock that moves only when the test advances it."""

    def __init__(self, now: datetime = START):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


def make_resources(cpus: float = 8.0, memory_mb: int = 16000, free_memory_mb: int = 12000) -> NodeResources:
    return NodeResources(cpus=cpus, memory_mb=memory_mb, free_memory_mb=free_memory_mb, free_disk_mb=50000, load_average=0.1)


def make_hello(
    node_id: str,
    slots: Optional[Dict[JobType, int]] = None,
    labels: Optional[Dict[str, str]] = None,
    fingerprints: Optional[Dict[str, str]] = None,
    resources: Optional[NodeResources] = None,
    name: Optional[str] = None,
) -> Hello:
    slots = {JobType.SCENE_GENERATION: 2} if slots is None else slots
    return Hello(
        node_id=node_id,
        node_name=name or f"{node_id}-host",
        software_revision="755cbec",
        capabilities=[CapabilityOffer(job_type=job_type, slots=count) for job_type, count in slots.items()],
        labels=labels or {},
        resources=resources or make_resources(),
        fingerprints=fingerprints or {},
    )


def make_submission(
    job_type: JobType = JobType.SCENE_GENERATION,
    priority: int = 0,
    idempotency_key: Optional[str] = None,
    max_attempts: int = 3,
    requirements: Optional[JobRequirements] = None,
    payload: Optional[dict] = None,
) -> JobSubmission:
    return JobSubmission(
        job_type=job_type,
        payload=payload or {"scene": 1},
        requirements=requirements or JobRequirements(),
        priority=priority,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )
