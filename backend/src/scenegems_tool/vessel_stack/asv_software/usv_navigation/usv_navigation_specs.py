"""Specs of the USV Navigation ASV software and its adapters.

USV Navigation is colav_automaton (github.com/michaelstolberger27/usv-navigation, MIT),
pinned to COLAV_AUTOMATON_COMMIT in backend/pyproject.toml and in the scenario execution
image. Every route runs the same in-process participant (usv_navigation_participant.py),
stepped by the simulation clock; the adapters differ in what takes its heading and speed:
the kinematic layer itself, or the custom controller's autopilot on Gazebo (WP5c).
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
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
