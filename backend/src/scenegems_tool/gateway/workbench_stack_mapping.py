"""Maps the workbench wire vocabulary to vessel stack triples and back.

The browser sends one simulatorType for the instance and, per agent, its ASV software
(asvSoftware) and control layer (controlLayer). Older clients send only a controlMode per
agent, which names the ASV software (autonomous is replay, external is mission_planner); the
control layer then defaults to the one the simulator's ArduPilot-era stacks used (none on the
kinematic layer, ardupilot otherwise).

Adapters: an instance with a real vessel runs through ArduAgent, which reaches real and
simulated vessels alike over WARA-PS MQTT, so its replay and Mission Planner vessels select
the ArduAgent adapters. An instance of simulated vessels uses the registry's defaults (the
lockstep MAVLink link, the custom controller's adapters, the Mission Planner ground station
port), which the scenario execution worker drives with the lockstep runners.

The labels sent back (simulation_models, the scenario execution worker body) are the ones the
browser offers, so the round trip is unchanged.
"""

from typing import Dict, Optional, Tuple

from scenegems_tool.vessel_stack.asv_software.mission_planner.mission_planner_specs import MISSION_PLANNER_MAVLINK_PORT
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig

_SIMULATOR_TYPE_LABELS: Dict[SimulationLayerId, str] = {
    SimulationLayerId.GAZEBO: "Gazebo",
    SimulationLayerId.ARDUPILOT_SIM: "ArduPilot Sim",
    SimulationLayerId.KINEMATIC: "Kinematic",
}
_CONTROL_MODE_LABELS: Dict[AsvSoftwareId, str] = {
    AsvSoftwareId.REPLAY: "autonomous",
    AsvSoftwareId.MISSION_PLANNER: "external",
}
# The adapters ArduAgent drives a vessel through, for instances with a real vessel.
_ARDUAGENT_ADAPTER_IDS: Dict[AsvSoftwareId, Tuple[str, ...]] = {
    AsvSoftwareId.REPLAY: (REPLAY_ARDUAGENT_FOLLOWER.id,),
    AsvSoftwareId.MISSION_PLANNER: (MISSION_PLANNER_MAVLINK_PORT.id,),
}


def simulation_layer_from_simulator_type(simulator_type: str) -> SimulationLayerId:
    """simulatorType is compared case-insensitively, as before the adapter framework."""
    for layer, label in _SIMULATOR_TYPE_LABELS.items():
        if simulator_type.strip().lower() == label.lower():
            return layer
    raise ValueError(f"Unknown simulatorType '{simulator_type}'; expected one of {', '.join(_SIMULATOR_TYPE_LABELS.values())}.")


def simulator_type_label(layer: SimulationLayerId) -> str:
    if layer not in _SIMULATOR_TYPE_LABELS:
        raise ValueError(f"Simulation layer {layer.value} has no workbench simulatorType.")
    return _SIMULATOR_TYPE_LABELS[layer]


def asv_software_from_control_mode(control_mode: str) -> AsvSoftwareId:
    for asv_software, label in _CONTROL_MODE_LABELS.items():
        if control_mode == label:
            return asv_software
    raise ValueError(f"Unknown controlMode '{control_mode}'; expected one of {', '.join(_CONTROL_MODE_LABELS.values())}.")


def control_mode_label(asv_software: AsvSoftwareId) -> Optional[str]:
    """The controlMode of an ASV software, None for one ArduAgent has no mode for (USV Navigation)."""
    return _CONTROL_MODE_LABELS.get(asv_software)


def default_control_layer(simulation_layer: SimulationLayerId) -> ControlLayerId:
    """The control layer of an agent that names none: the kinematic layer integrates control itself."""
    return ControlLayerId.NONE if simulation_layer == SimulationLayerId.KINEMATIC else ControlLayerId.ARDUPILOT


def _parse_role(enum, value: str, field: str):
    try:
        return enum(value)
    except ValueError:
        raise ValueError(f"Unknown {field} '{value}'; expected one of {', '.join(member.value for member in enum)}.") from None


def workbench_stack(simulator_type: str, asv_software: Optional[str], control_layer: Optional[str], control_mode: Optional[str] = None) -> VesselStackConfig:
    """The triple of one agent: asvSoftware (or, from older clients, controlMode) and controlLayer (or the simulator's default)."""
    simulation_layer = simulation_layer_from_simulator_type(simulator_type)
    if asv_software:
        software = _parse_role(AsvSoftwareId, asv_software, "asvSoftware")
    elif control_mode:
        software = asv_software_from_control_mode(control_mode)
    else:
        raise ValueError("An agent needs an asvSoftware (or a controlMode).")
    control = _parse_role(ControlLayerId, control_layer, "controlLayer") if control_layer else default_control_layer(simulation_layer)
    return VesselStackConfig(asv_software=software, control_layer=control, simulation_layer=simulation_layer)


def workbench_adapter_ids(stack: VesselStackConfig, instance_has_real_vessel: bool) -> Tuple[str, ...]:
    """ArduAgent's adapters in an instance with a real vessel, else the registry's defaults (none named)."""
    if not instance_has_real_vessel:
        return ()
    return _ARDUAGENT_ADAPTER_IDS.get(stack.asv_software, ())
