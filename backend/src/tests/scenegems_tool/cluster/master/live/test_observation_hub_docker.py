"""The observation hub on a real cluster broker (NanoMQ in Docker, -m docker): a pool's preview reaches the browser.

The broker is the image the master's compose file runs, unchanged: plain MQTT, anonymous, on
the VPN. The hub connects to it as master-api does on the compose network; the test plays the pool
and publishes under the node's topic scope. The image comes from SCENEGEMS_BROKER_IMAGE
(default scenegems-mqtt-broker:latest).
"""

import json
import os
import socket
import subprocess
import time
import uuid

import anyio
import paho.mqtt.client as mqtt
import pytest

from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.live.observation_hub import GENERATED_SCENE_TOPIC, paho_broker
from scenegems_tool.cluster.master.live.topics import create_live_channel
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.node.instance_scope import node_topic_scope
from scenegems_tool.cluster.protocol.live import instance_topic
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryJobStore, InMemoryNodeStore
from tests.scenegems_tool.cluster.master.live.conftest import Browser
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello

pytestmark = [pytest.mark.docker, pytest.mark.anyio]

BROKER_IMAGE = os.environ.get("SCENEGEMS_BROKER_IMAGE", "scenegems-mqtt-broker:latest")
MASTER_ID = "lab-master"
NODE_ID = "lab-node-1"
POOL = "scene_generation-0"
TIMEOUT_S = 10.0


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, check=check, timeout=120)


@pytest.fixture(scope="module")
def broker_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    name = f"scenegems-test-cluster-broker-{uuid.uuid4().hex[:8]}"
    _docker("run", "-d", "--rm", "--name", name, "--tmpfs", "/data/broker", "-p", f"127.0.0.1:{port}:1883", BROKER_IMAGE)  # the image logs to /data/broker, a volume in compose
    try:
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("the broker did not open its port")
        yield port
    finally:
        _docker("rm", "-f", name, check=False)


async def test_a_pools_scene_sample_reaches_the_observer_through_the_broker(broker_port):
    clock = ManualClock()
    nodes = InMemoryNodeStore(clock)
    nodes.register(make_hello(NODE_ID))
    plane = ControlPlane(MASTER_ID, nodes, InMemoryJobStore(nodes, clock), ExpectedFingerprints.fixed({}), clock=clock)
    channel = create_live_channel(plane, broker=paho_broker("127.0.0.1", broker_port))
    browser = Browser(channel)
    browser.socket.subscribe(instance_topic(NODE_ID, POOL))
    (subscribed,) = await browser.messages(1)
    assert subscribed["type"] == "subscribed" and subscribed["snapshot"]["kind"] == "scene_generation"

    pool = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"pool-{uuid.uuid4().hex[:8]}")  # anonymous, as every node on the VPN
    pool.connect("127.0.0.1", broker_port, keepalive=30)
    pool.loop_start()
    sample = {"request-id": "r1", "valid": True, "final": True, "generated-frame": {"scenarioId": "r1"}, "evaluation-data": {"best_fitness": [0.1]}}
    try:
        deadline = time.monotonic() + TIMEOUT_S
        while not browser.socket.sent:  # the hub's subscription becomes active once its connection is up
            assert time.monotonic() < deadline, "the sample never reached the browser"
            pool.publish(f"{node_topic_scope(MASTER_ID, NODE_ID)}{POOL}/{GENERATED_SCENE_TOPIC}", json.dumps(sample), qos=1)
            await anyio.sleep(0.2)
        update = (await browser.messages(1))[0]
        assert update["type"] == "update" and update["data"]["kind"] == "scene_sample" and update["data"]["request_id"] == "r1" and update["data"]["final"] is True
    finally:
        pool.loop_stop()
        pool.disconnect()
        await browser.leave()
        await channel.close()
