"""MqttClient with an instance prefix: relative topic names in subsystem code, prefixed on the wire."""

from typing import Any, List

import paho.mqtt.client as mqtt
import pytest

from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo, mqtt_connection_from_environment, mqtt_container_environment
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence

PREFIX = "scenegems/m1/n1/scene_generation-0/"


def connection(topic_prefix: str = "") -> MQttConnectionInfo:
    return MQttConnectionInfo("user", "secret", "broker", "localhost", 1883, False, False, topic_prefix=topic_prefix)


class RecordingClient(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo):
        super().__init__("recording", "waraps/service/virtual/real/recording", mqtt_connection, Geofence(57.7, 11.9, 1000.0))
        self.received: List[Any] = []

    @property
    def listen_topics(self) -> List[str]:
        return [self.exec_command_topic]

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        self.received.append((msg.topic, payload))


def deliver(client: MqttClient, topic: str, payload: bytes) -> None:
    message = mqtt.MQTTMessage(topic=topic.encode())
    message.payload = payload
    client._on_scoped_message(client.client, None, message)


def test_incoming_topics_lose_the_prefix_before_the_subsystem_sees_them():
    client = RecordingClient(connection(PREFIX))
    deliver(client, PREFIX + client.exec_command_topic, b'{"command": "start-task"}')
    assert client.received == [(client.exec_command_topic, {"command": "start-task"})]


def test_messages_of_another_instance_are_ignored():
    client = RecordingClient(connection(PREFIX))
    deliver(client, "scenegems/m1/n2/scene_generation-0/" + client.exec_command_topic, b"{}")
    assert client.received == []


def test_the_workbench_client_has_no_prefix():
    client = RecordingClient(connection())
    assert client.topic_scope.is_empty
    deliver(client, client.exec_command_topic, b"{}")
    assert client.received == [(client.exec_command_topic, {})]


def test_subscriptions_on_connect_carry_the_prefix(monkeypatch):
    subscribed = []
    monkeypatch.setattr(mqtt.Client, "subscribe", lambda self, topic, *args: subscribed.append(topic))
    client = RecordingClient(connection(PREFIX))
    client.on_connect(client.client, None, {}, 0)
    assert subscribed == [PREFIX + client.exec_command_topic]


def test_with_topic_prefix_keeps_every_connection_setting():
    scoped = connection().with_topic_prefix(PREFIX)
    assert (scoped.user, scoped.password, scoped.agent_broker, scoped.client_broker, scoped.port) == ("user", "secret", "broker", "localhost", 1883)
    assert scoped.topic_prefix == PREFIX


def test_container_environment_of_the_workbench_has_no_prefix_variable():
    assert mqtt_container_environment(connection()) == {
        "MQTT_USER": "user",
        "MQTT_PASSWORD": "secret",
        "MQTT_BROKER": "broker",
        "MQTT_PORT": "1883",
        "MQTT_TLS": "0",
        "MQTT_ALLOW_CERTIFICATES": "0",
    }


@pytest.mark.parametrize("topic_prefix", ["", PREFIX])
def test_container_environment_round_trips(monkeypatch, topic_prefix):
    for name, value in mqtt_container_environment(connection(topic_prefix)).items():
        monkeypatch.setenv(name, value)
    if not topic_prefix:
        monkeypatch.delenv("MQTT_TOPIC_PREFIX", raising=False)
    restored = mqtt_connection_from_environment()
    # A container dials the agent broker.
    assert (restored.agent_broker, restored.client_broker, restored.port, restored.topic_prefix) == ("broker", "broker", 1883, topic_prefix)
    assert (restored.tls_connection, restored.allow_certificates) == (False, False)
