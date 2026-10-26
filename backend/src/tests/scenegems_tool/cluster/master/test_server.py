"""The master's listeners on real sockets: the node API over HTTPS and WSS with the master's certificate."""

import asyncio
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from websockets.asyncio.client import connect

from scenegems_tool.cluster.master.api.master_apps import create_master_apps
from scenegems_tool.cluster.master.server import MAX_NODE_FRAME_BYTES, build_assurance_stores, build_live_channel, listeners
from scenegems_tool.cluster.master.settings import BrokerClientSettings, Listener, MasterSettings
from scenegems_tool.cluster.protocol.codec import decode_master_message, encode
from scenegems_tool.cluster.protocol.jobs import JobSubmission
from scenegems_tool.cluster.protocol.messages import LeaseOffer, Welcome
from scenegems_tool.cluster.protocol.pairing import PairingRequest
from scenegems_tool.cluster.protocol.routes import AUTHORIZATION_HEADER, CA_CERTIFICATE_PATH, NODE_CONTROL_PATH, bearer
from scenegems_tool.cluster.security.certificates.certificate_pinning import certificate_sha256, matches_pinned_sha256
from scenegems_tool.cluster.security.credentials.pairing_tokens import create_pairing_token
from scenegems_tool.cluster.security.pairing import pair_node
from tests.scenegems_tool.cluster.master.conftest import EXPECTED, SCENE
from tests.scenegems_tool.cluster.security.conftest import HOOK_SECRET, make_master_security
from tests.scenegems_tool.persistence.stores.builders import make_hello


def _settings(security_dir: Path) -> MasterSettings:
    return MasterSettings(
        security_dir=security_dir,
        database_url="postgresql://unused",
        broker_hook_secret=HOOK_SECRET,
        node_api=Listener("127.0.0.1", 0),
        operator=Listener("127.0.0.1", 0),
        broker_hook=Listener("127.0.0.1", 0),
    )


def test_listeners_use_the_api_certificate_and_their_hosts(plane, security):
    apps = create_master_apps(plane, security, HOOK_SECRET)
    node_api, operator, hook = listeners(_settings(security.layout.root), apps)
    assert node_api.config.ssl_certfile == str(security.layout.api_certificate) and node_api.config.ssl_keyfile == str(security.layout.api_key)
    assert operator.config.ssl_certfile is None and hook.config.ssl_certfile is None
    assert operator.config.ws_ping_interval is None and node_api.config.ws_max_size == MAX_NODE_FRAME_BYTES == 64 * 1024 * 1024
    assert (node_api.config.app, operator.config.app, hook.config.app) == (apps.node_api, apps.operator, apps.broker_hook)


@pytest.fixture
def https_node_api(plane, security):
    """The node API on a real HTTPS socket; yields its base address without the scheme."""
    server = listeners(_settings(security.layout.root), create_master_apps(plane, security, HOOK_SECRET, run_timers=True))[0]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    started = threading.Event()
    for _ in range(200):  # until uvicorn has bound its socket
        if server.started:
            started.set()
            break
        started.wait(0.05)
    assert server.started, "the node API did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_a_new_node_pins_the_ca_then_pairs_and_connects_over_tls(https_node_api, security, stores):
    # Bootstrap: an unverified fetch of the CA certificate, checked against the hash the token command printed
    unverified = ssl.create_default_context()
    unverified.check_hostname, unverified.verify_mode = False, ssl.CERT_NONE
    pem = urllib.request.urlopen(f"https://{https_node_api}{CA_CERTIFICATE_PATH}", context=unverified, timeout=10).read().decode("ascii")
    assert matches_pinned_sha256(pem, certificate_sha256(security.ca_certificate_pem))

    # From then on every connection is verified against that CA, host name included
    trusted = ssl.create_default_context(cadata=pem)
    assert urllib.request.urlopen(f"https://{https_node_api}{CA_CERTIFICATE_PATH}", context=trusted, timeout=10).read().decode("ascii") == pem

    paired = pair_node(security, PairingRequest(token=create_pairing_token(security.store).token, node_name="tls node"))
    job = stores.jobs.submit(JobSubmission(job_type=SCENE)).job  # queued before the node connects, so its Hello triggers the offer

    # The asyncio client, as the node daemon uses: the threading client stalls on TLS 1.3 under Windows (design doc 13.8.4)
    async def node_session():
        async with connect(f"wss://{https_node_api}{NODE_CONTROL_PATH}", ssl=trusted, additional_headers={AUTHORIZATION_HEADER: bearer(paired.node_credential)}, open_timeout=10) as socket:
            await socket.send(encode(make_hello(paired.node_id, slots={SCENE: 1}, fingerprints=dict(EXPECTED))))
            return [decode_master_message(await asyncio.wait_for(socket.recv(), 10)) for _ in range(2)]

    welcome, offer = asyncio.run(node_session())
    assert isinstance(welcome, Welcome) and isinstance(offer, LeaseOffer) and offer.job.job_id == job.job_id


def test_a_client_that_trusts_another_ca_is_refused(https_node_api, tmp_path):
    other = make_master_security(tmp_path / "other-master")
    with pytest.raises(urllib.error.URLError, match="CERTIFICATE_VERIFY_FAILED"):
        urllib.request.urlopen(f"https://{https_node_api}{CA_CERTIFICATE_PATH}", context=ssl.create_default_context(cadata=other.ca_certificate_pem), timeout=10)


def test_the_master_has_one_assurance_stores_shared_with_its_pipeline_engine(plane):
    from sqlalchemy.orm import sessionmaker

    sessions = sessionmaker()
    stores = build_assurance_stores(sessions)
    plane.attach_pipeline(stores)
    assert stores.session_factory is sessions and plane.pipeline.stores is stores


def test_the_live_channel_observes_pools_with_the_masters_broker_login(plane, security):
    without = build_live_channel(_settings(security.layout.root), security, plane, None)
    assert not without.producers.hub.broker_configured
    settings = _settings(security.layout.root)
    settings = MasterSettings(**{**settings.__dict__, "broker": BrokerClientSettings("cluster-broker", 8883, "", "broker-secret-0123456789")})
    channel = build_live_channel(settings, security, plane, None)
    hub = channel.producers.hub
    assert hub.broker_configured
    client = hub._broker_factory()
    assert (client.host, client.port, client._username) == ("cluster-broker", 8883, security.identity.master_broker_username)
    assert client._ca_certificate == str(security.layout.ca_certificate)
