"""The stages a case passes through, the jobs they run, and the case's bookkeeping of them.

Per case:

    generate_scene          scene_generation job
    generate_trajectories   trajectory_generation job (monitor_driven_rrt or straight)
    per run, per repeat:
      simulate              simulation.kinematic job; with the live monitor the job judges the run itself
    per run:
      monitor               monitoring.post_hoc job over repeat 0's state log (post_hoc only)
      calibrate             calibration.deviation job over the run's repeats (repeats above one only)
      verdict               no job: the engine writes it, from the post-hoc result, the simulation's
                            monitor section (live) or as unmonitored (empty)

A run's verdict judges its repeat 0; the other repeats exist for the calibration. Every repeat
gets a run record.

A case's progress (scenario_case.progress) records what the engine has handled:

    steps   step name (generate_scene, simulate:0:1, monitor:0, ...) to the job's outcome; an event
            of a step already there is a duplicate and changes nothing
    runs    per run index: run_records (repeat index to run record id), verdict (the pending
            verdict until the coverage controller completes the case), tier (the stack's
            repeatability tier), calibrated

The case is ready when every run has its verdict and, with repeats, its calibration. The
coverage controller then completes it (writes its verdicts) or cancels it (above the quota).
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

from scenegems_tool.assurance.campaign.campaign_config import CampaignConfig, RunConfig
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import MonitorImplementation, PipelineStage

# Later stages run first, so started cases finish depth first and their artifacts live briefly
STAGE_PRIORITY_OFFSET = {
    PipelineStage.GENERATE_SCENE: 0,
    PipelineStage.GENERATE_TRAJECTORIES: 1,
    PipelineStage.SIMULATE: 2,
    PipelineStage.MONITOR: 3,
    PipelineStage.CALIBRATE: 4,
}
STAGE_JOB_TYPES = {
    PipelineStage.GENERATE_SCENE: JobType.SCENE_GENERATION,
    PipelineStage.GENERATE_TRAJECTORIES: JobType.TRAJECTORY_GENERATION,
    PipelineStage.SIMULATE: JobType.SIMULATION_KINEMATIC,  # the only simulation layer of a campaign run so far
    PipelineStage.MONITOR: JobType.MONITORING_POST_HOC,
    PipelineStage.CALIBRATE: JobType.CALIBRATION_DEVIATION,
}
JOB_STAGES = tuple(STAGE_JOB_TYPES)


@dataclass(frozen=True)
class Step:
    """One job of a case: its stage, and its run and repeat for the per-run stages."""

    stage: PipelineStage
    run_index: Optional[int] = None
    repeat_index: Optional[int] = None

    def __post_init__(self) -> None:
        if self.stage == PipelineStage.VERDICT:
            raise ValueError("the verdict stage runs no job")
        per_run = self.stage in (PipelineStage.SIMULATE, PipelineStage.MONITOR, PipelineStage.CALIBRATE)
        if per_run != (self.run_index is not None) or (self.stage == PipelineStage.SIMULATE) != (self.repeat_index is not None):
            raise ValueError(f"step {self.stage.value} with run {self.run_index} and repeat {self.repeat_index}")

    @property
    def name(self) -> str:
        """The step's name in the case's progress: generate_scene, simulate:0:1, monitor:0."""
        return ":".join([self.stage.value] + [str(index) for index in (self.run_index, self.repeat_index) if index is not None])

    @property
    def job_type(self) -> JobType:
        return STAGE_JOB_TYPES[self.stage]

    def idempotency_key(self, campaign_id: str, case_id: int) -> str:
        """The key of the step's pipeline job and job: campaign:<id>:case:<case id>:<step name>."""
        return f"campaign:{campaign_id}:case:{case_id}:{self.name}"

    def priority(self, campaign_priority: int) -> int:
        return campaign_priority + STAGE_PRIORITY_OFFSET[self.stage]

    @classmethod
    def of(cls, stage: PipelineStage, run_index: Optional[int], repeat_index: Optional[int]) -> "Step":
        return cls(stage, run_index, repeat_index)


SCENE_STEP = Step(PipelineStage.GENERATE_SCENE)
TRAJECTORIES_STEP = Step(PipelineStage.GENERATE_TRAJECTORIES)


