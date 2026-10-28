"""The monitor client sends monitoring commands, routes the monitored frames back and bounds its waits."""

import json
import time

import pytest

from scenegems_tool.messaging.mqtt_monitor_client import GENERATED_SCENE_SCENARIO_ID, MqttMonitorClient
from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline

AGENT = "colregs_monitor"
SERVICE = "workbench_service"
TOPIC = f"waraps/service/virtual/real/{AGENT}"


def _client(sent):
    return offline(MqttMonitorClient(CONNECTION, TOPIC, AGENT, GEOFENCE, SERVICE, send_payload=sent.append))


def _frames(count=2):
    return [{"scenarioId": "s1", "timestamp": index} for index in range(count)]


def _reply(**changes):
    reply = {"task_sender": AGENT, "task-uuid": "b1", "is-simulation-frame": False, "monitored-frames": _frames()}
    reply.update(changes)
    return reply


@pytest.fixture
def scene():
    return monitored_run((200.0, -200.0), 1)[0].scene


def test_the_client_listens_for_monitored_scenes_and_heartbeats():
    client = _client([])
    assert client.name == f"{AGENT}_client"
    assert client.listen_topics == [client.monitored_scene_topic, client.heartbeat_topic]


@pytest.mark.parametrize("simulation, kind", [(True, "simulation_trajectory_chunk"), (False, "preview_trajectory_chunk")])
def test_frames_are_sent_on_as_one_chunk(simulation, kind):
    sent = []
    client = _client(sent)
    deliver(client, client.monitored_scene_topic, _reply(**{"is-simulation-frame": simulation}))
    [message] = sent
    assert message["type"] == kind
    assert message["frames"] == _frames()


def test_a_single_frame_reply_is_a_chunk_of_one():
    sent = []
    client = _client(sent)
    reply = _reply(**{"monitored-frame": {"scenarioId": "s1", "timestamp": 3}})
    del reply["monitored-frames"]
    deliver(client, client.monitored_scene_topic, reply)
    assert [frame["timestamp"] for frame in sent[0]["frames"]] == [3]


def test_replies_of_other_senders_and_empty_replies_are_dropped():
    sent = []
    client = _client(sent)
    deliver(client, client.monitored_scene_topic, _reply(task_sender="other"))
    deliver(client, client.monitored_scene_topic, _reply(**{"monitored-frames": []}))
    assert sent == []


def test_a_heartbeat_clears_the_failed_waits_and_makes_the_client_valid(monkeypatch):
    client = _client([])
    client.last_heartbeat_timestamp = 0.0
    client._heartbeat_wait_failed = client._batch_wait_failed = True
    assert not client.is_heartbeat_valid
    monkeypatch.setattr(time, "time", lambda: 500.0)
    deliver(client, client.heartbeat_topic, {})
    assert client.is_heartbeat_valid and not client._heartbeat_wait_failed and not client._batch_wait_failed


def test_a_step_command_carries_the_scene_and_the_frame_kind(scene):
    client = _client([])
    client.publish_step_monitor_command("s1", scene, 7, 2, True)
    [(topic, command)] = client.client.published
    assert topic == client.exec_command_topic
    assert (command["task_sender"], command["execution-unit"], command["task"]["name"]) == (SERVICE, AGENT, "step-monitor")
    assert command["task"]["params"] == {"scenario-id": "s1", "scene": json.loads(json.dumps(scene.to_dict())), "scene-timestamp": 7, "time-step": 2, "is-simulation-frame": True}


def test_a_batch_command_waits_until_the_monitor_replies(scene):
    client = _client([])
    original = client._register_batch_wait
    registered = []

    def register(task_uuid):
        event = original(task_uuid)
        registered.append(task_uuid)
        event.set()  # the reply arrives while the client waits
        return event

    client._register_batch_wait = register
    client.publish_step_monitor_batch_command("s1", [scene, scene], [0, 1], 2, False)
    [(_, command)] = client.client.published
    params = command["task"]["params"]
    assert command["task"]["name"] == "step-monitor-batch" and command["task-uuid"] == registered[0]
    assert (params["scene-timestamps"], params["time-step"], len(params["scenes"])) == ([0, 1], 2, 2)


