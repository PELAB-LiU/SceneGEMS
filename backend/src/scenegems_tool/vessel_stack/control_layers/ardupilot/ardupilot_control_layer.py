"""ArduPilot control layer adapter: SITL with its parameter file, MAVProxy and ArduAgent per vessel."""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.messaging.mqtt_agent_client import MqttAgentClient
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardu_param_generator import generate_ardu_params
from scenegems_tool.vessel_stack.control_layers.ardupilot.arduagent_control_mode import arduagent_control_mode
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUPILOT_CONTROL_LAYER
from scenegems_tool.vessel_stack.control_layers.ardupilot.vessel_service_generator import generate_vessel_service
from utils.file_system_utils import SIMULATION_GEN_FOLDER


class ArduPilotControlLayer:
    spec = ARDUPILOT_CONTROL_LAYER

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        connection = vessel_config.require_connection()
        # The service generator reads the agent's name, broker and home pose from a client
        # object; it is never connected.
        agent_stub = MqttAgentClient(
            vessel=vessel,
            mqtt_connection=request.mqtt_connection,
            topic=connection.topic,
            control_mode=arduagent_control_mode(vessel_config.stack.asv_software),
            agent_name=connection.agent_name,
            reference_geofence=request.reference_geofence,
            initial_state=state,
            parent_service_name="scenario_execution_service",
            mission_waypoints=[],
        )

        environment = request.simulation.environment
        ardu_params = generate_ardu_params(vessel, request.trajectories.get_max_speed(vessel), environment.wind_vector, environment.wave)
        params_file = f"{SIMULATION_GEN_FOLDER}/params-{connection.agent_name}.params"
        lines = []
        for key, value in ardu_params.items():
            if value is not None:
                lines.append(f"{key}\t{value}\n")
        artifacts.pending_writes.append((params_file, "".join(lines)))

        # sitl_internal_physics homes SITL at the start pose; ardupilot_gazebo_plugin runs SITL's JSON backend against Gazebo.
        sitl_internal_physics = vessel_config.stack.simulation_layer == SimulationLayerId.ARDUPILOT_SIM
        artifacts.services.update(generate_vessel_service(agent_stub, connection.port, params_file, request.simulation.speedup, sitl_internal_physics))
