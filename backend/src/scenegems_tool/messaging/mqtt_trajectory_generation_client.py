import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt

from scenegems_tool.gateway.protocol import ServerMessage, make_trajectory_generation_preview_message, make_trajectory_generation_result_message
from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TrajectoryGenerationParams
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

# (request_id, trajectory_data, valid, complete, error_message): the result as the service sent it.
TrajectoryResultHandler = Callable[[str, Optional[Dict[str, Any]], bool, bool, Optional[str]], None]


class MqttTrajectoryGenerationClient(MqttClient):
    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        topic: str,
        reference_geofence: Geofence,
        parent_service_name: str,
        send_payload: Callable[[ServerMessage], None],
        on_result: Optional[TrajectoryResultHandler] = None,
    ):
        super().__init__(name="trajectory_generation_client", topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.parent_service_name = parent_service_name
        self.send_payload = send_payload
        self.on_result = on_result  # when set, it gets the result instead of send_payload (cluster jobs); previews still go to send_payload
        self.last_heartbeat_timestamp = 0.0
        self.timeout_sec = 10.0
        self.heartbeat_interval_sec = 5.0

    @property
    def listen_topics(self) -> List[str]:
        return [
            self.planned_trajectory_topic,
            self.planned_trajectory_preview_topic,
            self.exec_feedback_topic,
            self.exec_response_topic,
            self.heartbeat_topic,
        ]

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        match msg.topic:
            case self.planned_trajectory_preview_topic:
                if payload["task_sender"] != self.parent_service_name:
                    return
                self.send_payload(
                    make_trajectory_generation_preview_message(
                        request_id=payload["request-id"],
                        trajectory_data=payload["trajectory-data"],
                    )
                )
            case self.planned_trajectory_topic:
                if payload["task_sender"] != self.parent_service_name:
                    return
                if self.on_result is not None:
                    valid = bool(payload.get("valid", False))
                    # A service from before the complete flag reported a partial path as valid.
                    self.on_result(payload["request-id"], payload.get("trajectory-data"), valid, bool(payload.get("complete", valid)), payload.get("error-message"))
                    return
                self.send_payload(
                    make_trajectory_generation_result_message(
                        request_id=payload["request-id"],
                        trajectory_data=payload.get("trajectory-data"),
                        valid=bool(payload.get("valid", False)),
                        error_message=payload.get("error-message"),
                        complete=bool(payload["complete"]) if "complete" in payload else None,
                    )
                )
            case self.heartbeat_topic:
                self.last_heartbeat_timestamp = time.time()

    @property
    def is_heartbeat_valid(self) -> bool:
        return time.time() - self.last_heartbeat_timestamp < self.heartbeat_interval_sec

    def wait_for_heartbeat(self) -> None:
        start_time = time.time()
        while not self.is_heartbeat_valid or not self.is_connected:
            time.sleep(0.1)
            if time.time() - start_time > self.timeout_sec:
                raise ValueError("Timeout: Failed to connect to trajectory generation service")

    def publish_generate_trajectories_command(
        self,
        request_id: str,
        scenario_content: str,
        colregs_constraints_content: str,
        params: TrajectoryGenerationParams,
        seed: Optional[int] = None,
    ):
        self.wait_for_heartbeat()
        command = {
            "stamp": time.time(),
            "task_sender": self.name,
            "task-uuid": str(uuid.uuid4()),
            "command": "start-task",
            "execution-unit": self.parent_service_name,
            "task": {
                "name": "generate-trajectories",
                "params": {
                    "request-id": request_id,
                    "scenario-content": scenario_content,
                    "colregs-constraints-content": colregs_constraints_content,
                    "params": params.to_wire(),
                    **({"seed": int(seed)} if seed is not None else {}),
                },
            },
        }
        self.client.publish(self.exec_command_topic, json.dumps(command), qos=1)

    def publish_cancel_command(self, request_id: str) -> Optional[mqtt.MQTTMessageInfo]:
        """Ask the pool to stop the search of this request only; the returned info confirms the publish."""
        command = {
            "stamp": time.time(),
            "task_sender": self.name,
            "task-uuid": str(uuid.uuid4()),
            "command": "signal-task",
            "execution-unit": self.parent_service_name,
            "signal": {"name": "cancel", "request-id": request_id},
        }
        return self.client.publish(self.exec_command_topic, json.dumps(command), qos=1)
