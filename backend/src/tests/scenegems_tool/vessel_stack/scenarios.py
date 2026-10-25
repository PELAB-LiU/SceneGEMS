"""Scenes and trajectories shared by the vessel stack tests: the four controlled encounters and stack instances."""

import math
from typing import Dict, Sequence

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import (
    AgentConnection,
    EnvironmentConfig,
    SimulationInstanceConfig,
    VesselConfig,
    VesselStackConfig,
)

SPEED = 8.0
GEOFENCE = Geofence(57.757128, 16.673189, 5000)

# The own ship starts at the origin heading east (x east, y north, heading counterclockwise from east).
ENCOUNTER_TARGETS: Dict[str, ActorState] = {
    "head_on": ActorState(6000.0, 0.0, SPEED, math.pi),
    "crossing_from_starboard": ActorState(3600.0, -3600.0, SPEED, math.pi / 2),
    "crossing_from_port": ActorState(3600.0, 3600.0, SPEED, -math.pi / 2),
    "overtaking": ActorState(1500.0, 0.0, 3.0, 0.0),
}


def make_vessel(vessel_id: int, is_os: bool, length: float = 30.0, max_speed: float = 20.57778, max_angular_speed: float = 0.05, max_acceleration: float = 0.4) -> ConcreteVessel:
    vessel = ConcreteActor.from_dict(
        {
            "id": vessel_id,
            "type": "OSPassengerShip" if is_os else "PassengerShip",
            "length": length,
            "breadth": length / 3,
            "safety_radius": 4 * length,
            "is_vessel": True,
            "_is_os": is_os,
            "_max_speed": max_speed,
            "_max_angular_speed": max_angular_speed,
            "_max_acceleration": max_acceleration,
        }
    )
    assert isinstance(vessel, ConcreteVessel)
    return vessel


def encounter_scene(name: str) -> ConcreteScene:
    return ConcreteScene({make_vessel(0, True): ActorState(0.0, 0.0, SPEED, 0.0), make_vessel(1, False): ENCOUNTER_TARGETS[name]})


def encounter_trajectories(name: str, timespan: int = 300, time_step: int = 1) -> Trajectories:
    """Straight-line trajectories of one encounter, as the scenario generator's stand-in."""
    return TrajectoryBuilder.default_trajectory_from_scene(encounter_scene(name), time_step, timespan)


def straight_trajectories(length: float = 30.0, speed: float = SPEED, timespan: int = 60) -> Trajectories:
    """One own ship heading east at constant speed."""
    scene = ConcreteScene({make_vessel(0, True, length=length): ActorState(0.0, 0.0, speed, 0.0)})
    return TrajectoryBuilder.default_trajectory_from_scene(scene, 1, timespan)


def mqtt_connection() -> MQttConnectionInfo:
    return MQttConnectionInfo(user="user", password="password", agent_broker="broker", client_broker="broker", port=1883, tls_connection=False, allow_certificates=False)


def stack_instance(
    simulation_layer: SimulationLayerId,
    vessel_ids: Sequence[int],
    asv_software: AsvSoftwareId = AsvSoftwareId.REPLAY,
    control_layer: ControlLayerId = ControlLayerId.ARDUPILOT,
    *,
    environment: EnvironmentConfig | None = None,
    speedup: int = 1,
    adapter_ids: Sequence[str] = (),
) -> SimulationInstanceConfig:
    """An instance with the same triple on every vessel, each with an agent connection."""
    stack = VesselStackConfig(asv_software=asv_software, control_layer=control_layer, simulation_layer=simulation_layer)
    return SimulationInstanceConfig(
        simulation_layer=simulation_layer,
        environment=environment or EnvironmentConfig.calm(),
        speedup=speedup,
        vessels={
            str(vessel_id): VesselConfig(
                agent_id=str(vessel_id),
                stack=stack,
                connection=AgentConnection(agent_name=f"agent_{vessel_id}", topic=f"waraps/unit/surface/agent_{vessel_id}", port=14550 + 10 * vessel_id),
                adapter_ids=tuple(adapter_ids),
            )
            for vessel_id in vessel_ids
        },
    )


def wind_environment(east: float = 0.0, north: float = 5.0) -> EnvironmentConfig:
    environment = EnvironmentConfig.calm()
    environment.wind_vector = np.array([east, north, 0.0])
    return environment
