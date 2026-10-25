"""simulation.kinematic: a lockstep run on the kinematic layer, in a scenario execution container.

Two modes: replay of every vessel's generated trajectory (kinematic_runner.run_kinematic_replay),
or USV Navigation on the own ship against replaying targets (run_kinematic_closed_loop).
The run needs no other service, so its container has no network. A run is bit-identical
for the same payload, and the result carries its state digest.

With monitor live, the COLREGS monitor judges every step in process with the post-hoc
monitor's summary (subsystems/monitoring/rule_outcomes.py), and early_stop ends the run once
every rule is decided. A run without a monitor is the same run as before the monitor existed.
"""

import threading
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import TrajectoriesInput, parse_payload, to_trajectories
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback, run_in_runner_container
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_parameters import DEFAULT_PRESCRIBED_TIME_S, UsvNavigationParameters

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)


class KinematicMode(str, Enum):
    REPLAY = "replay"  # every vessel replays its trajectory
    USV_NAVIGATION = "usv_navigation"  # the own ship runs USV Navigation, the others replay


class KinematicMonitor(str, Enum):
    NONE = "none"  # no monitor in the run; a post-hoc or empty monitor may follow
    LIVE = "live"  # the COLREGS monitor in process, step by step


class UsvNavigationPayload(ProtocolModel):
    """UsvNavigationParameters in full; leave it out for the SceneGEMS defaults (from_reference)."""

    goal: Tuple[float, float]
    speed: float = Field(gt=0.0)
    safety_radius: float = Field(gt=0.0)
    control_horizon: float = Field(gt=0.0)
    prescribed_time: float = Field(default=DEFAULT_PRESCRIBED_TIME_S, gt=0.0)
    runtime_options: Dict[str, float] = Field(default_factory=dict)

    def to_parameters(self) -> UsvNavigationParameters:
        return UsvNavigationParameters(
            goal=self.goal,
            speed=self.speed,
            safety_radius=self.safety_radius,
            control_horizon=self.control_horizon,
            prescribed_time=self.prescribed_time,
            runtime_options=tuple(sorted(self.runtime_options.items())),
        )


class KinematicSimulationPayload(ProtocolModel):
    mode: KinematicMode = KinematicMode.REPLAY
    trajectories: TrajectoriesInput
    own_ship_id: Optional[int] = None  # usv_navigation only; the scene's own ship when None
    usv_navigation: Optional[UsvNavigationPayload] = None  # usv_navigation only
    dt: Optional[float] = Field(default=None, gt=0.0)  # the trajectories' time step when None
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when None
    seed: int = 0  # run seed (EnvironmentConfig.seed)
    monitor: KinematicMonitor = KinematicMonitor.NONE
    early_stop: bool = False  # live only: end the run once every rule of every relation is decided
    colregs_constraints_content: Optional[str] = None  # live only: COLREGS constants YAML; the general maritime defaults when None
    include_trajectories: bool = True  # return the simulated trajectories, not only the run record
    timeout_s: float = Field(default=600.0, gt=0.0)

    @model_validator(mode="after")
    def _closed_loop_options_need_closed_loop(self) -> "KinematicSimulationPayload":
        if self.mode == KinematicMode.REPLAY and (self.own_ship_id is not None or self.usv_navigation is not None):
            raise ValueError("own_ship_id and usv_navigation apply only to mode usv_navigation")
        return self

    @model_validator(mode="after")
    def _monitor_options_need_the_live_monitor(self) -> "KinematicSimulationPayload":
        if self.monitor != KinematicMonitor.LIVE and (self.early_stop or self.colregs_constraints_content is not None):
            raise ValueError("early_stop and colregs_constraints_content apply only to monitor live")
        if self.monitor == KinematicMonitor.LIVE and self.dt is not None and not float(self.dt).is_integer():
            raise ValueError("the live monitor needs a whole number of seconds as dt")
        return self


PAYLOAD_MODEL = KinematicSimulationPayload


