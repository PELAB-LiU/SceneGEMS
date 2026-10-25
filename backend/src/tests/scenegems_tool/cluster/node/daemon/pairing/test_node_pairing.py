"""Pairing without a network: the network call is replaced, the checks and the state folder are real."""

import json
import os
import stat

import pytest

from scenegems_tool.cluster.node.daemon.configuration.node_configuration import NodeConfiguration
from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import CaPinMismatch, certificate_sha256
from scenegems_tool.cluster.node.daemon.pairing.node_pairing import NotPaired, ensure_paired
from scenegems_tool.cluster.node.daemon.pairing.pairing_state import PAIRING_FILE_NAME, PairingState, PairingStateError
from scenegems_tool.cluster.protocol.pairing import BrokerAccess, PairingResponse
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch
from scenegems_tool.cluster.security.certificates.certificate_authority import CertificateAuthority


@pytest.fixture(scope="module")
def ca_pem() -> str:
    return CertificateAuthority.create("lab-master").certificate_pem.decode("ascii")


def response(ca_pem: str, master_id: str = "lab-master") -> PairingResponse:
    return PairingResponse(
        master_id=master_id,
        node_id="worker-1-abc123",
        node_credential="worker-1-abc123.secret-value",
        ca_certificate_pem=ca_pem,
        broker=BrokerAccess(host="192.168.1.10", port=8883, username="worker-1-abc123", password="broker-secret", topic_scope=f"scenegems/{master_id}/worker-1-abc123"),
    )


def configuration(tmp_path, ca_pem: str, **changes) -> NodeConfiguration:
    values = {
        "SCENEGEMS_MASTER_URL": "https://192.168.1.10:8443",
        "SCENEGEMS_MASTER_ID": "lab-master",
        "SCENEGEMS_MASTER_CA_SHA256": certificate_sha256(ca_pem),
        "SCENEGEMS_PAIRING_TOKEN": "one-time-token",
        "SCENEGEMS_NODE_NAME": "worker-1",
        "SCENEGEMS_NODE_CAPABILITIES": "simulation.kinematic:1",
        "SCENEGEMS_NODE_STATE_DIR": str(tmp_path / "state"),
    }
    values.update(changes)
    return NodeConfiguration.from_values({key: value for key, value in values.items() if value})


def test_first_start_pairs_and_stores_the_response(tmp_path, ca_pem):
    calls = []
    stored = ensure_paired(configuration(tmp_path, ca_pem), pair=lambda config: calls.append(config) or response(ca_pem))
    assert len(calls) == 1
    assert stored.response.node_id == "worker-1-abc123" and stored.master_url == "https://192.168.1.10:8443"
    state = PairingState(tmp_path / "state")
    document = json.loads(state.pairing_file.read_text())
    assert document["response"]["node_credential"] == "worker-1-abc123.secret-value"  # the secrets are in the file, not in repr
    assert document["master_ca_sha256"] == certificate_sha256(ca_pem)
    assert state.ca_certificate_file.read_text() == ca_pem
    assert (tmp_path / "state" / "trust" / "ca_certificate.pem").read_text() == ca_pem
    assert list((tmp_path / "state" / "trust").iterdir()) == [tmp_path / "state" / "trust" / "ca_certificate.pem"]  # nothing secret where containers look


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_the_pairing_file_and_folder_are_owner_only(tmp_path, ca_pem):
    ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(ca_pem))
    assert stat.S_IMODE((tmp_path / "state" / PAIRING_FILE_NAME).stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "state").stat().st_mode) == 0o700


def test_later_starts_reuse_the_pairing_and_need_no_token(tmp_path, ca_pem):
    ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(ca_pem))
    (tmp_path / "state" / "trust" / "ca_certificate.pem").unlink()

    def must_not_pair(_):
        raise AssertionError("paired twice")

    stored = ensure_paired(configuration(tmp_path, ca_pem, SCENEGEMS_PAIRING_TOKEN=""), pair=must_not_pair)
    assert stored.response.node_credential == "worker-1-abc123.secret-value"
    assert (tmp_path / "state" / "trust" / "ca_certificate.pem").read_text() == ca_pem  # rewritten at every start


def test_without_pairing_and_token_the_start_fails_clearly(tmp_path, ca_pem):
    with pytest.raises(NotPaired, match="SCENEGEMS_PAIRING_TOKEN"):
        ensure_paired(configuration(tmp_path, ca_pem, SCENEGEMS_PAIRING_TOKEN=""), pair=lambda _: response(ca_pem))


def test_an_answer_from_another_master_is_not_stored(tmp_path, ca_pem):
    with pytest.raises(PairingStateError, match="'other-master'"):
        ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(ca_pem, master_id="other-master"))
    assert not (tmp_path / "state" / PAIRING_FILE_NAME).exists()


def test_an_answer_with_another_ca_is_not_stored(tmp_path, ca_pem):
    other = CertificateAuthority.create("other").certificate_pem.decode("ascii")
    with pytest.raises(CaPinMismatch):
        ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(other))
    assert not (tmp_path / "state" / PAIRING_FILE_NAME).exists()


def test_a_stored_pairing_of_another_master_is_refused(tmp_path, ca_pem):
    ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(ca_pem))
    with pytest.raises(PairingStateError, match="belongs to master 'lab-master'"):
        ensure_paired(configuration(tmp_path, ca_pem, SCENEGEMS_MASTER_ID="second-master"), pair=lambda _: response(ca_pem))


def test_a_stored_pairing_with_another_ca_hash_is_refused(tmp_path, ca_pem):
    ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(ca_pem))
    with pytest.raises(PairingStateError, match="Remove the node's state volume"):
        ensure_paired(configuration(tmp_path, ca_pem, SCENEGEMS_MASTER_CA_SHA256="1" * 64), pair=lambda _: response(ca_pem))


def test_an_unreadable_state_file_names_the_way_out(tmp_path, ca_pem):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / PAIRING_FILE_NAME).write_text("{broken")
    with pytest.raises(PairingStateError, match="Remove the node's state volume"):
        ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(ca_pem))


def test_a_stored_pairing_of_another_protocol_version_is_refused(tmp_path, ca_pem):
    ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(ca_pem))
    path = tmp_path / "state" / PAIRING_FILE_NAME
    document = json.loads(path.read_text())
    document["response"]["protocol_version"] = 99
    path.write_text(json.dumps(document))
    with pytest.raises(PairingStateError, match="received 99"):
        ensure_paired(configuration(tmp_path, ca_pem), pair=lambda _: response(ca_pem))
    assert issubclass(ProtocolVersionMismatch, ValueError)  # why load() reports it as a state error
