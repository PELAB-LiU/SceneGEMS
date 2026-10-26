"""Specs of the custom control layer and of the replay route into it.

The custom controller is SceneGEMS's own heading and speed autopilot for a twin
differential-thrust hull (twin_thrust_autopilot.py), for Gazebo only. It runs in process in the
runner, next to the ASV software, and drives the hull through the gz-transport actuator
adapter (simulation_layers/gazebo/gz_transport_actuator.py), which steps the paused world, so
controller and physics share one clock.
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, LayerRef

CUSTOM_CONTROL_LAYER = LayerSpec(
    layer=LayerRef.of(ControlLayerId.CUSTOM),
    description="Own heading and speed autopilot for twin differential thrust: a surge loop sets the common thrust and a yaw loop the differential thrust, with gains from the generated hull model. Gazebo only.",
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.HEADING_SPEED_CMD, Port.WAYPOINT_MISSION}),
)

CUSTOM_CONTROLLER_WAYPOINT_FOLLOWER = AdapterSpec(
    id="custom_controller_waypoint_follower",
    source=LayerRef.of(AsvSoftwareId.REPLAY),
    target=LayerRef.of(ControlLayerId.CUSTOM),
    description="Line-of-sight waypoint follower inside the custom controller (los_waypoint_follower.py): the replayed trajectory is the waypoint mission, steered by its geometry and paced by its timing.",
    provides_ports=frozenset({Port.WAYPOINT_MISSION}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)


def los_waypoint_follower_runtime():
    """Runtime of CUSTOM_CONTROLLER_WAYPOINT_FOLLOWER, imported on first use."""
    from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower

    return LosWaypointFollower
