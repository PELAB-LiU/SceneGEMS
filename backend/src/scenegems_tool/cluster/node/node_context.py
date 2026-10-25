"""What a job runner needs from its node: identity, slots, broker access, the shared pools and artifact transport.

The node daemon builds one NodeContext from its configuration and pairing response
(daemon/node_runtime.py) and calls `shutdown` when it stops. Tests build one directly.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from scenegems_tool.cluster.node.artifacts.node_artifacts import ArtifactTransport
from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.ca_certificate_mount import CaCertificateMount
from scenegems_tool.cluster.node.launchers.pooled.service_pools import ServicePools
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence

# The job type whose slots size each pooled subsystem's worker pool.
_POOL_JOB_TYPES = {
    Subsystem.SCENE_GENERATION: JobType.SCENE_GENERATION,
    Subsystem.TRAJECTORY_GENERATION: JobType.TRAJECTORY_GENERATION,
}


@dataclass
class NodeContext:
    master_id: str
    node_id: str
    # The broker as this process dials it (client_broker) and as containers dial it
    # (agent_broker). Its topic prefix is unused: every instance gets its own.
    mqtt_connection: MQttConnectionInfo
    reference_geofence: Geofence  # frame of the pooled services; simulation payloads carry their own
    slots: Dict[JobType, int] = field(default_factory=dict)
    broker_network: Optional[str] = None  # Docker network the broker is reachable on; SCENEGEMS_DOCKER_NETWORK when None
    ca_certificate_mount: Optional[CaCertificateMount] = None  # how containers get the broker's CA file; mqtt_connection's CA path is this process's
    artifacts: Optional[ArtifactTransport] = None  # downloads referenced inputs and uploads results; None keeps results inline
    pools: ServicePools = field(init=False)

    def __post_init__(self) -> None:
        self.pools = ServicePools(self.master_id, self.node_id, self.mqtt_connection, self.reference_geofence, self.pool_workers, self.broker_network, self.ca_certificate_mount)

    def pool_workers(self, subsystem: Subsystem) -> int:
        return max(1, self.slots.get(_POOL_JOB_TYPES[subsystem], 1))

    def job_scope(self, job: JobSpec) -> InstanceScope:
        """The scope of a job's per-job stack; each attempt gets its own, so a retry never meets a leftover."""
        return InstanceScope.per_job(self.master_id, self.node_id, f"{job.job_id}-{job.attempt}")

    def shutdown(self) -> None:
        self.pools.shutdown()
