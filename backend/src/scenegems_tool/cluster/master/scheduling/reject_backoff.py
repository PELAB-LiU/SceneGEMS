"""What the scheduler does with a node that keeps rejecting the same job.

A rejected offer returns the job to the queue without using an attempt, so draining or a
busy node never burns retries. Without a rule, the claim would hand the same job straight
back to the node that refused it, forever. So after a reject the job is held back from that
node, 30 s after the first reject and twice as long after each further one, up to 10
minutes. Other nodes get the job meanwhile, and the node keeps getting other jobs; when no
other node can run the job, the rejecting node is asked again after the hold.

The holds live in the master's memory: a master restart clears them, which only means one
more reject. They are dropped when the job ends.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from scenegems_tool.persistence.clock import Clock, utc_now


@dataclass
class _Hold:
    rejects: int
    until: datetime


@dataclass
class RejectBackoff:
    initial_hold_s: float = 30.0
    max_hold_s: float = 600.0
    clock: Clock = utc_now
    _holds: Dict[Tuple[str, str], _Hold] = field(default_factory=dict)

    def rejected(self, node_id: str, job_id: str) -> datetime:
        """Records a reject; returns until when the job is held back from the node."""
        now = self.clock()
        self._prune(now)
        hold = self._holds.get((node_id, job_id))
        rejects = 1 if hold is None else hold.rejects + 1
        until = now + timedelta(seconds=self.hold_s(rejects))
        self._holds[(node_id, job_id)] = _Hold(rejects, until)
        return until

    def hold_s(self, rejects: int) -> float:
        return min(self.initial_hold_s * 2 ** (rejects - 1), self.max_hold_s)

    def held_jobs(self, node_id: str) -> List[str]:
        """Jobs not to offer to the node now."""
        now = self.clock()
        return sorted(job_id for (holder, job_id), hold in self._holds.items() if holder == node_id and hold.until > now)

    def job_ended(self, job_id: str) -> None:
        for key in [key for key in self._holds if key[1] == job_id]:
            del self._holds[key]

    def _prune(self, now: datetime) -> None:
        # A node that has not rejected the job for a full maximum hold starts again at the first hold
        horizon = now - timedelta(seconds=self.max_hold_s)
        for key in [key for key, hold in self._holds.items() if hold.until < horizon]:
            del self._holds[key]
