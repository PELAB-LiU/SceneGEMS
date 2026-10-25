"""Maps the workbench wire vocabulary to vessel stack triples and back.

The browser still sends the pre-adapter fields: one global simulatorType and a per-agent
controlMode. Inside the backend these become a (ASV software, control layer, simulation
layer) triple per vessel. Every Docker-based workbench stack runs the ardupilot control
layer, and autonomous vessels select the ArduAgent follower, not the registry's default
lockstep MAVLink link, because the workbench reaches its vessels over WARA-PS MQTT. The labels sent back (simulation_models, the scenario execution worker body) are the
ones the browser offers, so the round trip is unchanged.
"""

from typing import Dict, Tuple

from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig

WORKBENCH_CONTROL_LAYER = ControlLayerId.ARDUPILOT

_SIMULATOR_TYPE_LABELS: Dict[SimulationLayerId, str] = {
    SimulationLayerId.GAZEBO: "Gazebo",
    SimulationLayerId.ARDUPILOT_SIM: "ArduPilot Sim",
}
_CONTROL_MODE_LABELS: Dict[AsvSoftwareId, str] = {
    AsvSoftwareId.REPLAY: "autonomous",
    AsvSoftwareId.MISSION_PLANNER: "external",
}
_WORKBENCH_ADAPTER_IDS: Dict[AsvSoftwareId, Tuple[str, ...]] = {
    AsvSoftwareId.REPLAY: (REPLAY_ARDUAGENT_FOLLOWER.id,),
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


def control_mode_label(asv_software: AsvSoftwareId) -> str:
    if asv_software not in _CONTROL_MODE_LABELS:
        raise ValueError(f"ASV software {asv_software.value} has no workbench controlMode.")
    return _CONTROL_MODE_LABELS[asv_software]


def workbench_adapter_ids(control_mode: str) -> Tuple[str, ...]:
    """Adapters the workbench selects: it drives its vessels through ArduAgent over WARA-PS MQTT,
    while the registry's default from replay to ardupilot is the lockstep MAVLink link."""
    return _WORKBENCH_ADAPTER_IDS.get(asv_software_from_control_mode(control_mode), ())


def workbench_stack(simulator_type: str, control_mode: str) -> VesselStackConfig:
    return VesselStackConfig(
        asv_software=asv_software_from_control_mode(control_mode),
        control_layer=WORKBENCH_CONTROL_LAYER,
        simulation_layer=simulation_layer_from_simulator_type(simulator_type),
    )
