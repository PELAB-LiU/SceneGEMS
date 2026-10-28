"""The monitor service turns step-monitor commands into queued tasks and publishes the monitored frames."""

import pytest

from scenegems_tool.messaging.mqtt_monitor_service import MqttMonitoringBatchTask, MqttMonitoringTask, MqttMonitorService
from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline

NAME = "colregs_monitor"
TOPIC = f"waraps/service/virtual/real/{NAME}"


def _service():
    return offline(MqttMonitorService(CONNECTION, TOPIC, NAME, GEOFENCE))


def _scenes(count=2):
    return [result.scene for result in monitored_run((200.0, -200.0), count)]


def _command(name, params, **changes):
    command = {"execution-unit": NAME, "command": "start-task", "task-uuid": "u1", "task": {"name": name, "params": params}}
    command.update(changes)
    return command


def _step_params(scene):
    return {"scenario-id": "s1", "scene": scene.to_dict(), "scene-timestamp": 7, "time-step": 2, "is-simulation-frame": 1}


def _batch_params(scenes, **extra):
    return {"scenario-id": "s1", "scenes": [scene.to_dict() for scene in scenes], "scene-timestamps": list(range(len(scenes))), "time-step": 2, "is-simulation-frame": False, **extra}


def test_topics_follow_the_service_topic():
    service = _service()
    assert service.listen_topics == [service.exec_command_topic]
    assert service.base_topic == TOPIC
    assert service.monitored_scene_topic == f"{TOPIC}/sensor/monitored-scene"


def test_a_step_monitor_command_is_queued_as_a_task():
    service = _service()
    [scene] = _scenes(1)
    deliver(service, service.exec_command_topic, _command("step-monitor", _step_params(scene)))
    task = service.monitoring_task_queue.get_nowait()
    assert isinstance(task, MqttMonitoringTask)
    assert (task.sender, task.task_uuid, task.scenario_id, task.scene_timestamp, task.time_step, task.is_simulation_frame) == (NAME, "u1", "s1", 7, 2, True)
    assert task.scene.to_dict() == scene.to_dict()
    assert task.trajectory_id == f"{NAME}-s1-True"


def test_a_batch_command_is_queued_with_its_request_id():
    service = _service()
    scenes = _scenes(2)
    deliver(service, service.exec_command_topic, _command("step-monitor-batch", _batch_params(scenes, **{"request-id": "r1"})))
    deliver(service, service.exec_command_topic, _command("step-monitor-batch", _batch_params(scenes), **{"task-uuid": "u2"}))
    first, second = service.monitoring_task_queue.get_nowait(), service.monitoring_task_queue.get_nowait()
    assert isinstance(first, MqttMonitoringBatchTask)
    assert [scene.to_dict() for scene in first.scenes] == [scene.to_dict() for scene in scenes]
    assert (first.scene_timestamps, first.time_step, first.is_simulation_frame, first.request_id, first.trajectory_id) == ([0, 1], 2, False, "r1", f"{NAME}-s1-False")
    assert (second.task_uuid, second.request_id) == ("u2", None)


@pytest.mark.parametrize(
    "changes",
    [{"execution-unit": "other"}, {"command": "abort-task"}],
    ids=["other_unit", "other_command"],
)
def test_commands_for_others_are_ignored(changes):
    service = _service()
    [scene] = _scenes(1)
    deliver(service, service.exec_command_topic, _command("step-monitor", _step_params(scene), **changes))
    assert service.monitoring_task_queue.empty()


def test_an_unknown_task_name_is_ignored():
    service = _service()
    deliver(service, service.exec_command_topic, _command("something-else", {}))
    assert service.monitoring_task_queue.empty()


def test_ready_follows_connect_and_disconnect():
    service = _service()
    service.client.subscribe = lambda topic: None
    assert not service.is_ready
    service.on_connect(None, None, {}, 0)
    assert service.is_ready
    service.on_disconnect(None, None, 0)
    assert not service.is_ready


def test_a_monitored_scene_is_published_with_the_frame_and_the_task_identity():
    service = _service()
    result = monitored_run((200.0, -200.0), 1)[0]
    task = MqttMonitoringTask(NAME, "u1", "s1", result.scene, 7, 2, True)
    service.publish_monitored_scene(task, result)
    [(topic, message)] = service.client.published
    assert topic == service.monitored_scene_topic
    assert (message["task_sender"], message["task-uuid"], message["is-simulation-frame"]) == (NAME, "u1", True)
    assert (message["monitored-frame"]["scenarioId"], message["monitored-frame"]["timestamp"]) == ("s1", 7)


def test_a_batch_is_published_as_one_message_with_all_frames_and_the_request_id():
    service = _service()
    results = monitored_run((200.0, -200.0), 2)
    batch = MqttMonitoringBatchTask(NAME, "u1", "s1", [r.scene for r in results], [0, 1], 2, False, request_id="r1")
    tasks = [MqttMonitoringTask(NAME, "u1", "s1", r.scene, index, 2, False) for index, r in enumerate(results)]
    service.publish_monitored_scene_batch(batch, list(zip(tasks, results)))
    [(_, message)] = service.client.published
    assert [frame["timestamp"] for frame in message["monitored-frames"]] == [0, 1]
    assert (message["request-id"], message["task-uuid"], message["is-simulation-frame"]) == ("r1", "u1", False)


def test_an_empty_batch_publishes_nothing_and_no_request_id_means_no_key():
    service = _service()
    batch = MqttMonitoringBatchTask(NAME, "u1", "s1", [], [], 2, False)
    service.publish_monitored_scene_batch(batch, [])
    assert service.client.published == []
    result = monitored_run((200.0, -200.0), 1)[0]
    service.publish_monitored_scene_batch(batch, [(MqttMonitoringTask(NAME, "u1", "s1", result.scene, 0, 2, False), result)])
    assert "request-id" not in service.client.published[0][1]


def test_heartbeat_lists_the_running_tasks():
    service = _service()
    [scene] = _scenes(1)
    service.publish_heartbeat_and_sensor_info([MqttMonitoringTask(NAME, "u1", "s1", scene, 0, 1, False), MqttMonitoringTask(NAME, "u2", "s1", scene, 1, 1, False)])
    published = {topic: message for topic, message in service.client.published}
    assert published[service.heartbeat_topic]["agent-description"] == "COLREGS Monitor"
    assert published[service.sensor_info_topic]["sensor-data-provided"] == ["monitored-scene"]
    info = published[service.direct_execution_topic]
    assert info["tasks-available"] == [{"name": "step-monitor", "signals": []}]
    assert info["tasks-executing"] == [{"name": "step-monitor", "uuid": "u1"}, {"name": "step-monitor", "uuid": "u2"}]
