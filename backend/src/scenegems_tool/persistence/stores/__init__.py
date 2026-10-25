"""Transactional primitives the master's node registry, scheduler and lease manager call.

Every store method runs in its own transaction and returns detached snapshots (records),
never ORM rows. Which node gets which job, and when, is the scheduler's policy (P3.3); the
stores only guarantee that each step is atomic and safe under concurrency.

    node_records.py   snapshots of a node and its capabilities
    node_store.py     register from Hello, heartbeats, status, silent nodes offline
    job_records.py    snapshots of a job, a lease and the outcome of each primitive
    job_lifecycle.py  pure rules: when a lease is current, retries, result idempotency
    job_claim.py      what a node can take, and the SKIP LOCKED query that finds it
    job_event_log.py  the append-only history of each job
    job_store.py      submit, claim, accept, renew, release, result, cancel, expire
"""

from scenegems_tool.persistence.stores.job_records import CancelOutcome, ExpiredLease, JobEventRecord, JobRecord, Lease, ResultReport, ResultStatus, SubmitOutcome
from scenegems_tool.persistence.stores.job_store import IdempotencyKeyMismatch, JobStore, UnknownJob, UnknownNode
from scenegems_tool.persistence.stores.node_records import CapabilityUsage, NodeRecord
from scenegems_tool.persistence.stores.node_store import NodeStore

__all__ = [
    "CancelOutcome",
    "CapabilityUsage",
    "ExpiredLease",
    "IdempotencyKeyMismatch",
    "JobEventRecord",
    "JobRecord",
    "JobStore",
    "Lease",
    "NodeRecord",
    "NodeStore",
    "ResultReport",
    "ResultStatus",
    "SubmitOutcome",
    "UnknownJob",
    "UnknownNode",
]
