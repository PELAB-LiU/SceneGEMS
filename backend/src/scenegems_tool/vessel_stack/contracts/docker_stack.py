"""Contract for adapters that contribute files and services to a per-job Docker Compose stack.

The simulation instance builder (vessel_stack/simulation_docker_stack.py) resolves the
instance through the registry, then asks the simulation layer and each vessel's control
layer for their part. Services appear in the compose file in the order they are added.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Protocol, Tuple, runtime_checkable

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig, VesselConfig


@dataclass(frozen=True)
class DockerStackRequest:
    simulation: SimulationInstanceConfig
    trajectories: Trajectories
    mqtt_connection: MQttConnectionInfo
    reference_geofence: Geofence
    headless: bool


@dataclass
class DockerStackArtifacts:
    pending_writes: List[Tuple[str, str]] = field(default_factory=list)  # (path in the gen folder, content)
    services: Dict[str, dict] = field(default_factory=dict)


@runtime_checkable
class DockerSimulationLayer(Protocol):
    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None: ...

    def finish(self, artifacts: DockerStackArtifacts, request: DockerStackRequest) -> None:
        """Add the instance-wide part (world, simulator service) after every vessel."""


@runtime_checkable
class DockerControlLayer(Protocol):
    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None: ...
