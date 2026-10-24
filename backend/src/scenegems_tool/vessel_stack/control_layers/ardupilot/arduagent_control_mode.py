"""ArduAgent's control mode for the ASV software that drives an ArduPilot vessel.

MqttAgentClient and the scenario execution worker speak these modes: autonomous uploads
the trajectory as a mission to follow, external sends the vessel toward its last waypoint
and leaves the rest to whoever is on the MAVLink port.
"""

from typing import Dict

from scenegems_tool.vessel_stack.asv_software.mission_planner.mission_planner_specs import MISSION_PLANNER_MAVLINK_PORT
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId

# Adapters whose vessels ArduAgent drives: SITL, MAVProxy and ArduAgent per vessel, served by
# the scenario execution worker over WARA-PS MQTT. Any other adapter into ardupilot talks
# MAVLink to SITL itself (replay_mavlink_lockstep), so its vessel gets SITL only.
ARDUAGENT_ADAPTER_IDS = frozenset({REPLAY_ARDUAGENT_FOLLOWER.id, MISSION_PLANNER_MAVLINK_PORT.id})

_ARDUAGENT_CONTROL_MODES: Dict[AsvSoftwareId, str] = {
    AsvSoftwareId.REPLAY: "autonomous",
    AsvSoftwareId.MISSION_PLANNER: "external",
}


def arduagent_control_mode(asv_software: AsvSoftwareId) -> str:
    if asv_software not in _ARDUAGENT_CONTROL_MODES:
        raise ValueError(f"ArduAgent has no control mode for ASV software {asv_software.value}")
    return _ARDUAGENT_CONTROL_MODES[asv_software]
