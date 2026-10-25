"""Default registry: every layer, adapter and ruled-out connection of design section 3.3.

New ASV software, controllers or simulators are added by implementing their specs and
runtime and registering them here. Nothing else changes. Specs of Phase 2 adapters are
registered as planned so the resolver answers the whole availability matrix today.
"""

from functools import lru_cache
from typing import Mapping, Optional

from scenegems_tool.vessel_stack.asv_software.mission_planner.mission_planner_specs import MISSION_PLANNER_LAYER, MISSION_PLANNER_MAVLINK_PORT
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER, REPLAY_LAYER, REPLAY_MAVLINK_LOCKSTEP, REPLAY_STATE_FOLLOWER, mavlink_link_runtime
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_specs import USV_NAVIGATION_IN_PROCESS, USV_NAVIGATION_LAYER
from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec, SpecStatus, UnsupportedConnection
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUPILOT_CONTROL_LAYER
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.measured_capabilities import CapabilityMeasurement, load_capability_measurements
from scenegems_tool.vessel_stack.registry.resolver import StackResolver
from scenegems_tool.vessel_stack.simulation_layers.ardupilot_sim.ardupilot_sim_specs import ARDUPILOT_SIM_LAYER, SITL_INTERNAL_PHYSICS
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import ARDUPILOT_GAZEBO_PLUGIN, GAZEBO_LAYER
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_specs import KINEMATIC_COMMAND_INPUT, KINEMATIC_LAYER

_REPLAY = LayerRef.of(AsvSoftwareId.REPLAY)
_USV_NAVIGATION = LayerRef.of(AsvSoftwareId.USV_NAVIGATION)
_MISSION_PLANNER = LayerRef.of(AsvSoftwareId.MISSION_PLANNER)
_ARDUPILOT = LayerRef.of(ControlLayerId.ARDUPILOT)
_CUSTOM = LayerRef.of(ControlLayerId.CUSTOM)
_NONE = LayerRef.of(ControlLayerId.NONE)
_KINEMATIC = LayerRef.of(SimulationLayerId.KINEMATIC)
_GAZEBO = LayerRef.of(SimulationLayerId.GAZEBO)
_ARDUPILOT_SIM = LayerRef.of(SimulationLayerId.ARDUPILOT_SIM)

NONE_CONTROL_LAYER = LayerSpec(
    layer=_NONE,
    description="No separate controller: the simulation layer integrates control itself.",
)

# Planned for Phase 2 (design section 7).

