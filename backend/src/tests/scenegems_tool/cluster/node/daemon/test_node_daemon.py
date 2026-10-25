"""The node daemon against a scripted master over TLS: pairing, hello, leases, reconnects and refusals.

Jobs are scripted (conftest.ScriptedJobs), so these tests need no Docker; the Docker test
in test_node_daemon_docker.py runs real job containers.
"""

import json
import time

import pytest

from scenegems_tool.cluster.node.daemon.node_daemon import DaemonStopped
from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import CaPinMismatch
from scenegems_tool.cluster.node.daemon.pairing.pairing_state import PairingState
from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import (
    Cancel,
    Drain,
    Heartbeat,
    Hello,
    JobResult,
    JobStatus,
    LeaseAccept,
    LeaseReject,
    LeaseRelease,
    LeaseRenew,
    LogLines,
    LogStream,
    ProtocolError,
    ProtocolErrorCode,
    Welcome,
)
from scenegems_tool.cluster.protocol.node_description import CapabilityOffer
from scenegems_tool.cluster.security.certificates.certificate_authority import CertificateAuthority
from scenegems_tool.cluster.security.credentials.node_credentials import revoke_node_credential
from tests.scenegems_tool.cluster.node.daemon.conftest import FINGERPRINTS, make_job, make_offer, wait_for

QUIET_S = 0.6  # how long a frame that must not come is waited for


def connect(fake_master, start_daemon, configuration, **options):
    daemon = start_daemon(configuration, **options)
    connection = fake_master.wait_for_connection()
    hello = connection.expect(Hello)
    wait_for(daemon.daemon.connected.is_set)
    return daemon, connection, hello


def assert_no_frame(connection, kind, quiet_s: float = QUIET_S):
    time.sleep(quiet_s)
    assert not connection.received(kind), f"unexpected {kind.__name__}: {connection.received(kind)}"


# Pairing


def test_first_start_pairs_and_says_hello(fake_master, node_configuration, start_daemon):
    configuration = node_configuration()
    daemon, connection, hello = connect(fake_master, start_daemon, configuration)

    [request] = fake_master.pairing_requests
    assert request.node_name == "test-node" and request.labels == {"site": "lab"}
    response = PairingState(configuration.state_dir).load().response
    assert connection.node_id == hello.node_id == response.node_id
    assert hello.node_name == "test-node"
    assert hello.software_revision == "test-revision"
    assert hello.capabilities == [CapabilityOffer(job_type=JobType.SCENE_GENERATION, slots=1), CapabilityOffer(job_type=JobType.SIMULATION_KINEMATIC, slots=2)]
    assert hello.labels == {"site": "lab"}
    assert hello.fingerprints == FINGERPRINTS
    assert hello.resources.cpus >= 1 and hello.resources.free_disk_mb > 0
    assert hello.running_lease_ids == []
    # The CA the job containers mount is the paired one.
    assert (configuration.trust_dir / "ca_certificate.pem").read_text() == fake_master.security.ca_certificate_pem


def test_heartbeats_follow_the_welcome_interval(fake_master, node_configuration, start_daemon):
    _, connection, _ = connect(fake_master, start_daemon, node_configuration())
    first = connection.expect(Heartbeat, skip=())
    second = connection.expect(Heartbeat, skip=())
    assert first.slots_in_use == {} and second.running_lease_ids == []


def test_later_start_reuses_the_pairing_without_a_token(fake_master, node_configuration, start_daemon):
    first = node_configuration()
    daemon, _, hello = connect(fake_master, start_daemon, first)
    daemon.stop()

    again = node_configuration(SCENEGEMS_PAIRING_TOKEN="")
    assert again.pairing_token is None
    _, _, second_hello = connect(fake_master, start_daemon, again)
    assert second_hello.node_id == hello.node_id
    assert len(fake_master.pairing_requests) == 1


