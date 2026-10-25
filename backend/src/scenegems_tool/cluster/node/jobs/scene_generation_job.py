"""scene_generation: one concrete scene from a functional scenario, by the node's scene generation pool.

The job is dispatched to the pooled scenario generation service over the pool's scoped
topics with today's generate-scene task, so the daemon only relays it. The pool runs as
many generations at once as the node has scene_generation slots.
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
from scenegems_tool.subsystems.scene_generation.scenario_generation_types import SCENARIO_GENERATION_SERVICE_NAME, SCENARIO_GENERATION_SERVICE_TOPIC

REPLY_MARGIN_S = 60.0  # time beyond the generation timeout for the worker to start and the reply to arrive


class SceneGenerationPayload(ProtocolModel):
    functional_scenario_content: str
    colregs_constraints_content: str  # COLREGS constants YAML
    vessel_types_content: str  # vessel types YAML
    obstacle_types_content: str  # static obstacle types YAML
    timeout_s: int = Field(default=60, gt=0)  # the generation's own time limit
    enforce_low_tcpa: bool = False

    @field_validator("functional_scenario_content")
    @classmethod
    def _parses(cls, content: str) -> str:
        from functional_level.models.model_parser import ModelParser

        try:
            ModelParser.parse_problem(content)
        except Exception as error:
            raise ValueError(f"the functional scenario does not parse ({error})") from error
        return content


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    from scenegems_tool.messaging.mqtt_scenario_generation_client import MqttScenarioGenerationClient

    payload = parse_payload(SceneGenerationPayload, job)
    request_id = f"{job.job_id}-{job.attempt}"  # an earlier attempt's late reply is never taken for this one
    reply: Dict[str, Any] = {}
    replied = threading.Event()

    def on_generated_scene(scene_request_id: str, scene, evaluation_data: Dict[str, Any], valid: bool) -> None:
        if scene_request_id == request_id:
            reply.update(valid=valid, evaluation_data=evaluation_data)
            replied.set()

    def on_unmonitored_scene(message: Dict[str, Any]) -> None:
        # The client forwards a scene it could not rebuild as a workbench message.
        if message.get("type") == "generated_scene" and message.get("requestId") == request_id:
            reply.update(valid=bool(message["valid"]), evaluation_data=message["evaluationData"])
            replied.set()

    pool = node.pools.get(Subsystem.SCENE_GENERATION)
    client = MqttScenarioGenerationClient(
        mqtt_connection=pool.mqtt_connection,
        topic=SCENARIO_GENERATION_SERVICE_TOPIC,
        reference_geofence=node.reference_geofence,
        parent_service_name=SCENARIO_GENERATION_SERVICE_NAME,
        send_payload=on_unmonitored_scene,
        on_generated_scene=on_generated_scene,
    )
    try:
        client.connect()
    except RuntimeError as error:
        raise JobFailed(str(error), retryable=True) from error
    try:
        wait_for_pool(lambda: client.is_connected and client.is_heartbeat_valid, report, "scene generation pool", cancel)
        client.publish_generate_scene_command(
            request_id,
            payload.functional_scenario_content,
            payload.colregs_constraints_content,
            payload.vessel_types_content,
            payload.obstacle_types_content,
            payload.timeout_s,
            payload.enforce_low_tcpa,
        )
        wait_for_reply(replied, report, "generated scene", cancel, payload.timeout_s + REPLY_MARGIN_S)
    finally:
        client.disconnect()
    return {"request_id": request_id, **reply}
