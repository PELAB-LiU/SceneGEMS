"""trajectory_generation: trajectories for a concrete scene, by the node's trajectory generation pool.

The job is dispatched to the pooled trajectory generation service over the pool's scoped
topics with today's generate-trajectories task. On a node the pool queues requests for its
workers (one per trajectory_generation slot) instead of superseding the running one.
"""

import threading
from typing import Any, Dict, Optional

from pydantic import Field, field_validator

from scenegems_tool.cluster.node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.node.jobs.pool_client import wait_for_pool, wait_for_reply
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import (
    TRAJECTORY_GENERATION_SERVICE_NAME,
    TRAJECTORY_GENERATION_SERVICE_TOPIC,
    TrajectoryGenerationParams,
)

# The keys TrajectoryGenerationParams.from_wire reads, as the workbench sends them.
PARAM_KEYS = frozenset(
    {"timeStep", "timeout", "maxIterations", "goalSampleRate", "bestLeafSampleRate", "maxLeafs", "directionThreshold", "bestRandomNodesK", "previewInterval", "includeMonitorResults"}
)


class TrajectoryGenerationPayload(ProtocolModel):
    scenario_content: str  # the generated scene as the workbench sends it (EvaluationData or scene JSON)
    colregs_constraints_content: str  # COLREGS constants YAML
    params: Dict[str, Any] = Field(default_factory=dict)  # TrajectoryGenerationParams in wire form; search defaults when empty
    timeout_s: float = Field(default=1800.0, gt=0.0)  # how long the job waits for the result

    @field_validator("params")
    @classmethod
    def _known_params(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        unknown = sorted(set(params) - PARAM_KEYS)
        if unknown:
            raise ValueError(f"unknown search parameters {unknown}")
        TrajectoryGenerationParams.from_wire(params)
        return params


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    from scenegems_tool.messaging.mqtt_trajectory_generation_client import MqttTrajectoryGenerationClient

    payload = parse_payload(TrajectoryGenerationPayload, job)
    request_id = f"{job.job_id}-{job.attempt}"
    reply: Dict[str, Any] = {}
    replied = threading.Event()
    previews = 0

    def on_message(message: Dict[str, Any]) -> None:
        nonlocal previews
        if message.get("requestId") != request_id:
            return
        if message.get("type") == "trajectory_generation_preview":
            previews += 1
            report.status(f"search preview {previews}")
        elif message.get("type") == "trajectory_generation_result":
            reply.update(valid=bool(message.get("valid")), trajectory_data=message.get("trajectoryData"), error_message=message.get("errorMessage"))
            replied.set()

    pool = node.pools.get(Subsystem.TRAJECTORY_GENERATION)
    client = MqttTrajectoryGenerationClient(
        mqtt_connection=pool.mqtt_connection,
        topic=TRAJECTORY_GENERATION_SERVICE_TOPIC,
        reference_geofence=node.reference_geofence,
        parent_service_name=TRAJECTORY_GENERATION_SERVICE_NAME,
        send_payload=on_message,
    )
    try:
        client.connect()
    except RuntimeError as error:
        raise JobFailed(str(error), retryable=True) from error
    try:
        wait_for_pool(lambda: client.is_connected and client.is_heartbeat_valid, report, "trajectory generation pool", cancel)
        client.publish_generate_trajectories_command(request_id, payload.scenario_content, payload.colregs_constraints_content, TrajectoryGenerationParams.from_wire(payload.params))
        wait_for_reply(replied, report, "trajectory generation result", cancel, payload.timeout_s)
    finally:
        client.disconnect()
    # A search that plans nothing is a result (valid false, with the reason), not a failed job.
    return {"request_id": request_id, **reply}
