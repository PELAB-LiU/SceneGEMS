"""The cluster broker in a real NanoMQ container, configured by initialize_master_security.

The master's auth hook runs in this process (uvicorn in a thread); the broker container
reaches it as host.docker.internal. Two nodes are paired through pair_node, so the test
covers the whole path from pairing token to broker access. Run with `-m docker`; the
broker image comes from SCENEGEMS_BROKER_IMAGE (default scenegems-mqtt-broker:latest).
"""

import os
import socket
import ssl
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

import paho.mqtt.client as mqtt
import pytest
import uvicorn

from scenegems_tool.cluster.protocol.pairing import PairingRequest, PairingResponse
from scenegems_tool.cluster.security.broker.auth_hook import AUTH_HOOK_PATH, create_broker_auth_app
from scenegems_tool.cluster.security.broker.broker_config import BROKER_CONFIG_MOUNT, CONFIG_FILE_NAME, TLS_PORT
from scenegems_tool.cluster.security.certificates.certificate_authority import CertificateAuthority
from scenegems_tool.cluster.security.credentials.broker_accounts import remove_broker_account
from scenegems_tool.cluster.security.credentials.pairing_tokens import create_pairing_token
from scenegems_tool.cluster.security.pairing import pair_node
from tests.scenegems_tool.cluster.security.conftest import HOOK_SECRET, MASTER_ID, MASTER_PASSWORD, MASTER_USERNAME, make_master_security

pytestmark = pytest.mark.docker

BROKER_IMAGE = os.environ.get("SCENEGEMS_BROKER_IMAGE", "scenegems-mqtt-broker:latest")
TIMEOUT_S = 10.0
# Extra wait for a message that must not arrive, after the positive control has arrived.
QUIET_S = 1.0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, check=check, timeout=120)


@dataclass
class Probe:
    """A paho client that records what the broker answered."""

    client: mqtt.Client
    connected: threading.Event = field(default_factory=threading.Event)
    closed: threading.Event = field(default_factory=threading.Event)
    reason: Optional[str] = None
    granted: dict = field(default_factory=dict)
    subscribed: dict = field(default_factory=dict)
    messages: List[tuple] = field(default_factory=list)
    message_arrived: threading.Condition = field(default_factory=threading.Condition)

    def subscribe(self, topic_filter: str) -> bool:
        """Whether the broker granted the subscription."""
        _, mid = self.client.subscribe(topic_filter, qos=1)
        event = self.subscribed.setdefault(mid, threading.Event())
        assert event.wait(TIMEOUT_S), f"no SUBACK for {topic_filter}"
        return self.granted[mid]

    def wait_for(self, topic: str) -> bytes:
        with self.message_arrived:
            assert self.message_arrived.wait_for(lambda: any(t == topic for t, _ in self.messages), TIMEOUT_S), f"nothing on {topic}"
        return next(payload for t, payload in self.messages if t == topic)

    def topics(self) -> List[str]:
        return [topic for topic, _ in self.messages]

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()


def _open(port: int, ca_path: Optional[str], username: Optional[str] = None, password: Optional[str] = None, *, tls: bool = True) -> Probe:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"probe-{uuid.uuid4().hex[:8]}")
    client.reconnect_delay_set(min_delay=30, max_delay=30)
    probe = Probe(client)

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            probe.reason = str(reason_code)
            probe.closed.set()
        else:
            probe.connected.set()

    def on_disconnect(_client, _userdata, _flags, reason_code, _properties):
        probe.reason = probe.reason or str(reason_code)
        probe.closed.set()

    def on_subscribe(_client, _userdata, mid, reason_codes, _properties):
        probe.granted[mid] = not reason_codes[0].is_failure
        probe.subscribed.setdefault(mid, threading.Event()).set()

    def on_message(_client, _userdata, message):
        with probe.message_arrived:
            probe.messages.append((message.topic, message.payload))
            probe.message_arrived.notify_all()

    client.on_connect, client.on_disconnect, client.on_subscribe, client.on_message = on_connect, on_disconnect, on_subscribe, on_message
    if username is not None:
        client.username_pw_set(username, password)
    if tls:
        client.tls_set(ca_certs=ca_path, cert_reqs=ssl.CERT_REQUIRED)
    try:
        client.connect("127.0.0.1", port, keepalive=30)
    except (OSError, ssl.SSLError) as exc:
        probe.reason = f"{exc.__class__.__name__}: {exc}"
        probe.closed.set()
        return probe
    client.loop_start()
    probe.connected.wait(TIMEOUT_S) or probe.closed.wait(TIMEOUT_S)
    return probe