class CaseProgress:
    """A mutable view of a case's progress JSON; to_json gives the value to store."""

    def __init__(self, progress: Optional[Mapping[str, Any]] = None):
        progress = progress or {}
        self.steps: Dict[str, str] = dict(progress.get("steps", {}))
        self.runs: Dict[str, Dict[str, Any]] = {run: dict(state) for run, state in progress.get("runs", {}).items()}

    def to_json(self) -> Dict[str, Any]:
        return {"steps": dict(self.steps), "runs": {run: dict(state) for run, state in sorted(self.runs.items(), key=lambda item: int(item[0]))}}

    def handled(self, step: Step) -> bool:
        return step.name in self.steps

    def mark(self, step: Step, outcome: str) -> None:
        self.steps[step.name] = outcome

    def run(self, run_index: int) -> Dict[str, Any]:
        return self.runs.setdefault(str(run_index), {})

    def run_record_id(self, run_index: int, repeat_index: int) -> Optional[int]:
        return self.runs.get(str(run_index), {}).get("run_records", {}).get(str(repeat_index))

    def set_run_record(self, run_index: int, repeat_index: int, run_record_id: int) -> None:
        run = self.run(run_index)
        run["run_records"] = {**run.get("run_records", {}), str(repeat_index): run_record_id}

    def run_record_ids(self) -> List[int]:
        return [record_id for run in self.runs.values() for record_id in run.get("run_records", {}).values()]

    def pending_verdict(self, run_index: int) -> Optional[Dict[str, Any]]:
        return self.runs.get(str(run_index), {}).get("verdict")


class StageGraph:
    """The steps of a case under one campaign config."""

    def __init__(self, config: CampaignConfig):
        self.config = config
        self.runs: tuple = config.execution.runs

    def run(self, run_index: int) -> RunConfig:
        return self.runs[run_index]

    def simulate_steps(self) -> List[Step]:
        return [Step(PipelineStage.SIMULATE, run_index, repeat) for run_index, run in enumerate(self.runs) for repeat in range(run.repeats)]

    def needs_monitor_job(self, run_index: int) -> bool:
        return self.runs[run_index].monitor == MonitorImplementation.POST_HOC

    def needs_calibration(self, run_index: int) -> bool:
        return self.runs[run_index].repeats > 1

    def simulated(self, progress: CaseProgress, run_index: int) -> bool:
        """Every repeat of the run is simulated."""
        return all(progress.handled(Step(PipelineStage.SIMULATE, run_index, repeat)) for repeat in range(self.runs[run_index].repeats))

    def steps_after_simulation(self, progress: CaseProgress, run_index: int, repeat_index: int) -> List[Step]:
        """The jobs that become due when the given repeat of the run is simulated (and recorded in progress)."""
        due = []
        if repeat_index == 0 and self.needs_monitor_job(run_index):
            due.append(Step(PipelineStage.MONITOR, run_index))
        if self.needs_calibration(run_index) and self.simulated(progress, run_index):
            due.append(Step(PipelineStage.CALIBRATE, run_index))
        return due

    def run_finished(self, progress: CaseProgress, run_index: int) -> bool:
        run = progress.runs.get(str(run_index), {})
        return "verdict" in run and (not self.needs_calibration(run_index) or bool(run.get("calibrated")))

    def ready(self, progress: CaseProgress) -> bool:
        """Every run has its verdict, and its calibration when it has repeats."""
        return all(self.run_finished(progress, run_index) for run_index in range(len(self.runs)))

    def stage_of(self, progress: CaseProgress) -> PipelineStage:
        """The earliest stage with work left; verdict once the case is ready."""
        if not progress.handled(SCENE_STEP):
            return PipelineStage.GENERATE_SCENE
        if not progress.handled(TRAJECTORIES_STEP):
            return PipelineStage.GENERATE_TRAJECTORIES
        if not all(progress.handled(step) for step in self.simulate_steps()):
            return PipelineStage.SIMULATE
        indexes = range(len(self.runs))
        if any(self.needs_monitor_job(run_index) and not progress.handled(Step(PipelineStage.MONITOR, run_index)) for run_index in indexes):
            return PipelineStage.MONITOR
        if any(self.needs_calibration(run_index) and not progress.handled(Step(PipelineStage.CALIBRATE, run_index)) for run_index in indexes):
            return PipelineStage.CALIBRATE
        return PipelineStage.VERDICT


def job_types_of(stages: Iterable[PipelineStage]) -> List[JobType]:
    return sorted({STAGE_JOB_TYPES[stage] for stage in stages if stage in STAGE_JOB_TYPES}, key=lambda job_type: job_type.value)
