"""monitoring.post_hoc: judge a finished state log against COLREGS, in a monitoring container.

The monitor runs in process over every scene of the trajectories, as the live monitor does
for streamed batches, but without MQTT in between (the live path is the measured throughput
limit, design doc 10.5). Each job gets its own container, so the node's slots bound the
monitors that run at once. The result lists, per vessel pair and rule, when each outcome
first held (subsystems/monitoring/rule_outcomes.py, the same summary as the live monitor
of a kinematic simulation); the monitored frames are added on request.
"""

import threading
from typing import Any, Dict, Optional, Tuple

from pydantic import Field

from scenegems_tool.cluster.node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import TrajectoriesInput, parse_payload, to_trajectories
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback, run_in_runner_container
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel

_PROGRESS_EVERY_SCENES = 100

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("frames", ArtifactKind.FRAMES),)


class PostHocMonitoringPayload(ProtocolModel):
    trajectories: TrajectoriesInput  # the state log to judge
    colregs_constraints_content: Optional[str] = None  # COLREGS constants YAML; the general maritime defaults when None
    scenario_id: str = "post-hoc"  # scenarioId of the returned frames
    include_frames: bool = False  # add every monitored frame in the workbench's wire format
    timeout_s: float = Field(default=600.0, gt=0.0)


PAYLOAD_MODEL = PostHocMonitoringPayload


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(PostHocMonitoringPayload, job)
    return run_in_runner_container(job, node, report, Subsystem.MONITORING, timeout_s=payload.timeout_s, cancel=cancel)


def execute(job: JobSpec, status: StatusCallback) -> JobResultData:
    """The in-container part: monitor every scene in order and summarize the verdicts."""
    from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
    from scenegems_tool.gateway.serialization import serialize_monitored_frame
    from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
    from utils.colregs_approximations import COLREGSConstraints

    payload = parse_payload(PostHocMonitoringPayload, job)
    trajectories = to_trajectories(payload.trajectories)
    constants = COLREGSConstraints.from_file_content(payload.colregs_constraints_content) if payload.colregs_constraints_content else COLREGSConstraints.default_general_maritime()
    runtime = ColregsMonitorRuntime(constants)
    time_step = trajectories.time_step
    scene_count = len(trajectories.scene_list)

    outcomes = RuleOutcomes()
    frames = []
    for index, scene in enumerate(trajectories.scene_list):
        runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=index * time_step, time_step=time_step))
        for monitored_scene in runtime.monitor_current_tasks():
            outcomes.add(monitored_scene)
            if payload.include_frames:
                frames.append(serialize_monitored_frame(scenario_id=payload.scenario_id, monitored_scene=monitored_scene, timestamp=monitored_scene.timestamp, time_step=time_step))
        if (index + 1) % _PROGRESS_EVERY_SCENES == 0:
            status(f"monitored {index + 1} of {scene_count} scenes", (index + 1) / scene_count)

    data: Dict[str, Any] = {"scenes": scene_count, "monitored_scenes": outcomes.monitored_scenes, "time_step": time_step, **outcomes.summary()}
    if payload.include_frames:
        data["frames"] = frames
    return data
