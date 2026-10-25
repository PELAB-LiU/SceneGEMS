"""Reference vessels and trajectories of the measurements.

The vessels are the ones of the Phase 0 and Phase 2 measurements: a 5 m, a 30 m and a 100 m
hull with the limits of design doc 12.7. The trajectories are generated with the project's own
kinematic layer, so a measurement starts from the same kind of input a campaign produces.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_lockstep
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation


@dataclass(frozen=True)
class VesselScale:
    length: float
    max_speed: float  # m/s
    max_angular_speed: float  # rad/s
    max_acceleration: float  # m/s^2
    cruise_speed: float  # m/s, the speed of the reference runs


VESSEL_SCALES: Dict[str, VesselScale] = {
    "5m": VesselScale(length=5.0, max_speed=4.0, max_angular_speed=0.5, max_acceleration=1.0, cruise_speed=3.0),
    "30m": VesselScale(length=30.0, max_speed=20.57778, max_angular_speed=0.05, max_acceleration=0.4, cruise_speed=8.0),
    "100m": VesselScale(length=100.0, max_speed=12.9, max_angular_speed=0.008, max_acceleration=0.05, cruise_speed=8.0),
}

SPEED = 8.0  # m/s of the encounters
# The own ship starts at the origin heading east (x east, y north, heading counterclockwise from east).
ENCOUNTER_TARGETS: Dict[str, ActorState] = {
    "head_on": ActorState(6000.0, 0.0, SPEED, math.pi),
    "crossing_from_starboard": ActorState(3600.0, -3600.0, SPEED, math.pi / 2),
    "crossing_from_port": ActorState(3600.0, 3600.0, SPEED, -math.pi / 2),
    "overtaking": ActorState(1500.0, 0.0, 3.0, 0.0),
}


def make_vessel(vessel_id: int, is_os: bool, length: float = 30.0, max_speed: float = 20.57778, max_angular_speed: float = 0.05, max_acceleration: float = 0.4) -> ConcreteVessel:
    """A passenger-ship-like vessel with a safety radius of four lengths."""
    vessel = ConcreteActor.from_dict(
        {
            "id": vessel_id,
            "type": "OSPassengerShip" if is_os else "PassengerShip",
            "length": length,
            "breadth": length / 3,
            "safety_radius": 4 * length,
            "is_vessel": True,
            "_is_os": is_os,
            "_max_speed": max_speed,
            "_max_angular_speed": max_angular_speed,
            "_max_acceleration": max_acceleration,
        }
    )
    assert isinstance(vessel, ConcreteVessel)
    return vessel


def scaled_vessel(scale: str, vessel_id: int = 0, is_os: bool = True) -> ConcreteVessel:
    spec = VESSEL_SCALES[scale]
    return make_vessel(vessel_id, is_os, spec.length, spec.max_speed, spec.max_angular_speed, spec.max_acceleration)


def encounter_scene(name: str) -> ConcreteScene:
    return ConcreteScene({make_vessel(0, True): ActorState(0.0, 0.0, SPEED, 0.0), make_vessel(1, False): ENCOUNTER_TARGETS[name]})


def encounter_trajectories(name: str, timespan: int = 300, time_step: int = 1) -> Trajectories:
    """Straight-line trajectories of one controlled encounter, the generator's stand-in."""
    return TrajectoryBuilder.default_trajectory_from_scene(encounter_scene(name), time_step, timespan)


def straight_run(scale: str = "5m", duration_s: int = 90, time_step: int = 1) -> Trajectories:
    """One vessel heading east at its cruise speed."""
    vessel = scaled_vessel(scale)
    state = ActorState(0.0, 0.0, VESSEL_SCALES[scale].cruise_speed, 0.0)
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene({vessel: state}), time_step, duration_s)


class _HeadingSchedule:
    """Lockstep participant that commands the heading of a list of (start time, heading) legs."""

    def __init__(self, vessel: ConcreteVessel, legs: List[Tuple[float, float]], speed: float):
        self.participant_id = f"schedule/{vessel.id}"
        self._legs = legs
        self._speed = speed

    def start(self, seed: int) -> None:
        del seed

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        heading = [leg_heading for start, leg_heading in self._legs if start <= request.time][-1]
        return HeadingSpeedCommand(heading=heading, speed=self._speed)


def turning_run(scale: str = "5m", duration_s: int = 120, time_step: int = 1) -> Trajectories:
    """One vessel that turns 90 degrees to port and back to east, a third of the run each.

    Straight runs give the smallest repeat envelope, so a calibration also needs turns (design doc 10.6).
    """
    spec = VESSEL_SCALES[scale]
    vessel = scaled_vessel(scale)
    third = duration_s / 3.0
    legs = [(0.0, 0.0), (third, math.pi / 2), (2 * third, 0.0)]
    participant = _HeadingSchedule(vessel, legs, spec.cruise_speed)
    simulation = KinematicSimulation(ConcreteScene({vessel: ActorState(0.0, 0.0, spec.cruise_speed, 0.0)}), float(time_step), [participant.participant_id])
    result = run_lockstep(simulation, {vessel.id: participant}, int(duration_s / time_step), run_seed=0)
    return result.to_trajectories()


REFERENCE_RUNS = ("straight", "turning")


def reference_run(kind: str, scale: str = "5m", duration_s: int = 90) -> Trajectories:
    if kind == "straight":
        return straight_run(scale, duration_s)
    if kind == "turning":
        return turning_run(scale, duration_s)
    raise ValueError(f"Unknown reference run '{kind}'; expected one of {', '.join(REFERENCE_RUNS)}")
