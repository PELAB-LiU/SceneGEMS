"""Drives a workbench run whose vessels are all simulated with the registry's lockstep runners.

ArduAgent drives an instance with real vessels (vessel_stack/simulation_parser.py), because a
real vessel is reached over WARA-PS MQTT. An instance of simulated vessels only runs, inside
the scenario execution worker, through the runner its stacks resolve to:

- kinematic: KinematicSimulation with each vessel's participant (the replay follower or USV
  Navigation), in the worker itself;
- ardupilot on ardupilot_sim or gazebo: run_mavlink_stack against each vessel's SITL SERIAL0,
  as an attended run, so Mission Planner vessels are observed and left to their operator;
- custom on gazebo: run_gz_custom against the gz-transport actuator in the Gazebo service.

Every step's states reach the worker as a scene. SITL paces itself to the instance's speedup;
the kinematic layer and a Gazebo world stepped by the runner would run as fast as the CPU
allows, so the driver holds them to the speedup on the wall clock, and the workbench shows
the run as it happens.
"""

import threading
import time
from typing import Callable, Dict, Mapping, Optional

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_STATE_FOLLOWER
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_parameters import UsvNavigationParameters
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_specs import usv_navigation_participant_runtime
from scenegems_tool.vessel_stack.contracts.clock import LockstepParticipant
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_specs import KINEMATIC_LAYER

SceneObserver = Callable[[float, ConcreteScene], None]  # (scenario time in s, the scene at that time)


def uses_lockstep_driver(simulation: SimulationInstanceConfig) -> bool:
    """Whether the worker runs the instance with a lockstep runner: every vessel is simulated."""
    return bool(simulation.vessels) and all(vessel.is_simulated for vessel in simulation.vessels.values())


class RunStopped(Exception):
    """Raised from a step observer to end a run that the worker was asked to stop."""


class LockstepSimulationDriver:
    def __init__(
        self,
        simulation: SimulationInstanceConfig,
        trajectories: Trajectories,
        reference_geofence: Geofence,
        *,
        resolver: Optional[StackResolver] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not uses_lockstep_driver(simulation):
            raise ValueError("the lockstep driver runs instances whose vessels are all simulated; ArduAgent drives the others")
        self.simulation = simulation
        self.trajectories = trajectories
        self.reference_geofence = reference_geofence
        self.resolver = resolver or default_resolver()
        self._sleep = sleep
        self._clock = clock
        self._scene = trajectories.initial_scene
        self._running = False
        self._lock = threading.Lock()

    @property
    def kind(self) -> str:
        """kinematic, mavlink or gz_custom: the runner the instance resolves to."""
        if self.simulation.simulation_layer == SimulationLayerId.KINEMATIC:
            return "kinematic"
        layers = {vessel.stack.control_layer for vessel in self.simulation.simulated_vessels.values()}
        return "gz_custom" if layers == {ControlLayerId.CUSTOM} else "mavlink"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_scene(self) -> ConcreteScene:
        with self._lock:
            return self._scene

    def run(self, on_scene: SceneObserver, stop: threading.Event) -> None:
        """Run the instance until its trajectories' timespan, or until stop is set. Blocks."""
        dt = float(self.trajectories.time_step)
        steps = int(round(self.trajectories.timespan / dt))
        paced = self.kind != "mavlink"
        started = self._clock()

        def observe(index: int, states: Mapping[int, ActorState]) -> None:
            if stop.is_set():
                raise RunStopped()
            if paced:
                wait = started + index * dt / max(self.simulation.speedup, 1) - self._clock()
                if wait > 0:
                    self._sleep(wait)
            scene = self._scene_of(states)
            with self._lock:
                self._scene = scene
                self._running = True
            on_scene(index * dt, scene)

        try:
            if self.kind == "kinematic":
                self._run_kinematic(dt, steps, observe)
            elif self.kind == "gz_custom":
                from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import run_gz_custom

                run_gz_custom(self.trajectories, self.simulation, dt=dt, steps=steps, resolver=self.resolver, on_step=observe)
            else:
                from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import run_mavlink_stack

                run_mavlink_stack(
                    self.trajectories,
                    self.simulation,
                    self.reference_geofence,
                    dt=dt,
                    steps=steps,
                    resolver=self.resolver,
                    attended=True,
                    on_step=lambda index, samples: observe(index, {vessel_id: sample.state for vessel_id, sample in samples.items()}),
                )
        except RunStopped:
            pass
        finally:
            self._running = False

    def _run_kinematic(self, dt: float, steps: int, observe: Callable[[int, Mapping[int, ActorState]], None]) -> None:
        from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_lockstep

        self.resolver.require_instance(self.simulation, attended=True)
        scene = self.trajectories.initial_scene
        participants: Dict[int, LockstepParticipant] = {}
        for agent_id, vessel_config in self.simulation.simulated_vessels.items():
            vessel = scene.get_by_id(agent_id)
            if not isinstance(vessel, ConcreteVessel):
                raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")
            states = self.trajectories.state_list(vessel)
            if vessel_config.stack.asv_software == AsvSoftwareId.USV_NAVIGATION:
                participants[vessel.id] = usv_navigation_participant_runtime()(vessel, UsvNavigationParameters.from_reference(vessel, states, scene.actors, dt))
            else:
                participants[vessel.id] = self.resolver.registry.runtime(REPLAY_STATE_FOLLOWER.id)(vessel, states, self.trajectories.time_step)
        simulation_class = self.resolver.registry.runtime(KINEMATIC_LAYER.id)
        simulation = simulation_class(scene, dt, [participant.participant_id for participant in participants.values()])
        actors = simulation.actors

        def on_step(index, snapshot) -> bool:
            observe(index, {actor.id: state for actor, state in zip(actors, snapshot) if isinstance(actor, ConcreteVessel)})
            return False

        run_lockstep(simulation, participants, steps, self.simulation.environment.seed, on_step)

    def _scene_of(self, states: Mapping[int, ActorState]) -> ConcreteScene:
        """The initial scene with every vessel at its observed state (static obstacles stay where they are)."""
        initial = self.trajectories.initial_scene
        return ConcreteScene({actor: states.get(actor.id, initial[actor]) for actor in initial.actors})
