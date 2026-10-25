"""The node's artifact client against the real artifact routes, served over TLS by the scripted master."""

import gzip
import hashlib
import json
import os
import urllib.error

import pytest

from scenegems_tool.cluster.master.api import artifact_routes
from scenegems_tool.cluster.node.artifacts import artifact_client
from scenegems_tool.cluster.node.artifacts.artifact_client import ArtifactClient, ArtifactHashMismatch, ArtifactTransferError
from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import verified_context
from scenegems_tool.cluster.protocol.artifacts import ArtifactKind, ArtifactRef
from scenegems_tool.cluster.protocol.pairing import PairingRequest
from scenegems_tool.cluster.security.credentials.pairing_tokens import create_pairing_token
from scenegems_tool.cluster.security.pairing import pair_node
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from tests.scenegems_tool.cluster.node.daemon.fake_master import FakeMaster
from tests.scenegems_tool.cluster.security.conftest import make_master_security
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords
from tests.scenegems_tool.persistence.stores.builders import ManualClock

DOCUMENT = json.dumps({"trajectories": {str(vessel): [[float(step), 1.5, 8.0, 0.25] for step in range(2000)] for vessel in range(3)}}, sort_keys=True).encode()
SHA = hashlib.sha256(DOCUMENT).hexdigest()


@pytest.fixture
def records():
    return InMemoryArtifactRecords(ManualClock())


@pytest.fixture
def master(tmp_path, records):
    security = make_master_security(tmp_path / "security", addresses=("127.0.0.1", "localhost"))
    artifacts = RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), records)
    with FakeMaster(security, artifacts=artifacts, max_artifact_bytes=10 * 1024 * 1024) as master:
        yield master


@pytest.fixture
def paired(master):
    return pair_node(master.security, PairingRequest(token=create_pairing_token(master.security.store).token, node_name="lab"))


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(master, paired, sleeps):
    return ArtifactClient(master.url, paired.node_credential, verified_context(master.security.ca_certificate_pem), sleep=sleeps.append, timeout_s=10)


def test_an_upload_and_its_download_round_trip_gzip_on_the_wire(client, master, records):
    reference = client.upload(DOCUMENT, ArtifactKind.TRAJECTORIES)
    assert reference == ArtifactRef(sha256=SHA, size_bytes=len(DOCUMENT), kind=ArtifactKind.TRAJECTORIES)
    assert master.artifacts.store.read(SHA) == DOCUMENT and records.get(SHA).kind == "trajectories"
    assert client.download(SHA) == DOCUMENT
    assert client.download(SHA, max_bytes=len(DOCUMENT)) == DOCUMENT
    assert client.upload(DOCUMENT, ArtifactKind.TRAJECTORIES) == reference  # stored already: the same reference


def test_an_upload_for_a_leased_job_becomes_the_job_s_reference(client, master, paired, records):
    master.leased_jobs["job-1"] = paired.node_id
    client.upload(DOCUMENT, ArtifactKind.TRAJECTORIES, job_id="job-1", field="trajectories")
    assert records.references == {(SHA, "job", "job-1", "result:trajectories")}
    with pytest.raises(ArtifactTransferError) as refused:
        client.upload(b"[2]", ArtifactKind.FRAMES, job_id="job-2", field="frames")
    assert refused.value.status == 409 and refused.value.retryable and "not leased to this node" in str(refused.value)


def test_a_missing_artifact_is_not_retryable(client, sleeps):
    with pytest.raises(ArtifactTransferError) as missing:
        client.download("5" * 64)
    assert missing.value.status == 404 and not missing.value.retryable and sleeps == []


def test_corrupt_content_at_the_master_fails_the_hash_check(client, master):
    path = master.artifacts.store.path(SHA)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(DOCUMENT.replace(b"8.0", b"9.0")))
    with pytest.raises(ArtifactHashMismatch) as corrupt:
        client.download(SHA)
    assert not corrupt.value.retryable and "hashes to" in str(corrupt.value)
    with pytest.raises(ArtifactHashMismatch):
        client.download(SHA, max_bytes=100)  # longer than its reference says


def test_an_upload_over_the_limit_is_not_retryable(client, master):
    large = os.urandom(10 * 1024 * 1024 + 1)
    with pytest.raises(ArtifactTransferError) as too_large:
        client.upload(large, ArtifactKind.FRAMES)
    assert too_large.value.status == 413 and not too_large.value.retryable


def test_a_refused_credential_is_retryable_for_the_job_but_not_retried_here(master, sleeps):
    client = ArtifactClient(master.url, "lab-1.wrong", verified_context(master.security.ca_certificate_pem), sleep=sleeps.append)
    with pytest.raises(ArtifactTransferError) as refused:
        client.download(SHA)
    assert refused.value.status == 401 and refused.value.retryable and sleeps == []


def test_connection_failures_and_server_errors_are_retried_with_backoff(client, monkeypatch, sleeps):
    client.upload(DOCUMENT, ArtifactKind.TRAJECTORIES)
    failures = [urllib.error.URLError(ConnectionResetError("reset")), urllib.error.HTTPError(client.url(SHA), 503, "unavailable", {}, None), TimeoutError("read timed out")]
    real_open = artifact_client.open_url

    def flaky_open(request, context, timeout_s):
        if failures:
            raise failures.pop(0)
        return real_open(request, context, timeout_s)

    monkeypatch.setattr(artifact_client, "open_url", flaky_open)
    assert client.download(SHA) == DOCUMENT
    assert sleeps == [0.5, 1.0, 2.0]


def test_a_transfer_that_keeps_failing_is_retryable_for_the_job(client, monkeypatch, sleeps):
    def broken(request, context, timeout_s):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(artifact_client, "open_url", broken)
    with pytest.raises(ArtifactTransferError) as failed:
        client.upload(DOCUMENT, ArtifactKind.TRAJECTORIES)
    assert failed.value.retryable and sleeps == [0.5, 1.0, 2.0] and "refused" in str(failed.value)


def test_another_ca_is_not_trusted(master, paired, tmp_path):
    other = make_master_security(tmp_path / "other", addresses=("127.0.0.1",))
    client = ArtifactClient(master.url, paired.node_credential, lambda: verified_context(other.ca_certificate_pem), sleep=lambda _s: None)
    with pytest.raises(ArtifactTransferError) as untrusted:
        client.download(SHA)
    assert "does not verify" in str(untrusted.value)


def test_the_master_writes_an_upload_as_it_arrives(client, master, monkeypatch):
    """Over a real socket the body arrives in pieces, and each piece is written before the next is read."""
    monkeypatch.setattr(artifact_routes, "STREAM_CHUNK_BYTES", 64 * 1024)
    writes = []
    writer_of = master.artifacts.writer

    def spying_writer(sha256, max_bytes=None):
        writer = writer_of(sha256, max_bytes)
        write = writer.write
        writer.write = lambda data: writes.append(len(data)) or write(data)
        return writer

    monkeypatch.setattr(master.artifacts, "writer", spying_writer)
    data = os.urandom(3 * 1024 * 1024)  # incompressible, so the gzip body is as large
    client.upload(data, ArtifactKind.FRAMES)
    assert sum(writes) == len(data) and len(writes) > 10 and max(writes) <= 64 * 1024
