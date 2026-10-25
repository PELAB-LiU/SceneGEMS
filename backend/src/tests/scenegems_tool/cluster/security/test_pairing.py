from datetime import timedelta

import pytest

from scenegems_tool.cluster.protocol.pairing import PairingRequest, PairingResponse
from scenegems_tool.cluster.security.credentials.broker_accounts import verify_broker_login
from scenegems_tool.cluster.security.credentials.node_credentials import authenticate_node
from scenegems_tool.cluster.security.credentials.pairing_tokens import create_pairing_token
from scenegems_tool.cluster.security.pairing import PairingTokenRejected, new_node_id, pair_node
from scenegems_tool.cluster.security.scope_names import is_scope_name


def _pair(master_security, node_name="Lab PC 1", labels=None):
    token = create_pairing_token(master_security.store).token
    return pair_node(master_security, PairingRequest(token=token, node_name=node_name, labels=labels or {}))


def test_pairing_returns_working_credentials(master_security):
    response = _pair(master_security, labels={"gpu": "no"})
    assert response.master_id == "lab-master"
    assert response.node_id.startswith("lab-pc-1-") and is_scope_name(response.node_id)
    assert authenticate_node(master_security.store, response.node_credential) == response.node_id
    assert response.broker.username == response.node_id
    assert verify_broker_login(master_security.store, response.broker.username, response.broker.password)
    assert master_security.store.get_node_credential(response.node_id).labels == {"gpu": "no"}


def test_pairing_response_points_at_the_broker_with_tls_and_the_node_scope(master_security):
    response = _pair(master_security)
    assert (response.broker.host, response.broker.port, response.broker.tls) == ("192.168.1.10", 8883, True)
    assert response.broker.topic_scope == f"scenegems/lab-master/{response.node_id}"
    assert response.ca_certificate_pem == master_security.layout.ca_certificate.read_text()


def test_pairing_response_survives_the_wire(master_security):
    response = _pair(master_security)
    assert PairingResponse.model_validate_json(response.model_dump_json()) == response


def test_a_token_pairs_one_node_only(master_security):
    token = create_pairing_token(master_security.store).token
    pair_node(master_security, PairingRequest(token=token, node_name="lab 1"))
    with pytest.raises(PairingTokenRejected):
        pair_node(master_security, PairingRequest(token=token, node_name="lab 2"))


def test_expired_token_pairs_nothing(master_security, instant):
    token = create_pairing_token(master_security.store, lifetime=timedelta(minutes=5), now=instant).token
    with pytest.raises(PairingTokenRejected, match="expired"):
        pair_node(master_security, PairingRequest(token=token, node_name="lab 1"), now=instant + timedelta(minutes=6))
    assert list((master_security.layout.store_folder / "node_credentials").glob("*")) == []


def test_two_nodes_with_the_same_name_get_different_ids(master_security):
    first, second = _pair(master_security, "lab"), _pair(master_security, "lab")
    assert first.node_id != second.node_id
    assert first.broker.topic_scope != second.broker.topic_scope


def test_node_ids_from_awkward_names_are_scope_names():
    for name in ["", "!!!", "Gazebo Box #2 / GPU", "x" * 200]:
        assert is_scope_name(new_node_id(name)), name
