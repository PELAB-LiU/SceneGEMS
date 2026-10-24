"""Replay ASV software as a lockstep participant on the heading_speed_cmd port."""

import math
from typing import Optional, Sequence

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_STATE_FOLLOWER
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from utils.global_constants import EPSILON
from utils.math_utils import calculate_heading, heading_diff, rotate_heading


class ReplayFollower:
    """Tracks a generated trajectory with heading and speed commands, stepped only by the simulation clock.

    While the vessel is on the reference it commands the reference heading and speed at the
    step's target time, which reproduces a trajectory generated with the same kinematics.
    When it is more than position_tolerance_m off, it steers toward the reference point
    lookahead_s ahead (pure pursuit) at the speed that closes the gap in that time.
    """

    spec = REPLAY_STATE_FOLLOWER

    def __init__(
        self,
        vessel: ConcreteVessel,
        reference_states: Sequence[ActorState],
        reference_time_step: float,
        *,
        lookahead_s: float = 10.0,
        position_tolerance_m: Optional[float] = None,
    ):
        if not reference_states:
            raise ValueError(f"Vessel {vessel.id} has an empty reference trajectory")
        if reference_time_step <= 0:
            raise ValueError(f"reference_time_step must be positive, got {reference_time_step}")
        self.vessel = vessel
        self.participant_id = f"replay/{vessel.id}"
        self.lookahead_s = lookahead_s
        self.position_tolerance_m = position_tolerance_m if position_tolerance_m is not None else max(1.0, 0.1 * vessel.length)
        self._reference = tuple(reference_states)
        self._reference_time_step = float(reference_time_step)

    def start(self, seed: int) -> None:
        del seed  # the follower has no randomness

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        own = observation.own_state
        if float(np.linalg.norm(self.reference_state(request.time).p - own.p)) <= self.position_tolerance_m:
            target = self.reference_state(request.target_time)
            return HeadingSpeedCommand(heading=target.heading, speed=target.speed)
        carrot = self.reference_state(request.time + self.lookahead_s)
        offset = carrot.p - own.p
        gap = float(np.linalg.norm(offset))
        if gap < EPSILON:
            return HeadingSpeedCommand(heading=carrot.heading, speed=carrot.speed)
        return HeadingSpeedCommand(heading=float(calculate_heading(offset)), speed=float(np.clip(gap / self.lookahead_s, 0.0, self.vessel.max_speed)))

    def reference_state(self, time: float) -> ActorState:
        """Reference state at a simulated time, interpolated between samples and held at both ends."""
        last = len(self._reference) - 1
        position = time / self._reference_time_step
        if position <= 0:
            return self._reference[0]
        if position >= last:
            return self._reference[last]
        index = int(math.floor(position))
        fraction = position - index
        before = self._reference[index]
        if fraction == 0.0:
            return before
        after = self._reference[index + 1]
        return ActorState(
            x=before.x + (after.x - before.x) * fraction,
            y=before.y + (after.y - before.y) * fraction,
            speed=before.speed + (after.speed - before.speed) * fraction,
            heading=rotate_heading(before.heading, heading_diff(after.heading, before.heading) * fraction),
        )
