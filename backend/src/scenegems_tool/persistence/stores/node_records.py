"""Detached snapshots of a node as the stores return them."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.node_description import NodeResources
from scenegems_tool.persistence.schema import NodeRow, NodeStatus


@dataclass(frozen=True)
class CapabilityUsage:
    slots: int
    slots_in_use: int  # as the node last reported it


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    name: str
    status: NodeStatus
    labels: Dict[str, str]
    software_revision: str
    resources: NodeResources
    capabilities: Dict[JobType, CapabilityUsage]
    fingerprints: Dict[str, str]  # image name to build fingerprint
    registered_at: datetime
    last_seen_at: datetime

    @classmethod
    def from_row(cls, row: NodeRow) -> "NodeRecord":
        return cls(
            node_id=row.id,
            name=row.name,
            status=row.status,
            labels=dict(row.labels),
            software_revision=row.software_revision,
            resources=NodeResources(cpus=row.cpus, memory_mb=row.memory_mb, free_memory_mb=row.free_memory_mb, free_disk_mb=row.free_disk_mb, load_average=row.load_average),
            capabilities={capability.job_type: CapabilityUsage(slots=capability.slots, slots_in_use=capability.slots_in_use) for capability in row.capabilities},
            fingerprints={fingerprint.image: fingerprint.fingerprint for fingerprint in row.fingerprints},
            registered_at=row.registered_at,
            last_seen_at=row.last_seen_at,
        )
