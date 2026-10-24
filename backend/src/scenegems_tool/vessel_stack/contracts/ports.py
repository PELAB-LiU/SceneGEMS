"""Typed ports that adapters connect, and the payloads of the in-process ones.

Ports are declared on every spec so a reader and the later phases can see what flows
between layers. The resolver matches adapters by their layer ends, not by ports.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel


class Port(str, Enum):
    VESSEL_STATE = "vessel_state"  # sim to everyone: own state and target tracks at a simulated time
    HEADING_SPEED_CMD = "heading_speed_cmd"  # ASV or controller to sim or controller
    WAYPOINT_MISSION = "waypoint_mission"  # ASV to controller: ordered waypoints with speed
    MAVLINK = "mavlink"  # ASV or ground control station to ArduPilot
    ACTUATOR_CMD = "actuator_cmd"  # controller to sim: thruster and rudder commands
    CLOCK = "clock"  # sim to all: simulated time, lockstep step request and ack
    ENVIRONMENT = "environment"  # scenario to sim: wind, waves and seed


@dataclass(frozen=True)
class HeadingSpeedCommand:
    """Payload of the heading_speed_cmd port: desired heading [rad, local frame] and speed [m/s]."""

    heading: float
    speed: float


@dataclass(frozen=True)
class VesselStateObservation:
    """Payload of the vessel_state port for one vessel at one simulated time, in the local frame."""

    sim_time: float
    vessel: ConcreteVessel
    own_state: ActorState
    target_states: Mapping[int, ActorState]  # by actor id
