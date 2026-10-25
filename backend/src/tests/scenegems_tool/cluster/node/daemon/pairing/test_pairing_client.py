import json

import pytest

from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import verified_context
from scenegems_tool.cluster.node.daemon.pairing.pairing_client import PairingRefused, decode_pairing_response, request_pairing
from scenegems_tool.cluster.protocol.pairing import PairingRequest
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch
from scenegems_tool.cluster.security.credentials.pairing_tokens import create_pairing_token


def test_a_valid_token_returns_the_node_credentials(fake_master):
    token = create_pairing_token(fake_master.security.store).token
    response = request_pairing(fake_master.url, verified_context(fake_master.security.ca_certificate_pem), PairingRequest(token=token, node_name="worker 1", labels={"gpu": "yes"}))
    assert response.master_id == fake_master.security.master_id
    assert response.node_id.startswith("worker-1-")
    assert response.node_credential.startswith(f"{response.node_id}.")
    assert response.broker.username == response.node_id
    assert fake_master.pairing_requests[0].labels == {"gpu": "yes"}


def test_an_unknown_token_is_refused_with_the_master_s_reason(fake_master):
    with pytest.raises(PairingRefused, match="HTTP 403: pairing token rejected"):
        request_pairing(fake_master.url, verified_context(fake_master.security.ca_certificate_pem), PairingRequest(token="guessed", node_name="worker"))


def test_the_version_is_checked_before_the_fields():
    with pytest.raises(ProtocolVersionMismatch):
        decode_pairing_response(json.dumps({"protocol_version": 2, "something": "else"}).encode())
    with pytest.raises(PairingRefused, match="not JSON"):
        decode_pairing_response(b"<html>")
    with pytest.raises(PairingRefused, match="not a JSON object"):
        decode_pairing_response(b"[]")