CUSTOM_CONTROL_LAYER = LayerSpec(
    layer=_CUSTOM,
    description="Own controller for real-scale vessels, Gazebo only.",
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.HEADING_SPEED_CMD, Port.WAYPOINT_MISSION}),
    status=SpecStatus.PLANNED,
    planned_phase=2,
)
USV_NAVIGATION_MAVLINK_GUIDED = AdapterSpec(
    id="usv_navigation_mavlink_guided",
    source=_USV_NAVIGATION,
    target=_ARDUPILOT,
    description="Heading and speed of USV Navigation as MAVLink guided commands.",
    provides_ports=frozenset({Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
    status=SpecStatus.PLANNED,
    planned_phase=2,
)
CUSTOM_CONTROLLER_WAYPOINT_FOLLOWER = AdapterSpec(
    id="custom_controller_waypoint_follower",
    source=_REPLAY,
    target=_CUSTOM,
    description="Waypoint follower inside the custom controller.",
    provides_ports=frozenset({Port.WAYPOINT_MISSION}),
    status=SpecStatus.PLANNED,
    planned_phase=2,
)
CUSTOM_CONTROLLER_HEADING_SPEED_INPUT = AdapterSpec(
    id="custom_controller_heading_speed_input",
    source=_USV_NAVIGATION,
    target=_CUSTOM,
    description="heading_speed_cmd of USV Navigation into the custom controller.",
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    status=SpecStatus.PLANNED,
    planned_phase=2,
)
GZ_TRANSPORT_ACTUATOR = AdapterSpec(
    id="gz_transport_actuator",
    source=_CUSTOM,
    target=_GAZEBO,
    description="gz-transport actuator adapter: thrust commands on /model/<model>/joint/<joint>/cmd_thrust.",
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
    status=SpecStatus.PLANNED,
    planned_phase=2,
)

# The "no" rows of the availability matrix, with the reasons the design gives.
UNSUPPORTED_CONNECTIONS = (
    UnsupportedConnection(_MISSION_PLANNER, _NONE, "control layer none has no MAVLink endpoint (it only drives the kinematic sim, which has none)"),
    UnsupportedConnection(_MISSION_PLANNER, _CUSTOM, "the custom controller has no MAVLink"),
    UnsupportedConnection(_NONE, _GAZEBO, "Gazebo needs actuator commands"),
    UnsupportedConnection(_NONE, _ARDUPILOT_SIM, "ardupilot_sim is the physics inside ArduPilot SITL, so its control layer is ardupilot"),
    UnsupportedConnection(_CUSTOM, _ARDUPILOT_SIM, "SITL physics only accepts ArduPilot control"),
    UnsupportedConnection(_ARDUPILOT, _KINEMATIC, "the kinematic sim integrates control internally"),
    UnsupportedConnection(_CUSTOM, _KINEMATIC, "the kinematic sim integrates control internally"),
)


# Runtime loaders import on first use, so resolving a stack stays free of the code that runs it.
def _kinematic_simulation():
    from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation

    return KinematicSimulation


def _replay_follower():
    from scenegems_tool.vessel_stack.asv_software.replay.replay_follower import ReplayFollower

    return ReplayFollower


def _usv_navigation_participant():
    from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_participant import UsvNavigationParticipant

    return UsvNavigationParticipant


def _ardupilot_control_layer():
    from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_control_layer import ArduPilotControlLayer

    return ArduPilotControlLayer


def _gazebo_simulation_layer():
    from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_simulation_layer import GazeboSimulationLayer

    return GazeboSimulationLayer


def _ardupilot_sim_layer():
    from scenegems_tool.vessel_stack.simulation_layers.ardupilot_sim.ardupilot_sim_layer import ArduPilotSimLayer

    return ArduPilotSimLayer


def build_registry(measurements: Optional[Mapping[str, CapabilityMeasurement]] = None) -> AdapterRegistry:
    registry = AdapterRegistry(load_capability_measurements() if measurements is None else measurements)

    registry.register_layer(REPLAY_LAYER)
    registry.register_layer(USV_NAVIGATION_LAYER)
    registry.register_layer(MISSION_PLANNER_LAYER)
    registry.register_layer(ARDUPILOT_CONTROL_LAYER, runtime=_ardupilot_control_layer)
    registry.register_layer(CUSTOM_CONTROL_LAYER)
    registry.register_layer(NONE_CONTROL_LAYER)
    registry.register_layer(KINEMATIC_LAYER, runtime=_kinematic_simulation)
    registry.register_layer(GAZEBO_LAYER, runtime=_gazebo_simulation_layer)
    registry.register_layer(ARDUPILOT_SIM_LAYER, runtime=_ardupilot_sim_layer)

    registry.register_adapter(REPLAY_STATE_FOLLOWER, runtime=_replay_follower)
    registry.register_adapter(USV_NAVIGATION_IN_PROCESS, runtime=_usv_navigation_participant)
    registry.register_adapter(REPLAY_ARDUAGENT_FOLLOWER)
    registry.register_adapter(REPLAY_MAVLINK_LOCKSTEP, runtime=mavlink_link_runtime, default=True)
    registry.register_adapter(MISSION_PLANNER_MAVLINK_PORT)
    registry.register_adapter(KINEMATIC_COMMAND_INPUT)
    registry.register_adapter(SITL_INTERNAL_PHYSICS)
    registry.register_adapter(ARDUPILOT_GAZEBO_PLUGIN)
    for planned in (USV_NAVIGATION_MAVLINK_GUIDED, CUSTOM_CONTROLLER_WAYPOINT_FOLLOWER, CUSTOM_CONTROLLER_HEADING_SPEED_INPUT, GZ_TRANSPORT_ACTUATOR):
        registry.register_adapter(planned)

    for connection in UNSUPPORTED_CONNECTIONS:
        registry.declare_unsupported(connection)
    registry.check_measurements()
    return registry


@lru_cache(maxsize=1)
def default_registry() -> AdapterRegistry:
    return build_registry()


def default_resolver() -> StackResolver:
    return StackResolver(default_registry())
