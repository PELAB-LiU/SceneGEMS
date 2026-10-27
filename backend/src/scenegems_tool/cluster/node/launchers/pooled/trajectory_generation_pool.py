"""The trajectory generation pool: the trajectory generation MQTT service with its RRT workers."""

from typing import Optional

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import MAX_TRAJECTORY_GENERATION_WORKERS
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
from utils.file_system_utils import TRAJECTORY_GENERATION_GEN_FOLDER

_SERVICE_KEY = "trajectory_generation"
WORKBENCH_NAMES = PoolNames(
    compose_project="scenegems-trajectory-generation-subsystem",
    service_key=_SERVICE_KEY,
    container_name=_SERVICE_KEY,
    network_key="trajectory_generation_net",
    network_name="trajectory_generation_net",
    folder=TRAJECTORY_GENERATION_GEN_FOLDER,
    topic_prefix="",
    scoped=False,
)


class TrajectoryGenerationPool(PooledService):
    subsystem = Subsystem.TRAJECTORY_GENERATION

    @classmethod
    def for_workbench(cls, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence) -> "TrajectoryGenerationPool":
        """The single-machine pool: one worker, where a new request supersedes the running one."""
        return cls(WORKBENCH_NAMES, mqtt_connection, reference_geofence, cpus=MAX_TRAJECTORY_GENERATION_WORKERS + SERVICE_CPUS)

    @classmethod
    def for_scope(
        cls,
        scope: InstanceScope,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        workers: int,
        broker_network: Optional[str] = None,
    ) -> "TrajectoryGenerationPool":
        return cls(
            PoolNames.for_scope(scope, _SERVICE_KEY),
            mqtt_connection,
            reference_geofence,
            cpus=workers + SERVICE_CPUS,
            workers=workers,
            broker_network=broker_network,
        )
