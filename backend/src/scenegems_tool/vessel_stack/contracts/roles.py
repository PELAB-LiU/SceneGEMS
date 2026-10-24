"""Roles of a vessel stack and the implementations each role can have.

A vessel stack is a triple: the ASV software decides where the vessel goes, the control
layer turns that decision into actuation, and the simulation layer moves the vessel. The
enum values are the ids used in configuration, in the registry and in run records.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Union


class Role(str, Enum):
    ASV_SOFTWARE = "asv_software"
    CONTROL_LAYER = "control_layer"
    SIMULATION_LAYER = "simulation_layer"


class AsvSoftwareId(str, Enum):
    REPLAY = "replay"  # follows the generated trajectory
    USV_NAVIGATION = "usv_navigation"
    MISSION_PLANNER = "mission_planner"  # an operator or external software on a MAVLink port


class ControlLayerId(str, Enum):
    ARDUPILOT = "ardupilot"
    CUSTOM = "custom"
    NONE = "none"  # the simulation layer integrates control itself


class SimulationLayerId(str, Enum):
    KINEMATIC = "kinematic"
    GAZEBO = "gazebo"
    ARDUPILOT_SIM = "ardupilot_sim"


LayerImplementationId = Union[AsvSoftwareId, ControlLayerId, SimulationLayerId]

_ROLE_BY_IMPLEMENTATION_TYPE = {
    AsvSoftwareId: Role.ASV_SOFTWARE,
    ControlLayerId: Role.CONTROL_LAYER,
    SimulationLayerId: Role.SIMULATION_LAYER,
}

STACK_ROLE_ORDER = (Role.ASV_SOFTWARE, Role.CONTROL_LAYER, Role.SIMULATION_LAYER)


@dataclass(frozen=True)
class LayerRef:
    """One implementation of one role, a node of the adapter graph."""

    role: Role
    impl: str

    @classmethod
    def of(cls, implementation: LayerImplementationId) -> "LayerRef":
        return cls(_ROLE_BY_IMPLEMENTATION_TYPE[type(implementation)], implementation.value)

    def __str__(self) -> str:
        return f"{self.role.value}/{self.impl}"
