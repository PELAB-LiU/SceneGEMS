"""monitoring.post_hoc: judge a finished state log against COLREGS, in a monitoring container.

The monitor runs in process over every scene of the trajectories, as the live monitor does
for streamed batches, but without MQTT in between (the live path is the measured throughput
limit, design doc 10.5). Each job gets its own container, so the node's slots bound the
monitors that run at once. The result lists, per vessel pair and rule, when each outcome
first held; the monitored frames are added on request.
"""

import threading
from typing import Any, Dict, Optional

from pydantic import Field

from scenegems_tool.cluster.node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import TrajectoriesData, parse_payload, to_trajectories
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback, run_in_runner_container
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel

_PROGRESS_EVERY_SCENES = 100


class PostHocMonitoringPayload(ProtocolModel):
    trajectories: TrajectoriesData  # the state log to judge
    colregs_constraints_content: Optional[str] = None  # COLREGS constants YAML; the general maritime defaults when None
    scenario_id: str = "post-hoc"  # scenarioId of the returned frames
    include_frames: bool = False  # add every monitored frame in the workbench's wire format
    timeout_s: float = Field(default=600.0, gt=0.0)


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(PostHocMonitoringPayload, job)
    return run_in_runner_container(job, node, report, Subsystem.MONITORING, timeout_s=payload.timeout_s, cancel=cancel)


def execute(job: JobSpec, status: StatusCallback) -> JobResultData:
    """The in-container part: monitor every scene in order and summarize the verdicts."""
    from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
    from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
    from scenegems_tool.gateway.serialization import serialize_monitored_frame
    from utils.colregs_approximations import COLREGSConstraints

    payload = PostHocMonitoringPayload.model_validate(job.payload)
    trajectories = to_trajectories(payload.trajectories)
    constants = COLREGSConstraints.from_file_content(payload.colregs_constraints_content) if payload.colregs_constraints_content else COLREGSConstraints.default_general_maritime()
    runtime = ColregsMonitorRuntime(constants)
    time_step = trajectories.time_step
    scene_count = len(trajectories.scene_list)

    first_outcomes: Dict[str, Dict[str, Dict[str, int]]] = {}  # relation, rule, outcome: first timestamp
    frames = []
    monitored = 0
    for index, scene in enumerate(trajectories.scene_list):
        runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=index * time_step, time_step=time_step))
        for monitored_scene in runtime.monitor_current_tasks():
            monitored += 1
            for relation, result_map in monitored_scene.monitor_result_map_set.items():
                rules = first_outcomes.setdefault(str(relation), {})
                for rule, outcome in result_map.items():
                    if outcome != COLREGSRuleResult.UNKNOWN:
                        rules.setdefault(str(rule), {}).setdefault(outcome.name.lower(), monitored_scene.timestamp)
            if payload.include_frames:
                frames.append(serialize_monitored_frame(scenario_id=payload.scenario_id, monitored_scene=monitored_scene, timestamp=monitored_scene.timestamp, time_step=time_step))
        if (index + 1) % _PROGRESS_EVERY_SCENES == 0:
            status(f"monitored {index + 1} of {scene_count} scenes", (index + 1) / scene_count)

    failed = sorted(
        ({"relation": relation, "rule": rule, "first_failed_at": outcomes["failed"]} for relation, rules in first_outcomes.items() for rule, outcomes in rules.items() if "failed" in outcomes),
        key=lambda item: (item["first_failed_at"], item["relation"], item["rule"]),
    )
    data: Dict[str, Any] = {
        "scenes": scene_count,
        "monitored_scenes": monitored,
        "time_step": time_step,
        "rules": first_outcomes,
        "failed_rules": failed,
        "passed": not failed,
    }
    if payload.include_frames:
        data["frames"] = frames
    return data
