"""What running jobs report on the way: the latest status and the most recent log lines.

Kept in the master's memory for the job queries, bounded per job and in the number of
jobs. Results and state changes are in the job store; this is only the live view.
"""

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, List, Optional

from scenegems_tool.cluster.protocol.messages import JobStatus, LogLine, LogLines
from scenegems_tool.persistence.clock import Clock, utc_now

MAX_LINES_PER_JOB = 200
MAX_JOBS = 1000


@dataclass
class JobProgress:
    lease_id: str
    progress: Optional[float]
    message: str
    at: datetime


@dataclass
class _Activity:
    status: Optional[JobProgress] = None
    lines: Deque[LogLine] = field(default_factory=lambda: deque(maxlen=MAX_LINES_PER_JOB))


class JobActivity:
    def __init__(self, clock: Clock = utc_now):
        self._clock = clock
        self._jobs: "OrderedDict[str, _Activity]" = OrderedDict()

    def status(self, status: JobStatus) -> None:
        self._entry(status.job_id).status = JobProgress(lease_id=status.lease_id, progress=status.progress, message=status.message, at=self._clock())

    def logs(self, logs: LogLines) -> None:
        self._entry(logs.job_id).lines.extend(logs.lines)

    def progress(self, job_id: str) -> Optional[JobProgress]:
        activity = self._jobs.get(job_id)
        return None if activity is None else activity.status

    def lines(self, job_id: str) -> List[LogLine]:
        activity = self._jobs.get(job_id)
        return [] if activity is None else list(activity.lines)

    def _entry(self, job_id: str) -> _Activity:
        activity = self._jobs.pop(job_id, None) or _Activity()
        self._jobs[job_id] = activity
        while len(self._jobs) > MAX_JOBS:
            self._jobs.popitem(last=False)
        return activity
