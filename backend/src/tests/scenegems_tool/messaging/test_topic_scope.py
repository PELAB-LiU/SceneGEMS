import paho.mqtt.client as mqtt
import pytest

from scenegems_tool.messaging.topic_scope import ScopedPahoClient, TopicScope

PREFIX = "scenegems/m1/n1/scene_generation-0/"
TOPIC = "waraps/service/virtual/real/scenario_generation_service/exec/command"


def test_apply_and_strip_are_inverse():
    scope = TopicScope(PREFIX)
    assert scope.apply(TOPIC) == PREFIX + TOPIC
    assert scope.strip(scope.apply(TOPIC)) == TOPIC


def test_strip_outside_the_scope_is_none():
    assert TopicScope(PREFIX).strip("scenegems/m1/n2/scene_generation-0/" + TOPIC) is None


def test_empty_scope_leaves_topics_unchanged():
    scope = TopicScope("")
    assert scope.is_empty
    assert scope.apply(TOPIC) == TOPIC
    assert scope.strip(TOPIC) == TOPIC


@pytest.mark.parametrize("prefix", ["scenegems/m1", "scenegems/+/n1/", "scenegems/#/", "/scenegems/m1/"])
def test_invalid_prefixes_are_rejected(prefix):
    with pytest.raises(ValueError):
        TopicScope(prefix)


def test_subscription_arguments_are_prefixed_in_every_paho_form():
    scope = TopicScope(PREFIX)
    assert scope.apply_subscription("a/+/b") == PREFIX + "a/+/b"
    assert scope.apply_subscription(("a/b", 1)) == (PREFIX + "a/b", 1)
    assert scope.apply_subscription([("a", 0), ("b", 1)]) == [(PREFIX + "a", 0), (PREFIX + "b", 1)]
    assert scope.apply_subscription(["a", "b"]) == [PREFIX + "a", PREFIX + "b"]


def test_strip_message_copies_the_message_under_the_relative_topic():
    message = mqtt.MQTTMessage(mid=7, topic=(PREFIX + TOPIC).encode())
    message.payload = b'{"a": 1}'
    message.qos = 1
    message.retain = True
    stripped = TopicScope(PREFIX).strip_message(message)
    assert stripped.topic == TOPIC
    assert (stripped.payload, stripped.qos, stripped.retain, stripped.mid) == (b'{"a": 1}', 1, True, 7)


def test_strip_message_drops_a_message_from_another_scope():
    message = mqtt.MQTTMessage(topic=("scenegems/m1/n2/x-0/" + TOPIC).encode())
    assert TopicScope(PREFIX).strip_message(message) is None


def test_strip_message_without_scope_returns_the_message_itself():
    message = mqtt.MQTTMessage(topic=TOPIC.encode())
    assert TopicScope("").strip_message(message) is message


def test_scoped_paho_client_prefixes_publish_subscribe_and_unsubscribe(monkeypatch):
    calls = []
    monkeypatch.setattr(mqtt.Client, "publish", lambda self, topic, *args: calls.append(("publish", topic)))
    monkeypatch.setattr(mqtt.Client, "subscribe", lambda self, topic, *args: calls.append(("subscribe", topic)))
    monkeypatch.setattr(mqtt.Client, "unsubscribe", lambda self, topic, *args: calls.append(("unsubscribe", topic)))
    client = ScopedPahoClient(TopicScope(PREFIX), mqtt.CallbackAPIVersion.VERSION1, client_id="test")
    client.publish(TOPIC, "{}", qos=1)
    client.subscribe(TOPIC)
    client.unsubscribe([TOPIC])
    assert calls == [("publish", PREFIX + TOPIC), ("subscribe", PREFIX + TOPIC), ("unsubscribe", [PREFIX + TOPIC])]
