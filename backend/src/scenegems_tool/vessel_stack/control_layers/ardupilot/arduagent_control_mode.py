"""ArduAgent's control mode for the ASV software that drives an ArduPilot vessel.

MqttAgentClient and the scenario execution worker speak these modes: autonomous uploads
the trajectory as a mission to follow, external sends the vessel toward its last waypoint
and leaves the rest to whoever is on the MAVLink port.
"""

from typing import Dict

from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId

_ARDUAGENT_CONTROL_MODES: Dict[AsvSoftwareId, str] = {
    AsvSoftwareId.REPLAY: "autonomous",
    AsvSoftwareId.MISSION_PLANNER: "external",
}


def arduagent_control_mode(asv_software: AsvSoftwareId) -> str:
    if asv_software not in _ARDUAGENT_CONTROL_MODES:
        raise ValueError(f"ArduAgent has no control mode for ASV software {asv_software.value}")
    return _ARDUAGENT_CONTROL_MODES[asv_software]
