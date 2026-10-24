"""Configuration of the USV Navigation runtime and how SceneGEMS derives it from a scenario.

Kept apart from the participant so callers can build parameters without importing
colav_automaton.
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Sequence, Tuple

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel

# Upstream's validated geometric prescribed time (behaviour regression suite and CommonOcean
# batch, dt 1 s). It sizes dsafe = Cs + v * tp and the arrival radius at the virtual waypoint.
DEFAULT_PRESCRIBED_TIME_S = 3.0
# Upstream CommonOcean default for the control horizon, in steps.
DEFAULT_CONTROL_HORIZON_STEPS = 60


@dataclass(frozen=True)
class UsvNavigationParameters:
    """Arguments of one SyncColavRuntime. Use from_reference for the SceneGEMS defaults."""

    goal: Tuple[float, float]  # waypoint [m, local frame]
    speed: float  # v [m/s]: the runtime's fixed speed, also the commanded speed
    safety_radius: float  # Cs [m]: clearance kept around every obstacle
    control_horizon: float  # tp_control [s]: horizon of the prescribed-time heading law
    prescribed_time: float = DEFAULT_PRESCRIBED_TIME_S  # tp [s]
    # Further SyncColavRuntime keyword arguments (a, eta, K, K_off, v1_buffer, ...); upstream defaults when absent.
    runtime_options: Tuple[Tuple[str, float], ...] = ()

    @classmethod
    def from_reference(cls, vessel: ConcreteVessel, reference_states: Sequence[ActorState], actors: Iterable[ConcreteActor], dt: float) -> "UsvNavigationParameters":
        """SceneGEMS defaults for a vessel with a generated trajectory.

        - goal: the end of the generated trajectory, so the run heads where the scenario
          generator sent the vessel.
        - speed: the reference speed at t = 0 (the mean reference speed when that is zero),
          capped at the vessel's max speed. The runtime assumes the vessel keeps it.
        - safety_radius: the largest safety radius in the scene, own ship included, since
          SceneGEMS counts a domain violation when a vessel enters either vessel's safety
          radius, and the runtime takes one Cs for all obstacles.
        - control_horizon: the longest of 60 steps (upstream default), tp, and one full turn
          at the vessel's max yaw rate. The prescribed-time feedback switches off
          control_horizon seconds after each transition, so the vessel must be able to turn
          through half a circle well before that.
        - prescribed_time and every other runtime argument: upstream defaults.
        """
        if not reference_states:
            raise ValueError(f"Vessel {vessel.id} has an empty reference trajectory")
        speed = float(reference_states[0].speed)
        if speed <= 0:
            speed = float(np.mean([state.speed for state in reference_states]))
        speed = min(speed, vessel.max_speed)
        if speed <= 0:
            raise ValueError(f"Vessel {vessel.id} has no positive reference speed, which USV Navigation needs")
        end = reference_states[-1]
        full_turn_s = 2 * math.pi / vessel.max_angular_speed if vessel.max_angular_speed > 0 else 0.0
        return cls(
            goal=(float(end.x), float(end.y)),
            speed=speed,
            safety_radius=max(float(actor.safety_radius) for actor in actors),
            control_horizon=max(DEFAULT_CONTROL_HORIZON_STEPS * dt, DEFAULT_PRESCRIBED_TIME_S, full_turn_s),
        )

    def runtime_kwargs(self) -> Dict[str, float]:
        return {"Cs": self.safety_radius, "v": self.speed, "tp": self.prescribed_time, "tp_control": self.control_horizon, **dict(self.runtime_options)}

    def as_dict(self) -> Dict[str, Any]:
        return {"goal": list(self.goal), **self.runtime_kwargs()}