def test_a_wrong_ca_hash_is_refused_before_the_token_is_sent(fake_master, node_configuration, start_daemon):
    other_ca = CertificateAuthority.create("other-master").certificate_pem.decode()
    from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import certificate_sha256

    configuration = node_configuration(SCENEGEMS_MASTER_CA_SHA256=certificate_sha256(other_ca))
    error = start_daemon(configuration).wait_exit()
    assert isinstance(error, CaPinMismatch)
    assert fake_master.pairing_requests == []
    assert not PairingState(configuration.state_dir).pairing_file.exists()


def test_a_master_serving_another_ca_is_refused(fake_master, node_configuration, start_daemon):
    fake_master.served_ca_certificate_pem = CertificateAuthority.create("impostor").certificate_pem.decode()
    error = start_daemon(node_configuration()).wait_exit()
    assert isinstance(error, CaPinMismatch)
    assert "Refusing to pair" in str(error)
    assert fake_master.pairing_requests == []


def test_a_used_token_is_refused(fake_master, node_configuration, start_daemon, tmp_path):
    configuration = node_configuration()
    daemon, _, _ = connect(fake_master, start_daemon, configuration)
    daemon.stop()
    from scenegems_tool.cluster.node.daemon.configuration.node_configuration import NodeConfiguration
    from scenegems_tool.cluster.node.daemon.pairing.pairing_client import PairingRefused
    from tests.scenegems_tool.cluster.node.daemon.conftest import node_values

    reused = NodeConfiguration.from_values(node_values(fake_master, tmp_path / "other-state", SCENEGEMS_PAIRING_TOKEN=configuration.pairing_token))
    error = start_daemon(reused).wait_exit()
    assert isinstance(error, PairingRefused)
    assert "HTTP 403" in str(error)


def test_a_revoked_credential_stops_the_daemon(fake_master, node_configuration, start_daemon):
    configuration = node_configuration()
    daemon, _, hello = connect(fake_master, start_daemon, configuration)
    daemon.stop()
    revoke_node_credential(fake_master.security.store, hello.node_id)

    error = start_daemon(node_configuration(SCENEGEMS_PAIRING_TOKEN="")).wait_exit()
    assert isinstance(error, DaemonStopped)
    assert "HTTP 403" in str(error) and "pair" in str(error)


# Leases


def test_offer_accept_renew_and_result(fake_master, node_configuration, start_daemon, jobs):
    fake_master.lease_timeout_s = 0.6  # renewals every 0.2 s
    _, connection, _ = connect(fake_master, start_daemon, node_configuration())
    job = make_job("job-a", payload={"steps": 3})
    connection.send(make_offer("lease-a", job))
    assert connection.expect(LeaseAccept).lease_id == "lease-a"
    assert jobs.wait_started() == "job-a"

    renewal = connection.expect(LeaseRenew, skip=(Heartbeat, JobStatus, LogLines))
    assert renewal.lease_id == "lease-a"
    heartbeat = connection.expect(Heartbeat, skip=(LeaseRenew, JobStatus, LogLines))
    assert heartbeat.slots_in_use == {JobType.SIMULATION_KINEMATIC: 1} and heartbeat.running_lease_ids == ["lease-a"]
    time.sleep(1.0)  # longer than the lease timeout: renewals keep the lease
    jobs.finish("job-a", {"state_digest": "abc"})

    result = connection.expect(JobResult)
    assert result.lease_id == "lease-a" and result.job_id == "job-a" and result.idempotency_key == "job-a/key"
    assert result.outcome == JobOutcome.SUCCEEDED and result.result == {"state_digest": "abc"}
    statuses, logs = connection.received(JobStatus), connection.received(LogLines)
    assert statuses and statuses[0].message == "running job-a" and statuses[0].progress == 0.1
    texts = [line.text for frame in logs for line in frame.lines]
    assert "started job-a" in texts and any("accepted on node" in text for text in texts)
    assert any(line.stream == LogStream.DAEMON for frame in logs for line in frame.lines)
    # Reports of a lease always reach the master before its result.
    result_index = connection.history.index(result)
    assert all(connection.history.index(frame) < result_index for frame in statuses + logs)


