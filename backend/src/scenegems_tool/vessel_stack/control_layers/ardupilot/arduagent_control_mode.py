"""ArduAgent's control mode for the ASV software that drives an ArduPilot vessel.

MqttAgentClient and the scenario execution worker speak these modes: autonomous uploads
the trajectory as a mission to follow, external sends the vessel toward its last waypoint
and leaves the rest to whoever is on the MAVLink port, and on_board sends nothing: the
vessel's own software steers and ArduAgent only reports where it is.
"""

from typing import Dict

from scenegems_tool.vessel_stack.asv_software.mission_planner.mission_planner_specs import MISSION_PLANNER_MAVLINK_PORT
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId
from scenegems_tool.vessel_stack.control_layers.real_vessel.real_vessel_specs import (
    MISSION_PLANNER_ARDUAGENT_REAL_VESSEL,
    ON_BOARD_ARDUAGENT_REAL_VESSEL,
    REPLAY_ARDUAGENT_REAL_VESSEL,
)

# Adapters whose vessels ArduAgent drives, served by the scenario execution worker over MQTT:
# a simulated vessel gets SITL, MAVProxy and ArduAgent, a real vessel brings its own ArduAgent.
# Any other adapter into ardupilot talks MAVLink to SITL itself (replay_mavlink_lockstep,
# usv_navigation_mavlink_lockstep), so its vessel gets SITL only.
ARDUAGENT_ADAPTER_IDS = frozenset(
    {
        REPLAY_ARDUAGENT_FOLLOWER.id,
        MISSION_PLANNER_MAVLINK_PORT.id,
        REPLAY_ARDUAGENT_REAL_VESSEL.id,
        MISSION_PLANNER_ARDUAGENT_REAL_VESSEL.id,
        ON_BOARD_ARDUAGENT_REAL_VESSEL.id,
    }
)

ON_BOARD_CONTROL_MODE = "on_board"

_ARDUAGENT_CONTROL_MODES: Dict[AsvSoftwareId, str] = {
    AsvSoftwareId.REPLAY: "autonomous",
    AsvSoftwareId.MISSION_PLANNER: "external",
    AsvSoftwareId.ON_BOARD: ON_BOARD_CONTROL_MODE,
}


def arduagent_control_mode(asv_software: AsvSoftwareId) -> str:
    if asv_software not in _ARDUAGENT_CONTROL_MODES:
        raise ValueError(f"ArduAgent has no control mode for ASV software {asv_software.value}")
    return _ARDUAGENT_CONTROL_MODES[asv_software]
