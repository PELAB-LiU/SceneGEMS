"""Custom control layer adapter for Docker stacks: the controller has no container of its own.

The autopilot runs in process in the runner (simulation_layers/gazebo/gz_lockstep_runner.py), so
a vessel on the custom control layer adds nothing to the compose stack. The Gazebo layer gives
its model the variant without ArduPilotPlugin and starts the gz-transport actuator.
"""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig
from scenegems_tool.vessel_stack.control_layers.custom.custom_controller_specs import CUSTOM_CONTROL_LAYER


class CustomControlLayer:
    spec = CUSTOM_CONTROL_LAYER

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        del artifacts, request, vessel, state  # the controller runs in the runner process
        if vessel_config.stack.simulation_layer != SimulationLayerId.GAZEBO:
            raise ValueError(f"The custom control layer drives Gazebo only, not {vessel_config.stack.simulation_layer.value}")
