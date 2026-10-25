"""Trajectory generation over MQTT: the seed in the command and the task, complete in the result."""

from scenegems_tool.messaging.mqtt_trajectory_generation_client import MqttTrajectoryGenerationClient
from scenegems_tool.messaging.mqtt_trajectory_generation_service import MqttTrajectoryGenerationService
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import (
    TRAJECTORY_GENERATION_SERVICE_NAME,
    TRAJECTORY_GENERATION_SERVICE_TOPIC,
    MqttTrajectoryGenerationTask,
    TrajectoryGenerationParams,
    TrajectoryGeneratorId,
)
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline


def _client(sent=None, **handlers):
    return offline(
        MqttTrajectoryGenerationClient(
            CONNECTION, TRAJECTORY_GENERATION_SERVICE_TOPIC, GEOFENCE, TRAJECTORY_GENERATION_SERVICE_NAME, send_payload=(sent.append if sent is not None else lambda message: None), **handlers
        )
    )


def _command(client, **options):
    client.publish_generate_trajectories_command("r1", "{}", "colregs", TrajectoryGenerationParams(generator=TrajectoryGeneratorId.STRAIGHT, timespan=60.0), **options)
    [(_, command)] = client.client.published
    return command


def test_the_seed_and_the_generator_are_in_the_command():
    params = _command(_client(), seed=5)["task"]["params"]
    assert params["seed"] == 5 and params["params"]["generator"] == "straight" and params["params"]["timespan"] == 60.0
    assert "seed" not in _command(_client())["task"]["params"]


def test_the_service_puts_the_seed_and_the_generator_into_the_task():
    service = MqttTrajectoryGenerationService(CONNECTION, GEOFENCE, max_workers=2)
    deliver(service, service.exec_command_topic, _command(_client(), seed=5))
    task = service.task_queue.get(timeout=5)
    assert task.seed == 5 and task.params.generator_id == TrajectoryGeneratorId.STRAIGHT and task.params.timespan == 60.0


def test_the_result_says_whether_the_plan_is_complete():
    service = offline(MqttTrajectoryGenerationService(CONNECTION, GEOFENCE))
    task = MqttTrajectoryGenerationTask(sender=service.name, task_uuid="u", request_id="r1", scenario_content="{}", colregs_constraints_content="", params=TrajectoryGenerationParams())
    service.publish_result(task, {"t": 1}, True, None, complete=False)
    [(_, message)] = service.client.published
    assert (message["valid"], message["complete"]) == (True, False)


def test_a_cluster_job_and_the_workbench_both_get_complete_when_the_service_sends_it():
    received, sent = [], []
    job_client = _client(on_result=lambda *args: received.append(args))
    workbench_client = _client(sent)
    result = {"task_sender": TRAJECTORY_GENERATION_SERVICE_NAME, "request-id": "r1", "trajectory-data": {"t": 1}, "valid": True, "error-message": None}
    for client in (job_client, workbench_client):
        deliver(client, client.planned_trajectory_topic, {**result, "complete": False})
        deliver(client, client.planned_trajectory_topic, result)  # a service from before the flag: complete means valid
    assert received == [("r1", {"t": 1}, True, False, None), ("r1", {"t": 1}, True, True, None)]
    assert sent[0] == {"type": "trajectory_generation_result", "requestId": "r1", "trajectoryData": {"t": 1}, "valid": True, "complete": False, "errorMessage": None}
    assert sent[1] == {"type": "trajectory_generation_result", "requestId": "r1", "trajectoryData": {"t": 1}, "valid": True, "errorMessage": None}  # no flag from the service, none in the message