def test_a_reply_releases_the_batch_wait():
    client = _client([])
    event = client._register_batch_wait("b1")
    deliver(client, client.monitored_scene_topic, _reply())
    assert event.is_set() and client._pending_batch_events == {}


def test_a_reply_with_another_task_uuid_leaves_the_wait_pending():
    client = _client([])
    event = client._register_batch_wait("b1")
    deliver(client, client.monitored_scene_topic, _reply(**{"task-uuid": "other"}))
    assert not event.is_set()


def test_a_stopped_client_ends_the_batch_wait_with_an_error():
    client = _client([])
    event = client._register_batch_wait("b1")
    client._stop_wait.set()
    with pytest.raises(ValueError, match="did not return monitored frames"):
        client._await_batch_event(event, "b1")
    assert client._batch_wait_failed and client._pending_batch_events == {}


def test_a_failed_batch_wait_blocks_the_next_batch_command(scene):
    client = _client([])
    client._batch_wait_failed = True
    with pytest.raises(ValueError, match="did not return monitored frames"):
        client.publish_step_monitor_batch_command("s1", [scene], [0], 1, False)
    assert client.client.published == []


def test_generated_scene_goes_out_under_the_request_id_when_the_monitor_replies(scene):
    sent = []
    client = _client(sent)
    command_published = client.client.published
    evaluation = {"score": 1}
    # The reply is delivered as soon as the command is published, before the client polls for it.
    publish = client.client.publish

    def publish_and_reply(topic, payload, qos=0):
        publish(topic, payload, qos)
        deliver(client, client.monitored_scene_topic, _reply(**{"request-id": "r1", "monitored-frames": [{"scenarioId": GENERATED_SCENE_SCENARIO_ID, "timestamp": 0}]}))

    client.client.publish = publish_and_reply
    client.publish_monitor_generated_scene_command("r1", scene, evaluation, True)
    [(_, command)] = command_published
    assert command["task"]["params"]["scenario-id"] == GENERATED_SCENE_SCENARIO_ID and command["task"]["params"]["request-id"] == "r1"
    [message] = sent
    assert message["type"] == "generated_scene" and message["requestId"] == "r1"
    assert message["scene"]["scenarioId"] == "r1" and message["valid"] is True and message["evaluationData"] == evaluation
    assert client._pending_generated_scenes == {}


def test_a_generated_scene_reply_nobody_waits_for_is_dropped():
    sent = []
    client = _client(sent)
    deliver(client, client.monitored_scene_topic, _reply(**{"request-id": "unknown"}))
    assert sent == []


def test_waiting_for_a_generated_scene_that_never_comes_back_fails(monkeypatch):
    client = _client([])
    client.timeout_sec = -1.0
    client._pending_generated_scenes["r1"] = ({}, True)
    with pytest.raises(ValueError, match="generated scene r1"):
        client._wait_for_generated_scene_reply("r1")
    assert client._pending_generated_scenes == {}


def test_waiting_for_the_heartbeat_fails_once_then_fails_fast(monkeypatch):
    client = _client([])
    client.last_heartbeat_timestamp = 0.0
    client.startup_timeout_sec = -1.0
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    with pytest.raises(ValueError, match="monitor service"):
        client.wait_for_heartbeat()
    assert client._heartbeat_wait_failed
    with pytest.raises(ValueError, match="monitor service"):
        client.wait_for_heartbeat()


def test_disconnect_stops_pending_waits():
    client = _client([])
    client.client.disconnect = lambda: None
    client.last_heartbeat_timestamp = 0.0
    client.disconnect()
    with pytest.raises(ValueError, match="disconnected"):
        client.wait_for_heartbeat()
