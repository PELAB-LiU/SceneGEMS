"""ardupilot_sim simulation layer adapter: SITL's internal physics, so no simulator container.

The Gazebo world and vessel models are still written, unused, so the generated files stay
byte-identical to the stack before the adapter framework. Dropping them is a later cleanup.
"""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig
from scenegems_tool.vessel_stack.simulation_layers.ardupilot_sim.ardupilot_sim_specs import ARDUPILOT_SIM_LAYER
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_simulation_layer import GazeboWorldFiles


class ArduPilotSimLayer:
    spec = ARDUPILOT_SIM_LAYER

    def __init__(self):
        self._unused_gazebo_files = GazeboWorldFiles()

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        self._unused_gazebo_files.add_vessel_model(artifacts, request, vessel_config, vessel, state)

    def finish(self, artifacts: DockerStackArtifacts, request: DockerStackRequest) -> None:
        self._unused_gazebo_files.add_world(artifacts, request)