@pytest.mark.parametrize(
    "error, retryable",
    [(JobFailed("stack failed", retryable=True), True), (JobFailed("invalid payload", retryable=False), False), (RuntimeError("boom"), True)],
)
def test_a_failing_job_becomes_a_failed_result(fake_master, node_configuration, start_daemon, jobs, error, retryable):
    _, connection, _ = connect(fake_master, start_daemon, node_configuration())
    connection.send(make_offer("lease-f", make_job("job-f")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    jobs.fail("job-f", error)
    result = connection.expect(JobResult)
    assert result.outcome == JobOutcome.FAILED and result.retryable is retryable
    assert str(error) in result.error and result.result == {}


def test_offers_beyond_the_slots_are_rejected(fake_master, node_configuration, start_daemon, jobs):
    _, connection, _ = connect(fake_master, start_daemon, node_configuration())
    for lease_id in ("lease-1", "lease-2"):
        connection.send(make_offer(lease_id, make_job(f"job-{lease_id}")))
        connection.expect(LeaseAccept)
    connection.send(make_offer("lease-3", make_job("job-lease-3")))
    reject = connection.expect(LeaseReject)
    assert reject.lease_id == "lease-3" and "2 simulation.kinematic slots are in use" in reject.reason

    connection.send(make_offer("lease-t", make_job("job-t", job_type=JobType.TRAJECTORY_GENERATION)))
    assert "offers no trajectory_generation slots" in connection.expect(LeaseReject).reason
    connection.send(make_offer("lease-s", make_job("job-s", job_type=JobType.SCENE_GENERATION)))
    assert connection.expect(LeaseAccept).lease_id == "lease-s"

    jobs.wait_started(), jobs.wait_started()
    jobs.finish("job-lease-1")
    connection.expect(JobResult)
    connection.send(make_offer("lease-4", make_job("job-lease-4")))
    assert connection.expect(LeaseAccept).lease_id == "lease-4"
    assert jobs.most_running <= 3


def test_cancel_stops_the_job_and_frees_its_slot(fake_master, node_configuration, start_daemon, jobs):
    _, connection, _ = connect(fake_master, start_daemon, node_configuration(SCENEGEMS_NODE_CAPABILITIES="simulation.kinematic:1"))
    connection.send(make_offer("lease-c", make_job("job-c")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    connection.send(Cancel(lease_id="lease-c", job_id="job-c", reason="campaign stopped"))
    wait_for(lambda: jobs.cancelled == ["job-c"])
    connection.send(make_offer("lease-d", make_job("job-d")))
    assert connection.expect(LeaseAccept).lease_id == "lease-d"
    assert_no_frame(connection, JobResult)


def test_drain_rejects_new_leases_and_lets_running_ones_finish(fake_master, node_configuration, start_daemon, jobs):
    _, connection, _ = connect(fake_master, start_daemon, node_configuration())
    connection.send(make_offer("lease-r", make_job("job-r")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    connection.send(Drain(reason="maintenance"))
    connection.send(make_offer("lease-n", make_job("job-n")))
    reject = connection.expect(LeaseReject)
    assert reject.lease_id == "lease-n" and "draining (maintenance)" in reject.reason
    jobs.finish("job-r")
    assert connection.expect(JobResult).lease_id == "lease-r"


def test_running_jobs_survive_a_reconnect(fake_master, node_configuration, start_daemon, jobs):
    _, first, _ = connect(fake_master, start_daemon, node_configuration())
    first.send(make_offer("lease-k", make_job("job-k")))
    first.expect(LeaseAccept)
    jobs.wait_started()
    first.close()

    second = fake_master.wait_for_connection()
    hello = second.expect(Hello)
    assert hello.running_lease_ids == ["lease-k"]
    jobs.finish("job-k")
    result = second.expect(JobResult)
    assert result.lease_id == "lease-k" and result.outcome == JobOutcome.SUCCEEDED
    assert jobs.started.empty()  # the job ran once


def test_a_result_ready_while_disconnected_is_sent_after_the_reconnect(fake_master, node_configuration, start_daemon, jobs):
    daemon, first, _ = connect(fake_master, start_daemon, node_configuration(), welcome_timeout_s=0.5)
    first.send(make_offer("lease-w", make_job("job-w")))
    first.expect(LeaseAccept)
    jobs.wait_started()
    fake_master.hello_reply = lambda hello: None  # the master accepts connections but never welcomes
    first.close()
    wait_for(lambda: not daemon.daemon.connected.is_set())
    jobs.finish("job-w")
    time.sleep(0.3)
    assert not first.received(JobResult)

    fake_master.hello_reply = None
    wait_for(daemon.daemon.connected.is_set)
    connection = fake_master.all_connections[-1]  # the welcomed one; connections during the outage timed out
    result = connection.expect(JobResult, skip=(Hello, Heartbeat, JobStatus, LogLines, LeaseRenew))
    assert result.lease_id == "lease-w" and result.outcome == JobOutcome.SUCCEEDED


def test_a_lease_without_confirmed_renewals_is_given_up(fake_master, node_configuration, start_daemon, jobs):
    fake_master.lease_timeout_s = 0.5
    fake_master.renew_leases = False
    _, connection, _ = connect(fake_master, start_daemon, node_configuration(SCENEGEMS_NODE_CAPABILITIES="simulation.kinematic:1"))
    connection.send(make_offer("lease-l", make_job("job-l")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    wait_for(lambda: jobs.cancelled == ["job-l"], timeout_s=3.0)
    connection.send(make_offer("lease-m", make_job("job-m")))
    assert connection.expect(LeaseAccept).lease_id == "lease-m"
    assert not connection.received(JobResult)


def test_shutdown_releases_running_leases(fake_master, node_configuration, start_daemon, jobs):
    daemon, connection, _ = connect(fake_master, start_daemon, node_configuration())
    connection.send(make_offer("lease-s", make_job("job-s")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    daemon.stop()
    release = connection.expect(LeaseRelease)
    assert release.lease_id == "lease-s" and "stopped" in release.reason
    assert jobs.cancelled == ["job-s"]
    assert not connection.received(JobResult)


# Refusals by the master


def test_a_master_of_another_protocol_version_stops_the_daemon(fake_master, node_configuration, start_daemon):
    def newer_welcome(_hello):
        return json.dumps({"type": "welcome", "protocol_version": 2, "master_id": fake_master.security.master_id, "heartbeat_interval_s": 1.0, "lease_timeout_s": 3.0})

    fake_master.hello_reply = newer_welcome
    error = start_daemon(node_configuration()).wait_exit()
    assert isinstance(error, DaemonStopped)
    assert "received 2, this side speaks 1" in str(error)


def test_a_version_mismatch_error_from_the_master_stops_the_daemon(fake_master, node_configuration, start_daemon):
    fake_master.hello_reply = lambda _hello: ProtocolError(code=ProtocolErrorCode.VERSION_MISMATCH, message="master speaks 2")
    error = start_daemon(node_configuration()).wait_exit()
    assert isinstance(error, DaemonStopped) and "master speaks 2" in str(error)


def test_a_welcome_from_another_master_stops_the_daemon(fake_master, node_configuration, start_daemon):
    fake_master.hello_reply = lambda _hello: Welcome(master_id="other-master", heartbeat_interval_s=1.0, lease_timeout_s=3.0)
    error = start_daemon(node_configuration()).wait_exit()
    assert isinstance(error, DaemonStopped) and "'other-master'" in str(error)


def test_an_unreachable_master_is_retried_until_stopped(node_configuration, start_daemon):
    configuration = node_configuration(SCENEGEMS_MASTER_URL="https://127.0.0.1:9")  # nothing listens on the discard port
    daemon = start_daemon(configuration)
    time.sleep(0.5)
    assert daemon.thread.is_alive()
    daemon.stop()
    assert daemon.error is None
