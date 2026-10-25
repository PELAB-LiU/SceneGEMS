"""simulation.kinematic: a lockstep run on the kinematic layer, in a scenario execution container.

Two modes: replay of every vessel's generated trajectory (kinematic_runner.run_kinematic_replay),
or USV Navigation on the own ship against replaying targets (run_kinematic_closed_loop).
The run needs no other service, so its container has no network. A run is bit-identical
for the same payload, and the result carries its state digest.
"""

import threading
from enum import Enum
from typing import Dict, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import TrajectoriesData, parse_payload, to_trajectories
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback, run_in_runner_container
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_parameters import DEFAULT_PRESCRIBED_TIME_S, UsvNavigationParameters


class KinematicMode(str, Enum):
    REPLAY = "replay"  # every vessel replays its trajectory
    USV_NAVIGATION = "usv_navigation"  # the own ship runs USV Navigation, the others replay


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
    trajectories: TrajectoriesData
    own_ship_id: Optional[int] = None  # usv_navigation only; the scene's own ship when None
    usv_navigation: Optional[UsvNavigationPayload] = None  # usv_navigation only
    dt: Optional[float] = Field(default=None, gt=0.0)  # the trajectories' time step when None
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when None
    seed: int = 0  # run seed (EnvironmentConfig.seed)
    include_trajectories: bool = True  # return the simulated trajectories, not only the run record
    timeout_s: float = Field(default=600.0, gt=0.0)

    @model_validator(mode="after")
    def _closed_loop_options_need_closed_loop(self) -> "KinematicSimulationPayload":
        if self.mode == KinematicMode.REPLAY and (self.own_ship_id is not None or self.usv_navigation is not None):
            raise ValueError("own_ship_id and usv_navigation apply only to mode usv_navigation")
        return self


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(KinematicSimulationPayload, job)
    return run_in_runner_container(job, node, report, Subsystem.SCENARIO_EXECUTION, timeout_s=payload.timeout_s, cancel=cancel)


def execute(job: JobSpec, status: StatusCallback) -> JobResultData:
    """The in-container part: run the simulation in process and describe the run."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
    from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_closed_loop, run_kinematic_replay

    payload = KinematicSimulationPayload.model_validate(job.payload)
    trajectories = to_trajectories(payload.trajectories)
    environment = EnvironmentConfig.calm(seed=payload.seed)
    status(f"running the kinematic {payload.mode.value} run")
    if payload.mode == KinematicMode.REPLAY:
        result = run_kinematic_replay(trajectories, environment=environment, dt=payload.dt, steps=payload.steps)
    else:
        parameters = payload.usv_navigation.to_parameters() if payload.usv_navigation is not None else None
        result = run_kinematic_closed_loop(trajectories, own_ship_id=payload.own_ship_id, usv_navigation_parameters=parameters, environment=environment, dt=payload.dt, steps=payload.steps)
    status("run finished", 1.0)
    data: JobResultData = {"run_record": dict(result.run_record), "steps": result.steps, "state_digest": result.state_digest()}
    if payload.include_trajectories:
        data["trajectories"] = result.to_trajectories().to_dict()
    return data
