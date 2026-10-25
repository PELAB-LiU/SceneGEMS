"""Gazebo simulation layer adapter: the generated ocean world, one SDF model per vessel and the Gazebo service."""

from typing import List, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import GAZEBO_LAYER, wave_forces_enabled
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.gazebo_service_generator import generate_gazebo_service
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import generate_vessel_model
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.world_generator import generate_world


class GazeboWorldFiles:
    """Writes one SDF model per vessel and the world that includes them at their start poses."""

    def __init__(self):
        self._vessel_includes: List[Tuple[str, ActorState]] = []

    def add_vessel_model(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        agent_name = vessel_config.require_connection().agent_name
        if vessel_config.gazebo_vessel_model is not None:
            vessel_model = vessel_config.gazebo_vessel_model
        else:
            vessel_model = generate_vessel_model(vessel, agent_name, vessel_config.stack.control_layer, request.simulation.environment)
        vessel_model_filename = f"{agent_name}_model.sdf"
        artifacts.pending_writes.append((f"{request.gen_folder}/{vessel_model_filename}", vessel_model))
        self._vessel_includes.append((f"{request.mounted_gen_folder}/{vessel_model_filename}", state))

    def add_world(self, artifacts: DockerStackArtifacts, request: DockerStackRequest) -> str:
        os_state = request.trajectories.initial_scene.os_state
        lat_long = request.reference_geofence.to_lat_long(os_state.p)
        environment = request.simulation.environment
        world_model = generate_world(
            lat_long, self._vessel_includes, environment.wind_vector, environment.wave, request.simulation.speedup, headless=request.headless, wave_forces=wave_forces_enabled(environment)
        )
        world_file = f"{request.gen_folder}/ocean_world.sdf"
        artifacts.pending_writes.append((world_file, world_model))
        return world_file


class GazeboSimulationLayer:
    spec = GAZEBO_LAYER

    def __init__(self):
        self._world_files = GazeboWorldFiles()

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        self._world_files.add_vessel_model(artifacts, request, vessel_config, vessel, state)

    def finish(self, artifacts: DockerStackArtifacts, request: DockerStackRequest) -> None:
        world_file = self._world_files.add_world(artifacts, request)
        # Gazebo waits for every agent name, real vessels included, exactly as before the
        # adapter framework, although a real vessel has no service (see the Phase 1 notes).
        agent_names = [vessel_config.require_connection().agent_name for vessel_config in request.simulation.vessels.values()]
        artifacts.services.update(generate_gazebo_service(world_file, agent_names, headless=request.headless, display="host.docker.internal:0.0", verbose=4))
