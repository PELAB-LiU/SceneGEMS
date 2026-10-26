"""Specs of the USV Navigation ASV software and its adapters.

USV Navigation is colav_automaton (github.com/michaelstolberger27/usv-navigation, MIT),
pinned to COLAV_AUTOMATON_COMMIT in backend/pyproject.toml and in the scenario execution
image. Every route runs the same in-process participant (usv_navigation_participant.py),
stepped by the simulation clock; the adapters differ in what takes its heading and speed:
the kinematic layer itself, the custom controller's autopilot on Gazebo (WP5c), or ArduPilot
as GUIDED targets over the lockstep MAVLink link (WP5b).
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, LayerRef

COLAV_AUTOMATON_COMMIT = "54866f24a04987334057ae5c5896dfc3ee8ca058"

USV_NAVIGATION_LAYER = LayerSpec(
    layer=LayerRef.of(AsvSoftwareId.USV_NAVIGATION),
    description="USV Navigation (colav_automaton.SyncColavRuntime) in process, stepped by the simulation clock.",
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

USV_NAVIGATION_IN_PROCESS = AdapterSpec(
    id="usv_navigation_in_process",
    source=LayerRef.of(AsvSoftwareId.USV_NAVIGATION),
    target=LayerRef.of(ControlLayerId.NONE),
    description="In-process USV Navigation adapter: SyncColavRuntime.step_external every step, output as heading_speed_cmd.",
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

CUSTOM_CONTROLLER_HEADING_SPEED_INPUT = AdapterSpec(
    id="custom_controller_heading_speed_input",
    source=LayerRef.of(AsvSoftwareId.USV_NAVIGATION),
    target=LayerRef.of(ControlLayerId.CUSTOM),
    description="USV Navigation stepped in the runner next to the custom controller: its heading and speed commands are the twin-thrust autopilot's setpoints (gz_lockstep_runner.py).",
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

USV_NAVIGATION_MAVLINK_LOCKSTEP = AdapterSpec(
    id="usv_navigation_mavlink_lockstep",
    source=LayerRef.of(AsvSoftwareId.USV_NAVIGATION),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description="In-process USV Navigation driving ArduPilot over MAVLink: its heading and speed as GUIDED targets on simulation-time step boundaries read from SITL, as replay_mavlink_lockstep does for the replay follower. No MAVProxy or ArduAgent.",
    # The same link as replay_mavlink_lockstep: SITL is not held while a command is in flight.
    capabilities=Capabilities(lockstep=True, repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.HEADING_SPEED_CMD, Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)


def usv_navigation_participant_runtime():
    """The participant every USV Navigation route runs, imported on first use so resolving needs no colav_automaton."""
    from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_participant import UsvNavigationParticipant

    return UsvNavigationParticipant
