"""Kinematic simulation layer: ConcreteVessel.simulate at a fixed dt, behind the lockstep clock.

The layer owns the clock of its instance. No wall clock is read and the dynamics have no
randomness, so a run is a pure function of the initial scene, the commands and dt.
"""

from typing import Dict, Iterable, Mapping, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.vessel_stack.contracts.clock import LockstepClock, StepAck, StepRequest
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_specs import KINEMATIC_LAYER


class KinematicSimulation:
    spec = KINEMATIC_LAYER

    def __init__(self, initial_scene: ConcreteScene, dt: float, participant_ids: Iterable[str]):
        self.dt = dt
        self.clock = LockstepClock(dt, participant_ids)
        self.actors: Tuple[ConcreteActor, ...] = tuple(initial_scene.actors)
        self._vessels: Dict[int, ConcreteVessel] = {actor.id: actor for actor in self.actors if isinstance(actor, ConcreteVessel)}
        self._states: Dict[int, ActorState] = {actor.id: initial_scene[actor] for actor in self.actors}

    @property
    def time(self) -> float:
        return self.clock.time

    def step_request(self) -> StepRequest:
        return self.clock.request()

    def observe(self, vessel_id: int) -> VesselStateObservation:
        return VesselStateObservation(
            sim_time=self.clock.time,
            vessel=self._vessels[vessel_id],
            own_state=self._states[vessel_id],
            target_states={actor_id: state for actor_id, state in self._states.items() if actor_id != vessel_id},
        )

    def step(self, commands: Mapping[int, HeadingSpeedCommand], acks: Iterable[StepAck]) -> None:
        """Advance every vessel by dt once all participants acknowledged; uncommanded vessels hold heading and speed."""
        unknown = sorted(set(commands) - set(self._vessels))
        if unknown:
            raise ValueError(f"Commands for vessels that are not in the scene: {unknown}")
        self.clock.advance(acks)
        for vessel_id, vessel in self._vessels.items():
            state = self._states[vessel_id]
            command = commands.get(vessel_id)
            u_ref = (command.heading, command.speed) if command is not None else (state.heading, state.speed)
            self._states[vessel_id] = vessel.simulate(state, u_ref, self.dt)

    def snapshot(self) -> Tuple[ActorState, ...]:
        """States of all actors in the order of self.actors."""
        return tuple(self._states[actor.id] for actor in self.actors)
