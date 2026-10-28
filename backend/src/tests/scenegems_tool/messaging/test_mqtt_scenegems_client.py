"""The SceneGEMS client only subscribes."""

from types import SimpleNamespace

from scenegems_tool.messaging.mqtt_scenegems_client import MqttSceneGEMSClient
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline

TOPIC = "waraps/service/virtual/real/scenegems_service"


def test_the_client_listens_for_feedback_and_responses():
    client = MqttSceneGEMSClient(CONNECTION, TOPIC, GEOFENCE)
    assert client.name == "scenegems_client"
    assert client.listen_topics == [f"{TOPIC}/exec/feedback", f"{TOPIC}/exec/response"]


def test_messages_are_taken_without_effect_but_feedback_still_tracks_running_tasks():
    client = offline(MqttSceneGEMSClient(CONNECTION, TOPIC, GEOFENCE))
    deliver(client, client.exec_feedback_topic, {"status": "running", "task-uuid": "t1"})
    assert client.running_tasks == set()  # _on_message alone does not track
    for status, expected in (("running", {"t1"}), ("finished", set())):
        message = SimpleNamespace(topic=client.exec_feedback_topic, payload=f'{{"status": "{status}", "task-uuid": "t1"}}'.encode())
        client.on_message(None, None, message)
        assert client.running_tasks == expected
    assert client.client.published == []
