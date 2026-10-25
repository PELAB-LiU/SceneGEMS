"""The scene generation pool: the scenario generation MQTT service with its generation workers."""

from typing import Optional

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.scene_generation.scenario_generation_types import MAX_SCENE_GENERATION_WORKERS
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
from utils.file_system_utils import SCENARIO_GENERATION_GEN_FOLDER

_SERVICE_KEY = "scenario_generation"
WORKBENCH_NAMES = PoolNames(
    compose_project="scenegems-scenario-generation-subsystem",
    service_key=_SERVICE_KEY,
    container_name=_SERVICE_KEY,
    network_key="scenario_generation_net",
    network_name="scenario_generation_net",
    folder=SCENARIO_GENERATION_GEN_FOLDER,
    topic_prefix="",
    scoped=False,
)


class SceneGenerationPool(PooledService):
    subsystem = Subsystem.SCENE_GENERATION

    @classmethod
    def for_workbench(cls, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence) -> "SceneGenerationPool":
        """The single-machine pool: fixed names, no topic prefix, the service's default worker count."""
        return cls(WORKBENCH_NAMES, mqtt_connection, reference_geofence, cpus=MAX_SCENE_GENERATION_WORKERS + SERVICE_CPUS)

    @classmethod
    def for_scope(cls, scope: InstanceScope, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, workers: int, broker_network: Optional[str] = None) -> "SceneGenerationPool":
        return cls(PoolNames.for_scope(scope, _SERVICE_KEY), mqtt_connection, reference_geofence, cpus=workers + SERVICE_CPUS, workers=workers, broker_network=broker_network)
