"""Whether a connected node may receive offers now, and why not.

The job store's claim matches each job against the node's slots, labels, fingerprints and
its last reported free memory and CPUs. The checks here are about the node as a whole:
it must be online, up to date, and not short of memory or overloaded. Free memory and load
come from the last heartbeat, so jobs offered since then are not counted yet; the guard
keeps a margin for them, and a node that cannot take a job rejects it (no attempt used).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from scenegems_tool.persistence.schema import NodeStatus
from scenegems_tool.persistence.stores import NodeRecord


@dataclass(frozen=True)
class ResourceGuard:
    min_free_memory_mb: int = 512  # below this a node gets no new offers, whatever a job's own minimum says
    max_load_average: float = 1.5  # one-minute load per CPU above which a node gets no new offers


class Ineligibility(str, Enum):
    NOT_ONLINE = "not online"  # draining or offline
    FINGERPRINTS_UNKNOWN = "the master's expected fingerprints are not available"
    OUT_OF_DATE = "out of date"
    LOW_MEMORY = "low on free memory"
    OVERLOADED = "overloaded"


def ineligibility(node: NodeRecord, out_of_date: bool, fingerprints_known: bool, guard: ResourceGuard) -> Optional[Ineligibility]:
    """None when the node may receive offers, else the first reason it may not."""
    if node.status != NodeStatus.ONLINE:
        return Ineligibility.NOT_ONLINE
    if not fingerprints_known:
        return Ineligibility.FINGERPRINTS_UNKNOWN
    if out_of_date:
        return Ineligibility.OUT_OF_DATE
    if node.resources.free_memory_mb < guard.min_free_memory_mb:
        return Ineligibility.LOW_MEMORY
    if node.resources.load_average > guard.max_load_average:
        return Ineligibility.OVERLOADED
    return None
