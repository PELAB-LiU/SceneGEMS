"""The observation hub on a real cluster broker (NanoMQ in Docker, -m docker): a pool's preview reaches the browser.

The broker, the master's login hook and two paired nodes come from the cluster broker's own
Docker fixture (cluster/security/broker/test_cluster_broker_docker.py). The hub logs in with
the master's account over TLS, as master-api does on the compose network.
"""

import json
import time

import anyio
import pytest

from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.live.observation_hub import GENERATED_SCENE_TOPIC, paho_broker
from scenegems_tool.cluster.master.live.topics import create_live_channel
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.live import instance_topic
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryJobStore, InMemoryNodeStore
from tests.scenegems_tool.cluster.master.live.conftest import Browser
from tests.scenegems_tool.cluster.security.broker.test_cluster_broker_docker import TIMEOUT_S, cluster  # noqa: F401 (the module fixture)
from tests.scenegems_tool.cluster.security.conftest import MASTER_ID, MASTER_PASSWORD, MASTER_USERNAME
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello

pytestmark = [pytest.mark.docker, pytest.mark.anyio]

POOL = "scene_generation-0"


async def test_a_pools_scene_sample_reaches_the_observer_through_the_broker(cluster):  # noqa: F811
    node_id = cluster.node_a.node_id
    clock = ManualClock()
    nodes = InMemoryNodeStore(clock)
    nodes.register(make_hello(node_id))
    plane = ControlPlane(MASTER_ID, nodes, InMemoryJobStore(nodes, clock), ExpectedFingerprints.fixed({}), clock=clock)
    broker = paho_broker("127.0.0.1", cluster.port, MASTER_USERNAME, MASTER_PASSWORD, str(cluster.security.layout.ca_certificate))
    channel = create_live_channel(plane, broker=broker)
    browser = Browser(channel)
    browser.socket.subscribe(instance_topic(node_id, POOL))
    (subscribed,) = await browser.messages(1)
    assert subscribed["type"] == "subscribed" and subscribed["snapshot"]["kind"] == "scene_generation"

    node = cluster.node(cluster.node_a)  # the pool publishes with its node's account, under its scope
    sample = {"request-id": "r1", "valid": True, "final": True, "generated-frame": {"scenarioId": "r1"}, "evaluation-data": {"best_fitness": [0.1]}}
    try:
        deadline = time.monotonic() + TIMEOUT_S
        while not browser.socket.sent:  # the hub's subscription becomes active once its connection is up
            assert time.monotonic() < deadline, "the sample never reached the browser"
            node.client.publish(f"{cluster.node_a.broker.topic_scope}/{POOL}/{GENERATED_SCENE_TOPIC}", json.dumps(sample), qos=1)
            await anyio.sleep(0.2)
        update = (await browser.messages(1))[0]
        assert update["type"] == "update" and update["data"]["kind"] == "scene_sample" and update["data"]["request_id"] == "r1" and update["data"]["final"] is True
    finally:
        node.close()
        await browser.leave()
        await channel.close()