def _refused(probe: Probe) -> bool:
    if not probe.connected.is_set():
        probe.closed.wait(TIMEOUT_S)
    refused = not probe.connected.is_set() and probe.closed.is_set()
    probe.close()
    return refused


@dataclass
class Cluster:
    port: int
    ca_path: str
    node_a: PairingResponse
    node_b: PairingResponse
    security: object

    def node(self, response: PairingResponse) -> Probe:
        probe = _open(self.port, self.ca_path, response.broker.username, response.broker.password)
        assert probe.connected.is_set(), f"node {response.node_id} could not connect: {probe.reason}"
        return probe

    def master(self) -> Probe:
        probe = _open(self.port, self.ca_path, MASTER_USERNAME, MASTER_PASSWORD)
        assert probe.connected.is_set(), f"master could not connect: {probe.reason}"
        return probe


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    if _docker("info", check=False).returncode != 0:
        pytest.skip("Docker engine is not reachable")
    if _docker("image", "inspect", BROKER_IMAGE, check=False).returncode != 0:
        pytest.fail(f"Broker image {BROKER_IMAGE} is missing; build it with ./build.sh --stack")

    hook_port = _free_port()
    security = make_master_security(
        tmp_path_factory.mktemp("security"),
        hook_url=f"http://host.docker.internal:{hook_port}{AUTH_HOOK_PATH}",
        addresses=("127.0.0.1",),
    )
    # Bound to every interface because on Linux the container reaches the host through the
    # Docker bridge, not the loopback.
    server = uvicorn.Server(uvicorn.Config(create_broker_auth_app(security.store, HOOK_SECRET), host="0.0.0.0", port=hook_port, log_level="warning"))
    hook_thread = threading.Thread(target=server.run, daemon=True)
    hook_thread.start()

    broker_port = _free_port()
    container = f"scenegems-test-cluster-broker-{uuid.uuid4().hex[:8]}"
    _docker(
        "run",
        "-d",
        "--name",
        container,
        "--add-host",
        "host.docker.internal:host-gateway",
        "-p",
        f"127.0.0.1:{broker_port}:{TLS_PORT}",
        "-v",
        f"{security.layout.broker_folder.resolve().as_posix()}:{BROKER_CONFIG_MOUNT}:ro",
        BROKER_IMAGE,
        "nanomq",
        "start",
        "--conf",
        f"{BROKER_CONFIG_MOUNT}/{CONFIG_FILE_NAME}",
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            probe = _open(broker_port, str(security.layout.ca_certificate), MASTER_USERNAME, MASTER_PASSWORD)
            ready = probe.connected.is_set()
            probe.close()
            if ready:
                break
            if time.monotonic() > deadline:
                pytest.fail(f"cluster broker did not accept the master: {probe.reason}\n{_docker('logs', container, check=False).stdout[-3000:]}")
            time.sleep(0.5)

        def paired(name):
            token = create_pairing_token(security.store).token
            return pair_node(security, PairingRequest(token=token, node_name=name))

        node_a, node_b = paired("node a"), paired("node b")
        ca_path = security.layout.root / "node_ca_certificate.pem"
        ca_path.write_text(node_a.ca_certificate_pem)  # what a node stores from its pairing response
        yield Cluster(port=broker_port, ca_path=str(ca_path), node_a=node_a, node_b=node_b, security=security)
    finally:
        _docker("rm", "-f", container, check=False)
        server.should_exit = True
        hook_thread.join(timeout=10)


def test_client_without_credentials_is_refused(cluster):
    assert _refused(_open(cluster.port, cluster.ca_path))


def test_wrong_password_is_refused(cluster):
    assert _refused(_open(cluster.port, cluster.ca_path, cluster.node_a.broker.username, cluster.node_a.broker.password + "x"))


def test_one_nodes_password_does_not_open_another_nodes_account(cluster):
    assert _refused(_open(cluster.port, cluster.ca_path, cluster.node_b.broker.username, cluster.node_a.broker.password))


def test_plain_mqtt_is_not_served(cluster):
    assert _refused(_open(cluster.port, None, cluster.node_a.broker.username, cluster.node_a.broker.password, tls=False))


def test_client_refuses_a_broker_signed_by_another_ca(cluster, tmp_path):
    stranger = tmp_path / "other_ca.pem"
    stranger.write_bytes(CertificateAuthority.create("other-master").certificate_pem)
    probe = _open(cluster.port, str(stranger), cluster.node_a.broker.username, cluster.node_a.broker.password)
    assert _refused(probe)
    assert "certificate verify failed" in (probe.reason or "")


def test_node_uses_its_own_scope(cluster):
    node_a, master = cluster.node(cluster.node_a), cluster.master()
    try:
        scope = cluster.node_a.broker.topic_scope
        assert node_a.subscribe(f"{scope}/#")
        assert master.subscribe(f"scenegems/{MASTER_ID}/#")
        node_a.client.publish(f"{scope}/scene_generation-0/heartbeat", b"alive", qos=1).wait_for_publish(TIMEOUT_S)
        assert node_a.wait_for(f"{scope}/scene_generation-0/heartbeat") == b"alive"
        assert master.wait_for(f"{scope}/scene_generation-0/heartbeat") == b"alive"
    finally:
        node_a.close()
        master.close()


@pytest.mark.parametrize(
    "topic_filter",
    ["{b_scope}/#", "{b_scope}/scene_generation-0/heartbeat", "scenegems/{master_id}/+/#", "scenegems/{master_id}/#", "scenegems/#", "#", "$SYS/#", "waraps/#"],
)
def test_node_cannot_subscribe_outside_its_scope(cluster, topic_filter):
    node_a = cluster.node(cluster.node_a)
    try:
        assert not node_a.subscribe(topic_filter.format(b_scope=cluster.node_b.broker.topic_scope, master_id=MASTER_ID))
    finally:
        node_a.close()


@pytest.mark.parametrize("qos", [0, 1])
def test_node_cannot_publish_on_another_nodes_topics(cluster, qos):
    node_b, master = cluster.node(cluster.node_b), cluster.master()
    b_scope = cluster.node_b.broker.topic_scope
    command_topic = f"{b_scope}/scenario_execution-0/exec/command"
    try:
        assert node_b.subscribe(f"{b_scope}/#")
        assert master.subscribe(f"scenegems/{MASTER_ID}/#")
        for forbidden in [command_topic, f"scenegems/{MASTER_ID}/control", "waraps/service/virtual/real/x"]:
            node_a = cluster.node(cluster.node_a)
            node_a.client.publish(forbidden, b"from node a", qos=qos)
            # NanoMQ 0.25 answers a denied publish of any QoS by closing the publisher's connection.
            assert node_a.closed.wait(TIMEOUT_S), f"node a stayed connected after publishing on {forbidden}"
            node_a.close()
        # Positive control: node b's subscription works, and only the master's message reaches it.
        master.client.publish(command_topic, b"from master", qos=1).wait_for_publish(TIMEOUT_S)
        assert node_b.wait_for(command_topic) == b"from master"
        time.sleep(QUIET_S)
        assert node_b.messages == [(command_topic, b"from master")]
        assert b"from node a" not in [payload for _, payload in master.messages]
    finally:
        node_b.close()
        master.close()


def test_removed_account_cannot_connect_again(cluster):
    response = pair_node(cluster.security, PairingRequest(token=create_pairing_token(cluster.security.store).token, node_name="node c"))
    first = _open(cluster.port, cluster.ca_path, response.broker.username, response.broker.password)
    assert first.connected.is_set(), first.reason
    first.close()
    remove_broker_account(cluster.security.store, response.broker.username)
    assert _refused(_open(cluster.port, cluster.ca_path, response.broker.username, response.broker.password))