class LiveMonitor:
    """The COLREGS monitor fed by the run's step observer, as monitoring.post_hoc feeds it scene by scene."""

    def __init__(self, actors, time_step: int, colregs_constraints_content: Optional[str], early_stop: bool):
        from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime
        from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
        from utils.colregs_approximations import COLREGSConstraints

        constants = COLREGSConstraints.from_file_content(colregs_constraints_content) if colregs_constraints_content else COLREGSConstraints.default_general_maritime()
        self.actors = tuple(actors)
        self.time_step = time_step
        self.early_stop = early_stop
        self.runtime = ColregsMonitorRuntime(constants)
        self.outcomes = RuleOutcomes()
        self.scenes = 0
        self.decided_at: Optional[int] = None  # scenario time at which every rule was decided, with early_stop

    def on_step(self, index: int, states) -> bool:
        from concrete_level.colregs_monitoring.colregs_monitor_runtime import MonitoringTask
        from concrete_level.trajectory_generation.scene_builder import SceneBuilder

        builder = SceneBuilder()
        builder.set_states_as_dict(dict(zip(self.actors, states)))  # the scene KinematicRunResult.to_trajectories builds for this step
        self.runtime.add_task(MonitoringTask(scene=builder.build(), scene_timestamp=index * self.time_step, time_step=self.time_step))
        self.scenes += 1
        for monitored_scene in self.runtime.monitor_current_tasks():
            self.outcomes.add(monitored_scene)
        if self.early_stop and self.outcomes.every_rule_decided():
            self.decided_at = index * self.time_step
            return True
        return False

    def result(self, stopped_early: bool) -> Dict[str, Any]:
        """The post-hoc result shape, plus the scenario time the run stopped at when the monitor ended it early."""
        return {
            "scenes": self.scenes,
            "monitored_scenes": self.outcomes.monitored_scenes,
            "time_step": self.time_step,
            **self.outcomes.summary(),
            "stopped_early_at": self.decided_at if stopped_early else None,
        }


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(KinematicSimulationPayload, job)
    return run_in_runner_container(job, node, report, Subsystem.SCENARIO_EXECUTION, timeout_s=payload.timeout_s, cancel=cancel)


def execute(job: JobSpec, status: StatusCallback) -> JobResultData:
    """The in-container part: run the simulation in process and describe the run."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
    from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_closed_loop, run_kinematic_replay

    payload = parse_payload(KinematicSimulationPayload, job)
    trajectories = to_trajectories(payload.trajectories)
    environment = EnvironmentConfig.calm(seed=payload.seed)
    dt = float(trajectories.time_step) if payload.dt is None else payload.dt
    planned_steps = payload.steps if payload.steps is not None else int(round(trajectories.timespan / dt))
    monitor = LiveMonitor(trajectories.initial_scene.actors, int(dt), payload.colregs_constraints_content, payload.early_stop) if payload.monitor == KinematicMonitor.LIVE else None
    on_step = monitor.on_step if monitor is not None else None
    status(f"running the kinematic {payload.mode.value} run" + (" with the live monitor" if monitor is not None else ""))
    if payload.mode == KinematicMode.REPLAY:
        result = run_kinematic_replay(trajectories, environment=environment, dt=payload.dt, steps=payload.steps, on_step=on_step)
    else:
        parameters = payload.usv_navigation.to_parameters() if payload.usv_navigation is not None else None
        result = run_kinematic_closed_loop(
            trajectories, own_ship_id=payload.own_ship_id, usv_navigation_parameters=parameters, environment=environment, dt=payload.dt, steps=payload.steps, on_step=on_step
        )
    status("run finished", 1.0)
    data: JobResultData = {"run_record": dict(result.run_record), "steps": result.steps, "state_digest": result.state_digest()}
    if monitor is not None:
        data["monitor"] = monitor.result(stopped_early=result.steps < planned_steps)
    if payload.include_trajectories:
        data["trajectories"] = result.to_trajectories().to_dict()
    return data
