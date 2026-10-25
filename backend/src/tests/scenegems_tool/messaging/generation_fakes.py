"""Generation clients and services without a broker: published messages are recorded, received ones injected."""

import json
import time
from types import SimpleNamespace

from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence

CONNECTION = MQttConnectionInfo("", "", "broker", "broker", 1883, False, False)
GEOFENCE = Geofence(57.7, 11.9, 2000.0)


class RecordingPaho:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, json.loads(payload)))

    def is_connected(self):
        return True


def offline(client):
    """The client as if connected and heartbeating, publishing into a recorder."""
    client.client = RecordingPaho()
    client.connected_event.set()
    if hasattr(client, "last_heartbeat_timestamp"):
        client.last_heartbeat_timestamp = time.time()
    return client


def deliver(client, topic, payload):
    client._on_message(SimpleNamespace(topic=topic), payload)
