"""In-process lockstep runner for the kinematic layer, and a replay run of generated trajectories.

The runner owns no time of its own: every step it takes the simulation's step request,
collects one command and one acknowledgement per participant, and lets the simulation
advance. A run is bit-identical across repeats and processes for the same inputs.
"""

import dataclasses
import hashlib
import struct
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_STATE_FOLLOWER
from scenegems_tool.vessel_stack.contracts.clock import LockstepParticipant, StepAck, derive_seed
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_specs import KINEMATIC_LAYER

KINEMATIC_REPLAY_STACK = VesselStackConfig(asv_software=AsvSoftwareId.REPLAY, control_layer=ControlLayerId.NONE, simulation_layer=SimulationLayerId.KINEMATIC)


@dataclass(frozen=True)
class KinematicRunResult:
    actors: Tuple[ConcreteActor, ...]
    dt: float
    run_seed: int
    participant_seeds: Tuple[Tuple[str, int], ...]
    states: Tuple[Tuple[ActorState, ...], ...]  # per step from t = 0, one state per actor in `actors` order
    run_record: Mapping[str, Any]

    @property
    def steps(self) -> int:
        return len(self.states) - 1

    def state_digest(self) -> str:
        """SHA-256 over the exact float64 bits of every recorded state."""
        digest = hashlib.sha256()
        for step_states in self.states:
            for state in step_states:
                digest.update(struct.pack("<4d", float(state.x), float(state.y), float(state.speed), float(state.heading)))
        return digest.hexdigest()

    def to_trajectories(self) -> Trajectories:
        if not float(self.dt).is_integer():
            raise ValueError(f"Trajectories need an integer time step; this run used dt={self.dt}")
        builder = TrajectoryBuilder(time_step=int(self.dt))
        for step_states in self.states:
            builder.add_scene_as_dict(dict(zip(self.actors, step_states)))
        return builder.build()


def run_lockstep(simulation: KinematicSimulation, participants: Mapping[int, LockstepParticipant], steps: int, run_seed: int) -> KinematicRunResult:
    """Run `steps` lockstep steps. `participants` maps a vessel id to the participant that commands it."""
    ordered = sorted(participants.items())
    participant_ids = tuple(sorted(participant.participant_id for _, participant in ordered))
    if participant_ids != simulation.clock.participant_ids:
        raise ValueError(f"Participants {participant_ids} do not match the clock participants {simulation.clock.participant_ids}")
    seeds: Dict[str, int] = {}
    for _, participant in ordered:
        seeds[participant.participant_id] = derive_seed(run_seed, participant.participant_id)
        participant.start(seeds[participant.participant_id])

    recorded = [simulation.snapshot()]
    for _ in range(steps):
        request = simulation.step_request()
        commands = {}
        acks = []
        for vessel_id, participant in ordered:
            commands[vessel_id] = participant.on_step(request, simulation.observe(vessel_id))
            acks.append(StepAck(participant_id=participant.participant_id, index=request.index))
        simulation.step(commands, acks)
        recorded.append(simulation.snapshot())
    return KinematicRunResult(
        actors=simulation.actors,
        dt=simulation.dt,
        run_seed=run_seed,
        participant_seeds=tuple(sorted(seeds.items())),
        states=tuple(recorded),
        run_record={},
    )


def run_kinematic_replay(
    trajectories: Trajectories,
    *,
    environment: Optional[EnvironmentConfig] = None,
    dt: Optional[float] = None,
    steps: Optional[int] = None,
    resolver: Optional[StackResolver] = None,
) -> KinematicRunResult:
    """Replay every vessel of a generated trajectory on the kinematic layer, through the registry.

    The stack (replay, none, kinematic) and the environment are validated by the resolver
    first, so wind or waves are rejected with a reason. dt defaults to the trajectory time
    step and steps to its timespan. The run seed is environment.seed.
    """
    resolver = resolver or default_resolver()
    environment = environment or EnvironmentConfig.calm()
    dt = float(trajectories.time_step) if dt is None else dt
    vessels = trajectories.initial_scene.vessels
    instance = SimulationInstanceConfig(
        simulation_layer=SimulationLayerId.KINEMATIC,
        environment=environment,
        vessels={str(vessel.id): VesselConfig(agent_id=str(vessel.id), stack=KINEMATIC_REPLAY_STACK) for vessel in vessels},
    )
    resolution = resolver.require_instance(instance, attended=False)

    follower_class = resolver.registry.runtime(REPLAY_STATE_FOLLOWER.id)
    simulation_class = resolver.registry.runtime(KINEMATIC_LAYER.id)
    followers = {vessel.id: follower_class(vessel, trajectories.state_list(vessel), trajectories.time_step) for vessel in vessels}
    simulation = simulation_class(trajectories.initial_scene, dt, [follower.participant_id for follower in followers.values()])
    result = run_lockstep(simulation, followers, steps if steps is not None else int(round(trajectories.timespan / dt)), environment.seed)

    specs = _unique_ids(spec.id for chain in resolution.chains.values() for spec in chain.specs)
    tier = resolution.repeatability_tier
    run_record = {
        "stack": str(KINEMATIC_REPLAY_STACK),
        "specs": specs,
        "dt": dt,
        "steps": result.steps,
        "run_seed": environment.seed,
        "participant_seeds": dict(result.participant_seeds),
        "repeatability_tier": tier.value if tier is not None else None,
        "environment": resolution.effective_environment(),
        "state_digest": result.state_digest(),
    }
    return dataclasses.replace(result, run_record=run_record)


def _unique_ids(ids: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(ids))
